package traffic

import (
	"context"
	"fmt"
	"log"
	"math"
	"strings"
	"sync"
	"time"

	appmetrics "github.com/shark-platform/traffic-service/internal/pkg/metrics"
	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
)

const (
	defaultCHBatchRows     = 5000
	defaultCHFlushInterval = 5 * time.Second
	defaultCHIngestCap     = 65536
	defaultCHInsertTimeout = 90 * time.Second
	defaultCHMaxAttempts   = 4
)

// ClickHouseWriterConfig 批量写入器参数。
type ClickHouseWriterConfig struct {
	Database string
	Table    string

	MaxBatch int           // 达到条数触发 flush
	Interval time.Duration // 定时 flush
	InCap    int           // 输入 channel 容量（背压）

	InsertTimeout time.Duration
	MaxAttempts   int
}

// DefaultClickHouseWriterConfig 从应用 Config 填默认值。
func DefaultClickHouseWriterConfig(database, table string, maxBatch, flushSec, inCap int) ClickHouseWriterConfig {
	if database == "" {
		database = "traffic"
	}
	if table == "" {
		table = "traffic_log_raw"
	}
	if maxBatch <= 0 {
		maxBatch = defaultCHBatchRows
	}
	interval := time.Duration(flushSec) * time.Second
	if interval <= 0 {
		interval = defaultCHFlushInterval
	}
	if inCap <= 0 {
		inCap = defaultCHIngestCap
	}
	return ClickHouseWriterConfig{
		Database:      database,
		Table:         table,
		MaxBatch:      maxBatch,
		Interval:      interval,
		InCap:         inCap,
		InsertTimeout: defaultCHInsertTimeout,
		MaxAttempts:   defaultCHMaxAttempts,
	}
}

// chLogRow 对应 traffic.traffic_log_raw 单行（值类型，经 channel 传递副本）。
type chLogRow struct {
	Timestamp time.Time
	Source    string
	IP        string
	Method    string
	Path      string
	Status    uint16
	Duration  float64
	LatencyMs float64
	Country   string
	Referer   string
	UserAgent string
	BodyBytes uint64
}

// ClickHouseWriter 单协程将 Worker 投递的行写入 chBatchBuffer，定时或满批 PrepareBatch 发送。
type ClickHouseWriter struct {
	conn driver.Conn
	cfg  ClickHouseWriterConfig

	ingest chan chLogRow
	// chBatchBuffer 仅在 loop 协程内读写：flush 后 [:0] 复用底层数组以降低 GC。
	chBatchBuffer []chLogRow

	wg     sync.WaitGroup
	cancel context.CancelFunc
}

// NewClickHouseWriter 创建写入器（需调用 Start）。
func NewClickHouseWriter(conn driver.Conn, cfg ClickHouseWriterConfig) *ClickHouseWriter {
	return &ClickHouseWriter{
		conn:          conn,
		cfg:           cfg,
		ingest:        make(chan chLogRow, cfg.InCap),
		chBatchBuffer: make([]chLogRow, 0, cfg.MaxBatch),
	}
}

// Start 启动 ClickHouseWriter 协程。
func (w *ClickHouseWriter) Start(ctx context.Context) {
	ctx, cancel := context.WithCancel(ctx)
	w.cancel = cancel
	w.wg.Add(1)
	go w.loop(ctx)
}

// Stop 取消上下文并等待最后一次 flush（尽力 drain ingest channel）。
func (w *ClickHouseWriter) Stop() {
	if w.cancel != nil {
		w.cancel()
	}
	w.wg.Wait()
}

// EnqueueCleaned 阻塞入队（背压由 ingest channel 与 Worker 共同承担，避免静默丢数）。
func (w *ClickHouseWriter) EnqueueCleaned(rec CleanedRecord, recvAt time.Time) {
	w.ingest <- cleanedToCHRow(rec, recvAt)
}

func (w *ClickHouseWriter) loop(ctx context.Context) {
	defer w.wg.Done()
	tick := time.NewTicker(w.cfg.Interval)
	defer tick.Stop()

	flush := func(reason string) {
		n := len(w.chBatchBuffer)
		if n == 0 {
			return
		}
		insertCtx := context.Background()
		if err := w.insertBatchRetry(insertCtx, w.chBatchBuffer); err != nil {
			log.Printf("traffic clickhouse: insert failed reason=%s rows=%d err=%v (buffer retained for retry)", reason, n, err)
			return
		}
		w.chBatchBuffer = w.chBatchBuffer[:0]
	}

	for {
		select {
		case <-ctx.Done():
			tick.Stop()
			w.drainIngestNonBlocking(flush)
			flush("stop")
			return
		case r := <-w.ingest:
			w.chBatchBuffer = append(w.chBatchBuffer, r)
			if len(w.chBatchBuffer) >= w.cfg.MaxBatch {
				flush("size")
			}
		case <-tick.C:
			flush("tick")
		}
	}
}

func (w *ClickHouseWriter) drainIngestNonBlocking(flush func(string)) {
	for {
		select {
		case r := <-w.ingest:
			w.chBatchBuffer = append(w.chBatchBuffer, r)
			if len(w.chBatchBuffer) >= w.cfg.MaxBatch {
				flush("drain_chunk")
			}
		default:
			return
		}
	}
}

func (w *ClickHouseWriter) insertBatchRetry(ctx context.Context, rows []chLogRow) error {
	if len(rows) == 0 {
		return nil
	}
	attempts := w.cfg.MaxAttempts
	if attempts <= 0 {
		attempts = defaultCHMaxAttempts
	}
	timeout := w.cfg.InsertTimeout
	if timeout <= 0 {
		timeout = defaultCHInsertTimeout
	}

	t0 := time.Now()
	var lastErr error
	backoff := 200 * time.Millisecond
	for i := 0; i < attempts; i++ {
		if i > 0 {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(backoff):
			}
			if backoff < 5*time.Second {
				backoff *= 2
			}
		}
		attemptCtx, cancel := context.WithTimeout(ctx, timeout)
		lastErr = w.doInsert(attemptCtx, rows)
		cancel()
		if lastErr == nil {
			appmetrics.CHBatchWriteLatencySeconds.Observe(time.Since(t0).Seconds())
			return nil
		}
	}
	return lastErr
}

func (w *ClickHouseWriter) doInsert(ctx context.Context, rows []chLogRow) error {
	q := fmt.Sprintf(
		`INSERT INTO %s.%s (`+"`timestamp`"+`, source, ip, method, path, status, duration, latency_ms, country_code, referer, user_agent, body_bytes_sent)`,
		w.cfg.Database,
		w.cfg.Table,
	)
	batch, err := w.conn.PrepareBatch(ctx, q)
	if err != nil {
		return err
	}
	for i := range rows {
		r := &rows[i]
		if err := batch.Append(
			r.Timestamp,
			r.Source,
			r.IP,
			chMethodEnum(r.Method),
			r.Path,
			r.Status,
			r.Duration,
			r.LatencyMs,
			chCountryFixed(r.Country),
			r.Referer,
			r.UserAgent,
			r.BodyBytes,
		); err != nil {
			_ = batch.Abort()
			return err
		}
	}
	return batch.Send()
}

func cleanedToCHRow(rec CleanedRecord, recvAt time.Time) chLogRow {
	ts := eventTimestamp(rec, recvAt)
	dur := rec.RequestTimeS
	lat := 0.0
	if dur > 0 {
		lat = math.Round(dur * 1000)
	}
	st := rec.Status
	if st < 0 {
		st = 0
	}
	if st > 65535 {
		st = 65535
	}
	return chLogRow{
		Timestamp: ts,
		Source:    rec.Source,
		IP:        rec.RemoteAddr,
		Method:    rec.Method,
		Path:      PathForStore(rec.RequestURI),
		Status:    uint16(st),
		Duration:  dur,
		LatencyMs: lat,
		Country:   rec.CountryISO,
		Referer:   rec.Referer,
		UserAgent: rec.UserAgent,
		BodyBytes: rec.BodyBytesSent,
	}
}

func eventTimestamp(rec CleanedRecord, recvAt time.Time) time.Time {
	if rec.MSecUnix > 0 {
		sec, frac := math.Modf(rec.MSecUnix)
		ns := int64(math.Round(frac * 1e9))
		return time.Unix(int64(sec), ns).UTC().Truncate(time.Millisecond)
	}
	return recvAt.UTC().Truncate(time.Millisecond)
}

func chCountryFixed(cc string) string {
	cc = strings.ToUpper(strings.TrimSpace(cc))
	if len(cc) != 2 {
		return "ZZ"
	}
	return cc[:2]
}

func chMethodEnum(m string) string {
	switch strings.ToUpper(strings.TrimSpace(m)) {
	case "GET":
		return "GET"
	case "HEAD":
		return "HEAD"
	case "POST":
		return "POST"
	case "PUT":
		return "PUT"
	case "PATCH":
		return "PATCH"
	case "DELETE":
		return "DELETE"
	case "OPTIONS":
		return "OPTIONS"
	case "CONNECT":
		return "CONNECT"
	case "TRACE":
		return "TRACE"
	default:
		return "UNKNOWN"
	}
}
