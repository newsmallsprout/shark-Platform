package traffic

import (
	"context"
	"strings"
	"time"

	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
	"gorm.io/gorm"

	"github.com/shark-platform/traffic-service/internal/config"
	appgeoip "github.com/shark-platform/traffic-service/internal/pkg/geoip"
)

// SnapshotQuery 对应 Django snapshot 查询参数。
type SnapshotQuery struct {
	Range    string
	Source   string
	StartISO string
	EndISO   string
	FullData bool
}

// IngestEnqueueResult Handler 立即返回时的元信息（不做 JSON 解析）。
type IngestEnqueueResult struct {
	Queued   bool `json:"queued"`
	Bytes    int  `json:"bytes,omitempty"`
	Accepted int  `json:"accepted"` // 按换行粗估的行数（JSON envelope 模式下可能与真实条数有偏差）
}

// Service 聚合 ingest / snapshot 依赖。
type Service struct {
	DB                *gorm.DB
	Geo               *appgeoip.Reader
	ingest            *IngestPipeline
	agg               *Aggregator
	chWriter          *ClickHouseWriter
	chConn            driver.Conn
	chDatabase        string
	chRollupTable     string
	chSnapshotTimeout time.Duration
	snap              SnapshotEnv
}

func New(db *gorm.DB, geo *appgeoip.Reader, ingestCfg IngestPipelineConfig, snap SnapshotEnv, chConn driver.Conn, appCfg config.Config) *Service {
	var agg *Aggregator
	if chConn == nil {
		agg = NewAggregator()
	}

	var chw *ClickHouseWriter
	if chConn != nil {
		wcfg := DefaultClickHouseWriterConfig(
			appCfg.ClickHouseDatabase,
			appCfg.ClickHouseTable,
			appCfg.ClickHouseBatchRows,
			appCfg.ClickHouseFlushSec,
			appCfg.ClickHouseIngestCap,
		)
		chw = NewClickHouseWriter(chConn, wcfg)
		chw.Start(context.Background())
	}

	chSnapMS := appCfg.ClickHouseSnapshotTimeoutMs
	if chSnapMS <= 0 {
		chSnapMS = 25000
	}
	chRollup := strings.TrimSpace(appCfg.ClickHouseRollupTable)
	if chRollup == "" {
		chRollup = "traffic_rollup_min_local"
	}
	chDB := strings.TrimSpace(appCfg.ClickHouseDatabase)
	if chDB == "" {
		chDB = "traffic"
	}

	pipe := NewIngestPipeline(geo, agg, chw, ingestCfg)
	pipe.Start()

	if agg != nil && db != nil {
		agg.StartFlushLoop(context.Background(), db, defaultFlushLagMinutes)
	}

	return &Service{
		DB: db, Geo: geo, ingest: pipe, agg: agg,
		chWriter:          chw,
		chConn:            chConn,
		chDatabase:        chDB,
		chRollupTable:     chRollup,
		chSnapshotTimeout: time.Duration(chSnapMS) * time.Millisecond,
		snap:              snap,
	}
}

// IngestQueueLen 暴露 ingest channel 深度（Prometheus）。
func (s *Service) IngestQueueLen() int {
	if s.ingest == nil {
		return 0
	}
	return s.ingest.QueueLen()
}

// ShutdownGraceful 排空 ingest → 刷 ClickHouse → 关连接（SIGTERM 路径）。
func (s *Service) ShutdownGraceful() {
	s.ingest.CloseQueueAndDrain()
	if s.chWriter != nil {
		s.chWriter.Stop()
	}
	if s.chConn != nil {
		_ = s.chConn.Close()
	}
}

// EnqueueIngest 异步 ingest：仅复制并入队，连接立即返回。
func (s *Service) EnqueueIngest(source string, raw []byte) (*IngestEnqueueResult, error) {
	n := len(raw)
	est := 0
	if n > 0 {
		est = bytesCountNL(raw) + 1
	}
	if err := s.ingest.Enqueue(source, raw); err != nil {
		return nil, err
	}
	return &IngestEnqueueResult{Queued: true, Bytes: n, Accepted: est}, nil
}

func bytesCountNL(b []byte) int {
	c := 0
	for _, x := range b {
		if x == '\n' {
			c++
		}
	}
	return c
}

// Snapshot GET /api/traffic/snapshot：已配置 ClickHouse 时读 AggregatingMergeTree；否则 PG + 内存。
func (s *Service) Snapshot(ctx context.Context, q SnapshotQuery) (map[string]any, error) {
	if s.chConn != nil {
		return BuildClickHouseRollupSnapshot(ctx, s.chConn, s.snap, q, s.chDatabase, s.chRollupTable, s.chSnapshotTimeout)
	}
	return BuildRollupSnapshot(s.DB, s.agg, s.snap, q)
}
