package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Prometheus 指标（GET /metrics）。命名尽量贴近监控约定（*_total、latency *_seconds）。
var (
	CHBatchWriteLatencySeconds = promauto.NewHistogram(prometheus.HistogramOpts{
		Namespace: "traffic",
		Name:      "clickhouse_batch_write_latency_seconds",
		Help:      "Successful ClickHouse batch INSERT latency (seconds).",
		Buckets:   prometheus.ExponentialBuckets(0.001, 2, 16),
	})

	WorkerPanicTotal = promauto.NewCounter(prometheus.CounterOpts{
		Namespace: "traffic",
		Name:      "worker_panic_total",
		Help:      "Ingest worker / line parser panic recoveries (semantic: worker_panic_count).",
	})
)

// QueueLenProvider 队列深度观测（每个 scrape 读当前 len）。
type QueueLenProvider interface {
	IngestQueueLen() int
}

// RegisterLogQueueGaugeFunc 注册 traffic_log_queue_length（等价语义：log_queue_length）。
func RegisterLogQueueGaugeFunc(provider QueueLenProvider) {
	if provider == nil {
		return
	}
	prometheus.MustRegister(prometheus.NewGaugeFunc(
		prometheus.GaugeOpts{
			Namespace: "traffic",
			Name:      "log_queue_length",
			Help:      "Ingest pipeline channel backlog (chunks awaiting worker).",
		},
		func() float64 {
			return float64(provider.IngestQueueLen())
		},
	))
}
