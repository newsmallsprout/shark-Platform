package traffic

import (
	"fmt"
	"hash/fnv"
	"math"
	"strconv"
	"strings"
	"sync"
	"time"

	hdrhistogram "github.com/HdrHistogram/hdrhistogram-go"
)

const (
	aggKeySep      = "\x1f" // source 中勿包含该分隔符（内部 key；对外等价 source_minuteEpoch）
	shardCount     = 256
	maxPathKeys    = 4096
	maxLatencyMs   = 600_000 // 直方图上界：单次请求延迟 ms（10min）
	histSigFigures = 3
)

// Aggregator 内存分钟聚合器：分片锁 map，避免全局互斥与 sync.Map 写扩散。
type Aggregator struct {
	shards [shardCount]*aggShard
}

type aggShard struct {
	mu   sync.Mutex
	data map[string]*minuteBucket // key = aggMapKey(source, minuteUnix) → [source]_[分钟时间戳]
}

type minuteBucket struct {
	requests   uint64
	status2xx  uint64
	status4xx  uint64
	status5xx  uint64
	sumLatMs   uint64
	countLat   uint64
	hist       *hdrhistogram.Histogram
	pathCounts map[string]uint64
	geoCounts  map[string]uint64
}

type extractedBundle struct {
	SourceID   string
	MinuteUnix int64
	Bucket     *minuteBucket
}

func NewAggregator() *Aggregator {
	a := &Aggregator{}
	for i := range a.shards {
		a.shards[i] = &aggShard{
			data: make(map[string]*minuteBucket),
		}
	}
	return a
}

func aggMapKey(source string, minuteUnix int64) string {
	src := source
	if src == "" {
		src = "default"
	}
	return src + aggKeySep + strconv.FormatInt(minuteUnix, 10)
}

func parseAggMapKey(key string) (source string, minuteUnix int64, ok bool) {
	i := strings.LastIndex(key, aggKeySep)
	if i <= 0 {
		return "", 0, false
	}
	mu, err := strconv.ParseInt(key[i+len(aggKeySep):], 10, 64)
	if err != nil {
		return "", 0, false
	}
	return key[:i], mu, true
}

func shardIndexForKey(key string) int {
	h := fnv.New32a()
	_, _ = h.Write([]byte(key))
	return int(h.Sum32() % uint32(shardCount))
}

func newMinuteBucket() *minuteBucket {
	h := hdrhistogram.New(0, maxLatencyMs, histSigFigures)
	return &minuteBucket{
		hist:       h,
		pathCounts: make(map[string]uint64),
		geoCounts:  make(map[string]uint64),
	}
}

// Add 将清洗后的访问记录写入当前分钟桶（高频路径，仅持有单个分片锁）。
func (a *Aggregator) Add(rec CleanedRecord, recvAt time.Time) {
	src := rec.Source
	if src == "" {
		src = "default"
	}
	ts := rec.MSecUnix
	if ts <= 0 {
		ts = float64(recvAt.UnixNano()) / 1e9
	}
	minuteUnix := (int64(ts) / 60) * 60
	key := aggMapKey(src, minuteUnix)
	sh := a.shards[shardIndexForKey(key)]

	sh.mu.Lock()
	b := sh.data[key]
	if b == nil {
		b = newMinuteBucket()
		sh.data[key] = b
	}
	b.observe(rec)
	sh.mu.Unlock()
}

func (b *minuteBucket) observe(rec CleanedRecord) {
	b.requests++

	st := rec.Status
	switch {
	case st >= 200 && st < 400:
		b.status2xx++
	case st >= 400 && st < 500:
		b.status4xx++
	case st >= 500:
		b.status5xx++
	default:
		// 其它状态码不计入 2xx/4xx/5xx 分层
	}

	if rec.RequestTimeS > 0 {
		ms := int64(math.Round(rec.RequestTimeS * 1000))
		if ms < 0 {
			ms = 0
		}
		if ms > maxLatencyMs {
			ms = maxLatencyMs
		}
		b.sumLatMs += uint64(ms)
		b.countLat++
		if b.hist != nil {
			_ = b.hist.RecordValue(ms)
		}
	}

	if uri := strings.TrimSpace(rec.RequestURI); uri != "" {
		if _, exists := b.pathCounts[uri]; !exists && len(b.pathCounts) >= maxPathKeys {
			b.pathCounts["*overflow*"]++
		} else {
			b.pathCounts[uri]++
		}
	}

	cc := strings.TrimSpace(rec.CountryISO)
	if cc == "" {
		cc = "??"
	}
	b.geoCounts[cc]++
}

// ExtractMinute 抓取并移除某一 UTC 分钟桶（所有 source）。
// 仅在对应分片上短时间加锁；其它分片与其它 key 仍可并发写入。
func (a *Aggregator) ExtractMinute(minuteUnix int64) []extractedBundle {
	var out []extractedBundle
	for _, sh := range a.shards {
		sh.mu.Lock()
		var keys []string
		for k := range sh.data {
			_, mu, ok := parseAggMapKey(k)
			if ok && mu == minuteUnix {
				keys = append(keys, k)
			}
		}
		for _, k := range keys {
			b := sh.data[k]
			delete(sh.data, k)
			src, _, _ := parseAggMapKey(k)
			out = append(out, extractedBundle{
				SourceID:   src,
				MinuteUnix: minuteUnix,
				Bucket:     b,
			})
		}
		sh.mu.Unlock()
	}
	return out
}

// flushMinuteEpoch 计算待落库的「闭合」分钟（Unix 秒，UTC），含滞后以避免尾包。
func flushMinuteEpoch(now time.Time, lagMinutes int64) int64 {
	if lagMinutes <= 0 {
		lagMinutes = 2
	}
	cur := now.Unix() / 60
	targetMin := cur - lagMinutes
	return targetMin * 60
}

// AggHumanReadableKey 人类可读 key 形态：等价约定 `[source]_[分钟Unix秒]`（UTC）。
func AggHumanReadableKey(source string, minuteUnix int64) string {
	src := source
	if src == "" {
		src = "default"
	}
	return fmt.Sprintf("[%s]_[%d]", src, minuteUnix)
}

// PeekedMinuteRollup 内存中某一分钟的快照（不落库部分），用于与 PG 合并。
type PeekedMinuteRollup struct {
	BucketStart  time.Time
	SourceID     string
	Requests     uint64
	SumLatencyMs uint64
	CountLatency uint64
	Status2xx    uint64
	Status4xx    uint64
	Status5xx    uint64
	P50Ms        *float64
	P95Ms        *float64
	P99Ms        *float64
	GeoCounts    map[string]uint64
	TopPaths     map[string]uint64
}

func cloneUInt64StringMap(src map[string]uint64) map[string]uint64 {
	if src == nil {
		return nil
	}
	dst := make(map[string]uint64, len(src))
	for k, v := range src {
		dst[k] = v
	}
	return dst
}

// PeekBucketsInRange 只读导出 [startSec, endExclusiveSec) 内的分钟桶（不删除），用于 snapshot 与 PG 合并。
func (a *Aggregator) PeekBucketsInRange(startSec, endExclusiveSec int64, sourceFilter string) []PeekedMinuteRollup {
	var out []PeekedMinuteRollup
	for _, sh := range a.shards {
		sh.mu.Lock()
		for k, b := range sh.data {
			src, mu, ok := parseAggMapKey(k)
			if !ok || mu < startSec || mu >= endExclusiveSec {
				continue
			}
			if sourceFilter != "" && sourceFilter != "all" && src != sourceFilter {
				continue
			}
			out = append(out, materializePeekBucket(src, mu, b))
		}
		sh.mu.Unlock()
	}
	return out
}

func materializePeekBucket(src string, mu int64, b *minuteBucket) PeekedMinuteRollup {
	row := PeekedMinuteRollup{
		BucketStart:  time.Unix(mu, 0).UTC(),
		SourceID:     src,
		Requests:     b.requests,
		SumLatencyMs: b.sumLatMs,
		CountLatency: b.countLat,
		Status2xx:    b.status2xx,
		Status4xx:    b.status4xx,
		Status5xx:    b.status5xx,
		GeoCounts:    cloneUInt64StringMap(b.geoCounts),
		TopPaths:     cloneUInt64StringMap(b.pathCounts),
	}
	if b.hist != nil && b.hist.TotalCount() > 0 {
		p50 := float64(b.hist.ValueAtQuantile(50.0))
		p95 := float64(b.hist.ValueAtQuantile(95.0))
		p99 := float64(b.hist.ValueAtQuantile(99.0))
		row.P50Ms = &p50
		row.P95Ms = &p95
		row.P99Ms = &p99
	}
	return row
}
