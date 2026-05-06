package traffic

import (
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/shark-platform/traffic-service/internal/model"

	"gorm.io/datatypes"
	"gorm.io/gorm"
)

const (
	maxCustomSpanRollup    = 90 * 24 * time.Hour
	fullDataMaxSpanProtect = 48 * time.Hour
	timeseriesRollupBS     = 60 // 对齐 rollup_query._timeseries_from_merged
)

var presetRangeDur = map[string]time.Duration{
	"10m": 10 * time.Minute,
	"1h":  time.Hour,
	"6h":  6 * time.Hour,
	"24h": 24 * time.Hour,
	"7d":  7 * 24 * time.Hour,
	"30d": 30 * 24 * time.Hour,
}

// SnapshotHTTPError 可由 Handler 映射为 4xx。
type SnapshotHTTPError struct {
	Code int
	Msg  string
}

func (e *SnapshotHTTPError) Error() string { return e.Msg }

// SnapshotEnv snapshot 所需的运行时开关（对齐 Django cfg + inspection 片段）。
type SnapshotEnv struct {
	Blackbox            BlackboxConfig
	AccessLogMode       string
	LogConfigured       bool
	RollupIngestEnabled bool
}

type weightedP struct {
	p float64
	n uint64
}

type rollupContrib struct {
	BucketStart  time.Time
	SourceID     string
	Requests     uint64
	SumLatencyMs uint64
	CountLatency uint64
	S2           uint64
	S4           uint64
	S5           uint64
	p50w         []weightedP
	p95w         []weightedP
	p99w         []weightedP
	geo          map[string]uint64
	paths        map[string]uint64
}

type mergedMinutePy struct {
	BucketStart  time.Time
	Requests     uint64
	SumLatencyMs uint64
	CountLatency uint64
	S2           uint64
	S4           uint64
	S5           uint64
	p50w         []weightedP
	p95w         []weightedP
	p99w         []weightedP
	geo          map[string]uint64
	paths        map[string]uint64
}

func parseSnapshotWindow(q SnapshotQuery, now time.Time) (start, end time.Time, rangeLabel string, err error) {
	startS, endS := strings.TrimSpace(q.StartISO), strings.TrimSpace(q.EndISO)
	hasStart := startS != ""
	hasEnd := endS != ""
	if hasStart != hasEnd {
		return time.Time{}, time.Time{}, "", fmt.Errorf("start and end must both be set for custom range")
	}
	if hasStart && hasEnd {
		start, err = parseRFC3339Flexible(startS)
		if err != nil {
			return time.Time{}, time.Time{}, "", fmt.Errorf("bad start: %w", err)
		}
		end, err = parseRFC3339Flexible(endS)
		if err != nil {
			return time.Time{}, time.Time{}, "", fmt.Errorf("bad end: %w", err)
		}
		start = start.UTC()
		end = end.UTC()
		if !end.After(start) {
			return time.Time{}, time.Time{}, "", fmt.Errorf("end must be after start")
		}
		if end.Sub(start) > maxCustomSpanRollup {
			return time.Time{}, time.Time{}, "", fmt.Errorf("time span exceeds 90 days")
		}
		capEnd := now.UTC().Add(5 * time.Minute)
		if end.After(capEnd) {
			end = capEnd
		}
		spanSec := int(end.Sub(start).Seconds())
		return start, end, fmt.Sprintf("custom:%ds", spanSec), nil
	}

	rk := strings.TrimSpace(q.Range)
	if rk == "" {
		rk = "24h"
	}
	dur, ok := presetRangeDur[rk]
	if !ok {
		dur = 24 * time.Hour
		rk = "24h"
	}
	end = now.UTC()
	start = end.Add(-dur)
	return start, end, rk, nil
}

func parseRFC3339Flexible(s string) (time.Time, error) {
	if t, err := time.Parse(time.RFC3339Nano, s); err == nil {
		return t.UTC(), nil
	}
	if t, err := time.Parse(time.RFC3339, s); err == nil {
		return t.UTC(), nil
	}
	layouts := []string{
		"2006-01-02T15:04:05",
		"2006-01-02 15:04:05",
	}
	var lastErr error
	for _, l := range layouts {
		t, err := time.ParseInLocation(l, s, time.UTC)
		if err != nil {
			lastErr = err
			continue
		}
		return t.UTC(), nil
	}
	return time.Time{}, fmt.Errorf("parse time: %v", lastErr)
}

func compositeKey(bt time.Time, sourceID string) string {
	return fmt.Sprintf("%d|%s", bt.UTC().Unix(), sourceID)
}

func contribFromModel(m model.TrafficMinuteRollup) rollupContrib {
	c := rollupContrib{
		BucketStart:  m.BucketStart.UTC(),
		SourceID:     m.SourceID,
		Requests:     uint64(m.Requests),
		SumLatencyMs: m.SumLatencyMs,
		CountLatency: uint64(m.CountLatency),
		S2:           uint64(m.Status2xx),
		S4:           uint64(m.Status4xx),
		S5:           uint64(m.Status5xx),
		geo:          decodeGeoMapJSON(m.GeoCounts),
		paths:        topPathsJSONToMap(m.TopPaths),
	}
	n := uint64(m.Requests)
	if n > 0 {
		if m.P50Ms != nil {
			c.p50w = append(c.p50w, weightedP{*m.P50Ms, n})
		}
		if m.P95Ms != nil {
			c.p95w = append(c.p95w, weightedP{*m.P95Ms, n})
		}
		if m.P99Ms != nil {
			c.p99w = append(c.p99w, weightedP{*m.P99Ms, n})
		}
	}
	return c
}

func contribFromPeek(p PeekedMinuteRollup) rollupContrib {
	c := rollupContrib{
		BucketStart:  p.BucketStart.UTC(),
		SourceID:     p.SourceID,
		Requests:     p.Requests,
		SumLatencyMs: p.SumLatencyMs,
		CountLatency: p.CountLatency,
		S2:           p.Status2xx,
		S4:           p.Status4xx,
		S5:           p.Status5xx,
		geo:          cloneUInt64StringMap(p.GeoCounts),
		paths:        cloneUInt64StringMap(p.TopPaths),
	}
	n := p.Requests
	if n > 0 {
		if p.P50Ms != nil {
			c.p50w = append(c.p50w, weightedP{*p.P50Ms, n})
		}
		if p.P95Ms != nil {
			c.p95w = append(c.p95w, weightedP{*p.P95Ms, n})
		}
		if p.P99Ms != nil {
			c.p99w = append(c.p99w, weightedP{*p.P99Ms, n})
		}
	}
	return c
}

func decodeGeoMapJSON(j datatypes.JSON) map[string]uint64 {
	out := make(map[string]uint64)
	if len(j) == 0 {
		return out
	}
	_ = json.Unmarshal(j, &out)
	return out
}

func topPathsJSONToMap(j datatypes.JSON) map[string]uint64 {
	out := make(map[string]uint64)
	if len(j) == 0 {
		return out
	}
	var entries []struct {
		Path     string `json:"path"`
		Requests uint64 `json:"requests"`
	}
	if json.Unmarshal(j, &entries) != nil {
		return out
	}
	for _, e := range entries {
		out[e.Path] += e.Requests
	}
	return out
}

func mergeIntoComposite(dst *rollupContrib, src rollupContrib) {
	dst.Requests += src.Requests
	dst.SumLatencyMs += src.SumLatencyMs
	dst.CountLatency += src.CountLatency
	dst.S2 += src.S2
	dst.S4 += src.S4
	dst.S5 += src.S5
	dst.p50w = append(dst.p50w, src.p50w...)
	dst.p95w = append(dst.p95w, src.p95w...)
	dst.p99w = append(dst.p99w, src.p99w...)
	if dst.geo == nil {
		dst.geo = make(map[string]uint64)
	}
	for k, v := range src.geo {
		dst.geo[k] += v
	}
	if dst.paths == nil {
		dst.paths = make(map[string]uint64)
	}
	for k, v := range src.paths {
		dst.paths[k] += v
	}
}

func mergeByMinutePython(contribs []rollupContrib) []mergedMinutePy {
	by := make(map[int64]*mergedMinutePy)
	for _, r := range contribs {
		ts := r.BucketStart.Unix()
		b := by[ts]
		if b == nil {
			b = &mergedMinutePy{
				BucketStart: time.Unix(ts, 0).UTC(),
				geo:         make(map[string]uint64),
				paths:       make(map[string]uint64),
			}
			by[ts] = b
		}
		b.Requests += r.Requests
		b.SumLatencyMs += r.SumLatencyMs
		b.CountLatency += r.CountLatency
		b.S2 += r.S2
		b.S4 += r.S4
		b.S5 += r.S5
		b.p50w = append(b.p50w, r.p50w...)
		b.p95w = append(b.p95w, r.p95w...)
		b.p99w = append(b.p99w, r.p99w...)
		for k, v := range r.geo {
			b.geo[k] += v
		}
		for k, v := range r.paths {
			b.paths[k] += v
		}
	}
	keys := make([]int64, 0, len(by))
	for k := range by {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool { return keys[i] < keys[j] })
	out := make([]mergedMinutePy, 0, len(keys))
	for _, k := range keys {
		out = append(out, *by[k])
	}
	return out
}

func wavgPairs(pairs []weightedP) float64 {
	var tot uint64
	var sum float64
	for _, p := range pairs {
		tot += p.n
		sum += p.p * float64(p.n)
	}
	if tot == 0 {
		return 0
	}
	return sum / float64(tot)
}

func roundPy(v float64, prec int) float64 {
	p := math.Pow10(prec)
	return math.Round(v*p) / p
}

func emptyTimeseriesRollup(startSec, endSec float64, rangeLabel string) map[string]any {
	return emptyTimeseriesRollupBucket(startSec, endSec, rangeLabel, timeseriesRollupBS)
}

func emptyTimeseriesRollupBucket(startSec, endSec float64, rangeLabel string, bucketSec int) map[string]any {
	bs := bucketSec
	if bs <= 0 {
		bs = timeseriesRollupBS
	}
	var times []int64
	t := int64(startSec) / int64(bs) * int64(bs)
	endTs := int64(endSec)
	for t <= endTs {
		times = append(times, t)
		t += int64(bs)
	}
	if len(times) > 200 {
		times = times[len(times)-200:]
	}
	z := make([][]any, len(times))
	for i, x := range times {
		z[i] = []any{float64(x * 1000), 0}
	}
	return map[string]any{
		"bucket_sec": bs,
		"range":      rangeLabel,
		"qps":        z,
		"requests":   z,
		"latency": map[string]any{
			"p50": z,
			"p95": z,
			"p99": z,
		},
		"status_stack": map[string]any{
			"2xx": z,
			"4xx": z,
			"5xx": z,
		},
	}
}

func timeseriesFromMergedPy(merged []mergedMinutePy, rangeLabel string) map[string]any {
	return timeseriesFromMergedPyBucket(merged, rangeLabel, timeseriesRollupBS)
}

func timeseriesFromMergedPyBucket(merged []mergedMinutePy, rangeLabel string, bucketSec int) map[string]any {
	bs := bucketSec
	if bs <= 0 {
		bs = timeseriesRollupBS
	}
	dur := float64(bs)
	qps := make([][]any, 0, len(merged))
	reqs := make([][]any, 0, len(merged))
	p50 := make([][]any, 0, len(merged))
	p95 := make([][]any, 0, len(merged))
	p99 := make([][]any, 0, len(merged))
	s2 := make([][]any, 0, len(merged))
	s4 := make([][]any, 0, len(merged))
	s5 := make([][]any, 0, len(merged))

	for _, b := range merged {
		t := b.BucketStart.Unix()
		ms := float64(t * 1000)
		n := float64(b.Requests)
		qps = append(qps, []any{ms, roundPy(n/dur, 4)})
		reqs = append(reqs, []any{ms, b.Requests})
		v50 := wavgPairs(b.p50w)
		v95 := wavgPairs(b.p95w)
		v99 := wavgPairs(b.p99w)
		p50 = append(p50, []any{ms, roundPy(v50, 3)})
		p95 = append(p95, []any{ms, roundPy(v95, 3)})
		p99 = append(p99, []any{ms, roundPy(v99, 3)})
		s2 = append(s2, []any{ms, roundPy(float64(b.S2)/dur, 4)})
		s4 = append(s4, []any{ms, roundPy(float64(b.S4)/dur, 4)})
		s5 = append(s5, []any{ms, roundPy(float64(b.S5)/dur, 4)})
	}

	return map[string]any{
		"bucket_sec": bs,
		"range":      rangeLabel,
		"qps":        qps,
		"requests":   reqs,
		"latency": map[string]any{
			"p50": p50,
			"p95": p95,
			"p99": p99,
		},
		"status_stack": map[string]any{
			"2xx": s2,
			"4xx": s4,
			"5xx": s5,
		},
	}
}

func timeseriesBucketSecFromMap(ts map[string]any) int {
	if ts == nil {
		return timeseriesRollupBS
	}
	v, ok := ts["bucket_sec"]
	if !ok {
		return timeseriesRollupBS
	}
	switch x := v.(type) {
	case int:
		if x > 0 {
			return x
		}
	case int64:
		if x > 0 {
			return int(x)
		}
	case float64:
		if x > 0 {
			return int(x)
		}
	}
	return timeseriesRollupBS
}

func sumMergedRequestsOverlapping(merged []mergedMinutePy, winStart, winEnd time.Time, bucketDur time.Duration) uint64 {
	winStart = winStart.UTC()
	winEnd = winEnd.UTC()
	var sum uint64
	for _, b := range merged {
		bs := b.BucketStart.UTC()
		be := bs.Add(bucketDur)
		if be.After(winStart) && bs.Before(winEnd) {
			sum += b.Requests
		}
	}
	return sum
}

// qpsFromMergedNearNow 对齐 Django overview_kpis：先按墙钟近 60s；若无重叠（MV 延迟 / 区间末端空桶），再以最新聚合桶为锚取近 60s。
func qpsFromMergedNearNow(merged []mergedMinutePy, now time.Time, bucketSec int) float64 {
	if len(merged) == 0 || bucketSec <= 0 {
		return 0
	}
	bucketDur := time.Duration(bucketSec) * time.Second
	now = now.UTC()
	win := 60 * time.Second
	s := sumMergedRequestsOverlapping(merged, now.Add(-win), now, bucketDur)
	if s == 0 {
		last := merged[len(merged)-1].BucketStart.UTC()
		dataEnd := last.Add(bucketDur)
		s = sumMergedRequestsOverlapping(merged, dataEnd.Add(-win), dataEnd, bucketDur)
	}
	return roundPy(float64(s)/60.0, 4)
}

func overviewFromMergedPy(merged []mergedMinutePy, rangeLabel string, ts map[string]any) map[string]any {
	refreshed := iso8601ZMicro(time.Now().UTC())
	if len(merged) == 0 {
		return map[string]any{
			"range":                    rangeLabel,
			"refreshed_at":             refreshed,
			"total_requests":           0,
			"total_requests_delta_pct": 0.0,
			"qps":                      0.0,
			"latency_avg_ms":           0.0,
			"error_rate_pct":           0.0,
			"availability_pct":         100.0,
			"series":                   map[string]any{"qps": []any{}, "error_rate": []any{}},
			"error_detail":             rollupErrorDetailEmpty(),
		}
	}

	var total uint64
	var s2, s4, s5 uint64
	var sumLat uint64
	var nLat uint64
	for _, b := range merged {
		total += b.Requests
		s2 += b.S2
		s4 += b.S4
		s5 += b.S5
		sumLat += b.SumLatencyMs
		nLat += b.CountLatency
	}
	errc := s4 + s5
	errRate := 0.0
	if total > 0 {
		errRate = float64(errc) / float64(total) * 100.0
	}
	pct4 := 0.0
	pct5 := 0.0
	if total > 0 {
		pct4 = roundPy(float64(s4)/float64(total)*100.0, 3)
		pct5 = roundPy(float64(s5)/float64(total)*100.0, 3)
	}
	avgLat := 0.0
	if nLat > 0 {
		avgLat = float64(sumLat) / float64(nLat)
	}

	recsByBucket := make(map[int64]*mergedMinutePy)
	for i := range merged {
		bk := merged[i].BucketStart.Unix()
		recsByBucket[bk] = &merged[i]
	}

	bucketSec := timeseriesBucketSecFromMap(ts)

	qpsSeries, _ := ts["qps"].([][]any)
	sparkQPS := qpsSeries
	if len(sparkQPS) > 40 {
		sparkQPS = sparkQPS[len(sparkQPS)-40:]
	}

	reqSeries, _ := ts["requests"].([][]any)
	sparkErrFull := make([][]any, 0, len(reqSeries))
	for _, row := range reqSeries {
		if len(row) < 2 {
			continue
		}
		tMs, _ := row[0].(float64)
		nAny := row[1]
		var n float64
		switch v := nAny.(type) {
		case float64:
			n = v
		case uint64:
			n = float64(v)
		case int:
			n = float64(v)
		}
		tSec := int64(tMs) / 1000
		bk := (tSec / int64(bucketSec)) * int64(bucketSec)
		ref := recsByBucket[bk]
		if ref == nil || n == 0 {
			sparkErrFull = append(sparkErrFull, []any{tMs, 0.0})
			continue
		}
		e := float64(ref.S4 + ref.S5)
		sparkErrFull = append(sparkErrFull, []any{tMs, roundPy(e/n*100.0, 3)})
	}
	sparkErr := sparkErrFull
	if len(sparkQPS) > 0 && len(sparkErr) >= len(sparkQPS) {
		sparkErr = sparkErr[len(sparkErr)-len(sparkQPS):]
	}

	qpsNow := qpsFromMergedNearNow(merged, time.Now(), bucketSec)

	return map[string]any{
		"range":                    rangeLabel,
		"refreshed_at":             refreshed,
		"total_requests":           total,
		"total_requests_delta_pct": 0.0,
		"qps":                      qpsNow,
		"latency_avg_ms":           roundPy(avgLat, 2),
		"error_rate_pct":           roundPy(errRate, 3),
		"availability_pct":         roundPy(100.0-math.Min(errRate, 100.0), 3),
		"series": map[string]any{
			"qps":        sparkQPS,
			"error_rate": sparkErr,
		},
		"error_detail": map[string]any{
			"n_2xx":                      s2,
			"n_4xx":                      s4,
			"n_5xx":                      s5,
			"n_err":                      errc,
			"pct_4xx":                    pct4,
			"pct_5xx":                    pct5,
			"path_code_breakdown":        []any{},
			"rollup":                     true,
			"rollup_no_path_errors":      true,
			"rollup_no_status_breakdown": true,
		},
	}
}

func rollupErrorDetailEmpty() map[string]any {
	return map[string]any{
		"n_2xx":                      0,
		"n_4xx":                      0,
		"n_5xx":                      0,
		"n_err":                      0,
		"pct_4xx":                    0.0,
		"pct_5xx":                    0.0,
		"path_code_breakdown":        []any{},
		"rollup":                     true,
		"rollup_no_path_errors":      true,
		"rollup_no_status_breakdown": true,
	}
}

func geoFromMergedPy(merged []mergedMinutePy, rangeLabel string) map[string]any {
	counts := make(map[string]uint64)
	for _, b := range merged {
		for code, n := range b.geo {
			cc := code
			if cc == "" {
				cc = "??"
			}
			counts[cc] += n
		}
	}
	return rollupGeoFromCounts(counts, rangeLabel)
}

// rollupGeoFromCounts 由聚合后的国家计数生成 geo 契约（ClickHouse 全区间 geo 查询可直接喂 counts）。
func rollupGeoFromCounts(counts map[string]uint64, rangeLabel string) map[string]any {
	type kv struct {
		code string
		n    uint64
	}
	list := make([]kv, 0, len(counts))
	for c, n := range counts {
		list = append(list, kv{c, n})
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].n == list[j].n {
			return list[i].code < list[j].code
		}
		return list[i].n > list[j].n
	})
	if len(list) > 200 {
		list = list[:200]
	}
	items := make([]map[string]any, 0, len(list))
	for _, e := range list {
		lat, lng := 0.0, 0.0
		if e.code != "LAN" && e.code != "??" {
			if la, ln, ok := centroidForCountry(e.code); ok {
				lat, lng = la, ln
			}
		}
		items = append(items, map[string]any{
			"code":     e.code,
			"name":     e.code,
			"lat":      lat,
			"lng":      lng,
			"requests": e.n,
		})
	}
	return map[string]any{
		"range":       rangeLabel,
		"granularity": "country",
		"items":       items,
	}
}

func topPathsFromMergedPy(merged []mergedMinutePy, rangeLabel string, limit int) map[string]any {
	acc := make(map[string]uint64)
	for _, b := range merged {
		for p, n := range b.paths {
			acc[p] += n
		}
	}
	return rollupTopPathsFromCounts(acc, rangeLabel, limit)
}

// rollupTopPathsFromCounts 由路径计数生成 top_paths 契约。
func rollupTopPathsFromCounts(acc map[string]uint64, rangeLabel string, limit int) map[string]any {
	var tot uint64
	for _, n := range acc {
		tot += n
	}
	if tot == 0 {
		tot = 1
	}
	type kv struct {
		p string
		n uint64
	}
	list := make([]kv, 0, len(acc))
	for p, n := range acc {
		list = append(list, kv{p, n})
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].n == list[j].n {
			return list[i].p < list[j].p
		}
		return list[i].n > list[j].n
	})
	if len(list) > limit {
		list = list[:limit]
	}
	rows := make([]map[string]any, 0, len(list))
	for _, e := range list {
		rows = append(rows, map[string]any{
			"path":       e.p,
			"requests":   e.n,
			"p95_ms":     0.0,
			"errors_5xx": 0,
			"share_pct":  roundPy(float64(e.n)/float64(tot)*100.0, 2),
		})
	}
	return map[string]any{
		"type":  "paths",
		"range": rangeLabel,
		"items": rows,
	}
}

func topStatusFromMergedPy(merged []mergedMinutePy, rangeLabel string) map[string]any {
	var s2, s4, s5 uint64
	for _, b := range merged {
		s2 += b.S2
		s4 += b.S4
		s5 += b.S5
	}
	items := []map[string]any{
		{"name": "2xx", "value": s2},
		{"name": "4xx", "value": s4},
		{"name": "5xx", "value": s5},
	}
	return map[string]any{
		"type":  "status",
		"range": rangeLabel,
		"items": items,
	}
}

// BuildRollupSnapshot 对齐 Django build_rollups_snapshot（PG + 内存 Peek），不含 ClickHouse。
func BuildRollupSnapshot(db *gorm.DB, agg *Aggregator, env SnapshotEnv, q SnapshotQuery) (map[string]any, error) {
	now := time.Now().UTC()
	start, end, rangeLabel, err := parseSnapshotWindow(q, now)
	if err != nil {
		return nil, &SnapshotHTTPError{Code: http.StatusBadRequest, Msg: err.Error()}
	}
	if q.FullData && end.Sub(start) > fullDataMaxSpanProtect {
		return nil, &SnapshotHTTPError{
			Code: http.StatusBadRequest,
			Msg:  "full_data with time range too large; reduce span or omit full_data",
		}
	}

	source := strings.TrimSpace(q.Source)
	if source == "" {
		source = "all"
	}

	var pgRows []model.TrafficMinuteRollup
	if db != nil {
		tx := db.Where("bucket_start >= ? AND bucket_start < ?", start, end).
			Order("bucket_start ASC").Order("source_id ASC")
		if source != "" && source != "all" {
			tx = tx.Where("source_id = ?", source)
		}
		if err := tx.Find(&pgRows).Error; err != nil {
			return nil, err
		}
	}

	var peek []PeekedMinuteRollup
	if agg != nil {
		peek = agg.PeekBucketsInRange(start.Unix(), end.Unix(), source)
	}

	comp := make(map[string]*rollupContrib)
	for _, m := range pgRows {
		cm := contribFromModel(m)
		k := compositeKey(cm.BucketStart, cm.SourceID)
		if ex, ok := comp[k]; ok {
			mergeIntoComposite(ex, cm)
		} else {
			x := cm
			comp[k] = &x
		}
	}
	for _, p := range peek {
		cm := contribFromPeek(p)
		k := compositeKey(cm.BucketStart, cm.SourceID)
		if ex, ok := comp[k]; ok {
			mergeIntoComposite(ex, cm)
		} else {
			x := cm
			comp[k] = &x
		}
	}

	contribs := make([]rollupContrib, 0, len(comp))
	for _, p := range comp {
		contribs = append(contribs, *p)
	}
	merged := mergeByMinutePython(contribs)

	var ts map[string]any
	var ov map[string]any
	if len(merged) == 0 {
		ts = emptyTimeseriesRollup(float64(start.Unix()), float64(end.Unix()), rangeLabel)
		ov = overviewFromMergedPy(nil, rangeLabel, ts)
	} else {
		ts = timeseriesFromMergedPy(merged, rangeLabel)
		ov = overviewFromMergedPy(merged, rangeLabel, ts)
	}

	bb := fetchBlackboxSummary(env.Blackbox)
	ov["blackbox"] = bb
	if ap, ok := bb["availability_pct"]; ok && ap != nil {
		ov["availability_pct"] = ap
	}
	ov["log_configured"] = env.LogConfigured
	ov["access_log_mode"] = env.AccessLogMode
	if ov["access_log_mode"] == "" {
		ov["access_log_mode"] = "redis"
	}
	ov["full_data"] = q.FullData
	ov["minute_rollup"] = true
	ov["rollup"] = true
	ov["rollup_rows"] = len(pgRows) + len(peek)
	ov["rollup_ingest_enabled"] = env.RollupIngestEnabled

	out := map[string]any{
		"overview":   ov,
		"timeseries": ts,
		"geo":        geoFromMergedPy(merged, rangeLabel),
		"top_paths":  topPathsFromMergedPy(merged, rangeLabel, 10),
		"top_slow":   map[string]any{"type": "slow", "range": rangeLabel, "items": []any{}},
		"top_ip":     map[string]any{"type": "ip", "range": rangeLabel, "items": []any{}},
		"top_status": topStatusFromMergedPy(merged, rangeLabel),
	}

	if len(merged) == 0 {
		ovRoll := out["overview"].(map[string]any)
		ovRoll["rollup_empty"] = true
		if env.RollupIngestEnabled {
			ovRoll["rollup_empty_hint"] = "所选区间内分钟聚合表无行或尚未 ingest；请核对 ingest、Flush 与 source。"
		} else {
			ovRoll["rollup_empty_hint"] = "所选区间内分钟聚合无数据；请确认 TRAFFIC_ROLLUP_ENABLED 与 Flush。"
		}
	}

	return out, nil
}
