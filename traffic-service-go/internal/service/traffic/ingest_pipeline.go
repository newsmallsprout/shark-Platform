package traffic

import (
	"bytes"
	"encoding/json"
	"log"
	"runtime/debug"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	appmetrics "github.com/shark-platform/traffic-service/internal/pkg/metrics"
	appgeoip "github.com/shark-platform/traffic-service/internal/pkg/geoip"
)

const (
	defaultQueueDepth = 10000
	defaultWorkers    = 20
)

// ingestChunk CSP 队列元素：保留数据源标识 + 原始 Body（禁止在 Handler 内解析 JSON）。
type ingestChunk struct {
	Source  string
	Payload []byte
}

// IngestPipelineConfig Worker / 队列容量。
type IngestPipelineConfig struct {
	QueueDepth int
	Workers    int
}

func defaultIngestPipelineConfig(cfg IngestPipelineConfig) IngestPipelineConfig {
	if cfg.QueueDepth <= 0 {
		cfg.QueueDepth = defaultQueueDepth
	}
	if cfg.Workers <= 0 {
		cfg.Workers = defaultWorkers
	}
	return cfg
}

// IngestPipeline 使用带缓冲 channel（默认深度 10000）搬运 Raw Body，
// 等价于 CSP 模型下的 logQueue，额外附带 HTTP 层的 source 标识。
type IngestPipeline struct {
	geo    *appgeoip.Reader
	agg    *Aggregator
	ch     *ClickHouseWriter
	queue  chan ingestChunk
	cfg    IngestPipelineConfig
	wg     sync.WaitGroup

	shuttingDown atomic.Uint32 // 1 = 拒绝入队（先于 close(queue)）
	closeOnce    sync.Once

	accessLinePool sync.Pool
	envPool        sync.Pool
}

// NewIngestPipeline 创建流水线（需调用 Start）。
// ch 非 nil 时：清洗结果进入 ClickHouse 批量缓冲区，不再写入内存聚合器（大批量写入路径）。
// ch 为 nil 且 agg 非 nil 时：保持原内存聚合 + PG flush。
func NewIngestPipeline(geo *appgeoip.Reader, agg *Aggregator, ch *ClickHouseWriter, cfg IngestPipelineConfig) *IngestPipeline {
	cfg = defaultIngestPipelineConfig(cfg)
	p := &IngestPipeline{
		geo:   geo,
		agg:   agg,
		ch:    ch,
		queue: make(chan ingestChunk, cfg.QueueDepth),
		cfg:   cfg,
	}
	p.accessLinePool.New = func() any { return &AccessLineRaw{} }
	p.envPool.New = func() any { return &linesEnvelope{} }
	return p
}

type linesEnvelope struct {
	Lines []json.RawMessage `json:"lines"`
}

// Start 启动 Worker Pool（通过 CloseQueueAndDrain + channel close 结束）。
func (p *IngestPipeline) Start() {
	for i := 0; i < p.cfg.Workers; i++ {
		p.wg.Add(1)
		go p.worker(i)
	}
}

// QueueLen 当前 ingest 队列积压（用于 Prometheus traffic_log_queue_length）。
func (p *IngestPipeline) QueueLen() int {
	return len(p.queue)
}

// CloseQueueAndDrain 标记停机、关闭 queue，并等待 Worker 消费完已有 chunk。
func (p *IngestPipeline) CloseQueueAndDrain() {
	p.shuttingDown.Store(1)
	p.closeOnce.Do(func() {
		close(p.queue)
	})
	p.wg.Wait()
}

// Enqueue 复制 payload 后入队；阻塞直至有缓冲槽（背压）。停机后返回 ErrIngestShuttingDown。
func (p *IngestPipeline) Enqueue(source string, payload []byte) error {
	if p.shuttingDown.Load() != 0 {
		return ErrIngestShuttingDown
	}
	if len(payload) == 0 {
		return nil
	}
	dup := make([]byte, len(payload))
	copy(dup, payload)
	p.queue <- ingestChunk{Source: strings.TrimSpace(source), Payload: dup}
	return nil
}

func (p *IngestPipeline) worker(id int) {
	defer p.wg.Done()
	for job := range p.queue {
		func() {
			defer func() {
				if r := recover(); r != nil {
					appmetrics.WorkerPanicTotal.Inc()
					log.Printf("ingest worker %d panic: %v\n%s", id, r, debug.Stack())
				}
			}()
			p.processChunk(job)
		}()
	}
}

func (p *IngestPipeline) processChunk(job ingestChunk) {
	payload := bytes.TrimSpace(job.Payload)
	if len(payload) == 0 {
		return
	}

	env := p.envPool.Get().(*linesEnvelope)
	*env = linesEnvelope{}
	if err := json.Unmarshal(payload, env); err == nil && len(env.Lines) > 0 {
		linesCopy := append([]json.RawMessage(nil), env.Lines...)
		p.envPool.Put(env)
		for _, lm := range linesCopy {
			if len(lm) == 0 {
				continue
			}
			p.processOneLineRecover(job.Source, lm)
		}
		return
	}
	p.envPool.Put(env)

	for _, line := range bytes.Split(payload, []byte("\n")) {
		line = bytes.TrimSpace(line)
		if len(line) == 0 {
			continue
		}
		p.processOneLineRecover(job.Source, line)
	}
}

func (p *IngestPipeline) processOneLineRecover(source string, line []byte) {
	defer func() {
		if r := recover(); r != nil {
			appmetrics.WorkerPanicTotal.Inc()
			log.Printf("ingest line panic: %v\n%s", r, debug.Stack())
		}
	}()
	p.processOneLine(source, line)
}

func (p *IngestPipeline) processOneLine(source string, line []byte) {
	raw := p.accessLinePool.Get().(*AccessLineRaw)
	defer func() {
		*raw = AccessLineRaw{}
		p.accessLinePool.Put(raw)
	}()

	if err := json.Unmarshal(line, raw); err != nil {
		return
	}

	ip := firstForwardedIP(raw.RemoteAddr)
	country := ""
	if p.geo != nil {
		country = p.geo.LookupCountryISOCode(ip)
	}

	rec := CleanedRecord{
		Source:        source,
		RemoteAddr:    ip,
		CountryISO:    country,
		Method:        raw.Method,
		Referer:       raw.Referer,
		UserAgent:     raw.UserAgent,
		BodyBytesSent: parseBodyBytesSent(raw.BodyBytes),
		RequestURI:    raw.RequestURI,
		Status:        raw.Status,
		RequestTimeS:  parseRequestTimeSeconds(raw.RequestTime),
		MSecUnix:      parseMSecUnix(raw.MSec),
	}

	recvAt := time.Now().UTC()
	if p.ch != nil {
		p.ch.EnqueueCleaned(rec, recvAt)
		return
	}
	if p.agg != nil {
		p.agg.Add(rec, recvAt)
	}
}
