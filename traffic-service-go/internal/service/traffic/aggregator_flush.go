package traffic

import (
	"context"
	"encoding/json"
	"log"
	"sort"
	"time"

	"github.com/shark-platform/traffic-service/internal/model"

	"gorm.io/datatypes"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

const (
	defaultFlushLagMinutes = int64(2)
	topPathsPersistLimit   = 50
	persistBatchSize       = 128
)

type pathCountEntry struct {
	Path     string `json:"path"`
	Requests uint64 `json:"requests"`
}

// StartFlushLoop 每分钟触发一次：抽取滞后闭合分钟 → PG Upsert → 丢弃已抽取内存桶。
func (a *Aggregator) StartFlushLoop(ctx context.Context, db *gorm.DB, lagMinutes int64) {
	if lagMinutes <= 0 {
		lagMinutes = defaultFlushLagMinutes
	}
	go func() {
		ticker := time.NewTicker(time.Minute)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case tm := <-ticker.C:
				if db == nil {
					continue
				}
				mu := flushMinuteEpoch(tm.UTC(), lagMinutes)
				if mu <= 0 {
					continue
				}
				bundles := a.ExtractMinute(mu)
				if len(bundles) == 0 {
					continue
				}
				if err := persistMinuteRollups(db, bundles); err != nil {
					log.Printf("traffic aggregator flush minute=%d: %v", mu, err)
				}
			}
		}
	}()
}

func persistMinuteRollups(db *gorm.DB, bundles []extractedBundle) error {
	incoming := make([]model.TrafficMinuteRollup, 0, len(bundles))
	for _, eb := range bundles {
		if eb.Bucket == nil {
			continue
		}
		row := minuteBucketToModel(eb.SourceID, eb.MinuteUnix, eb.Bucket)
		incoming = append(incoming, row)
	}
	if len(incoming) == 0 {
		return nil
	}

	ts := incoming[0].BucketStart
	sourceIDs := make([]string, 0, len(incoming))
	seen := map[string]struct{}{}
	for _, r := range incoming {
		if _, ok := seen[r.SourceID]; ok {
			continue
		}
		seen[r.SourceID] = struct{}{}
		sourceIDs = append(sourceIDs, r.SourceID)
	}

	var existing []model.TrafficMinuteRollup
	if err := db.Where("bucket_start = ? AND source_id IN ?", ts, sourceIDs).
		Find(&existing).Error; err != nil {
		return err
	}

	bySrc := make(map[string]model.TrafficMinuteRollup, len(existing))
	for _, ex := range existing {
		bySrc[ex.SourceID] = ex
	}

	merged := make([]model.TrafficMinuteRollup, 0, len(incoming))
	for _, inc := range incoming {
		if old, ok := bySrc[inc.SourceID]; ok {
			merged = append(merged, mergeTrafficMinuteRollup(&old, &inc))
		} else {
			merged = append(merged, inc)
		}
	}

	for i := range merged {
		merged[i].ID = 0
	}

	return db.Clauses(clause.OnConflict{
		Columns: []clause.Column{{Name: "bucket_start"}, {Name: "source_id"}},
		DoUpdates: clause.AssignmentColumns([]string{
			"requests",
			"sum_latency_ms",
			"count_latency",
			"status_2xx",
			"status_4xx",
			"status_5xx",
			"p50_ms",
			"p95_ms",
			"p99_ms",
			"geo_counts",
			"top_paths",
		}),
	}).CreateInBatches(merged, persistBatchSize).Error
}

func minuteBucketToModel(sourceID string, minuteUnix int64, b *minuteBucket) model.TrafficMinuteRollup {
	row := model.TrafficMinuteRollup{
		BucketStart:  time.Unix(minuteUnix, 0).UTC(),
		SourceID:     sourceID,
		Requests:     uintClamp(b.requests),
		SumLatencyMs: b.sumLatMs,
		CountLatency: uintClamp(b.countLat),
		Status2xx:    uintClamp(b.status2xx),
		Status4xx:    uintClamp(b.status4xx),
		Status5xx:    uintClamp(b.status5xx),
	}

	if b.hist != nil && b.hist.TotalCount() > 0 {
		p50 := float64(b.hist.ValueAtQuantile(50.0))
		p95 := float64(b.hist.ValueAtQuantile(95.0))
		p99 := float64(b.hist.ValueAtQuantile(99.0))
		row.P50Ms = &p50
		row.P95Ms = &p95
		row.P99Ms = &p99
	}

	if raw, err := json.Marshal(b.geoCounts); err == nil {
		row.GeoCounts = datatypes.JSON(raw)
	}
	if raw, err := json.Marshal(topPathEntries(b.pathCounts, topPathsPersistLimit)); err == nil {
		row.TopPaths = datatypes.JSON(raw)
	}

	return row
}

func topPathEntries(m map[string]uint64, limit int) []pathCountEntry {
	if len(m) == 0 {
		return nil
	}
	type kv struct {
		k string
		v uint64
	}
	list := make([]kv, 0, len(m))
	for k, v := range m {
		list = append(list, kv{k: k, v: v})
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].v == list[j].v {
			return list[i].k < list[j].k
		}
		return list[i].v > list[j].v
	})
	if len(list) > limit {
		list = list[:limit]
	}
	out := make([]pathCountEntry, 0, len(list))
	for _, e := range list {
		out = append(out, pathCountEntry{Path: e.k, Requests: e.v})
	}
	return out
}

func mergeTrafficMinuteRollup(old *model.TrafficMinuteRollup, inc *model.TrafficMinuteRollup) model.TrafficMinuteRollup {
	out := model.TrafficMinuteRollup{
		BucketStart:  inc.BucketStart,
		SourceID:     inc.SourceID,
		Requests:     old.Requests + inc.Requests,
		SumLatencyMs: old.SumLatencyMs + inc.SumLatencyMs,
		CountLatency: old.CountLatency + inc.CountLatency,
		Status2xx:    old.Status2xx + inc.Status2xx,
		Status4xx:    old.Status4xx + inc.Status4xx,
		Status5xx:    old.Status5xx + inc.Status5xx,
	}

	out.P50Ms = mergeWeightedLatency(old.CountLatency, old.P50Ms, inc.CountLatency, inc.P50Ms)
	out.P95Ms = mergeWeightedLatency(old.CountLatency, old.P95Ms, inc.CountLatency, inc.P95Ms)
	out.P99Ms = mergeWeightedLatency(old.CountLatency, old.P99Ms, inc.CountLatency, inc.P99Ms)

	out.GeoCounts = mergeGeoCountsJSON(old.GeoCounts, inc.GeoCounts)
	out.TopPaths = mergeTopPathsJSON(old.TopPaths, inc.TopPaths)

	return out
}

func mergeWeightedLatency(oldCount uint, oldP *float64, incCount uint, incP *float64) *float64 {
	tc := oldCount + incCount
	if tc == 0 {
		return nil
	}
	if incCount == 0 {
		return cloneFloatPtr(oldP)
	}
	if oldCount == 0 {
		return cloneFloatPtr(incP)
	}
	ov, iv := 0.0, 0.0
	if oldP != nil {
		ov = *oldP
	}
	if incP != nil {
		iv = *incP
	}
	v := (ov*float64(oldCount) + iv*float64(incCount)) / float64(tc)
	return &v
}

func cloneFloatPtr(p *float64) *float64 {
	if p == nil {
		return nil
	}
	v := *p
	return &v
}

func mergeGeoCountsJSON(a, b datatypes.JSON) datatypes.JSON {
	ma := decodeGeoMap(a)
	mb := decodeGeoMap(b)
	for k, v := range mb {
		ma[k] += v
	}
	raw, err := json.Marshal(ma)
	if err != nil {
		return a
	}
	return datatypes.JSON(raw)
}

func decodeGeoMap(j datatypes.JSON) map[string]uint64 {
	out := make(map[string]uint64)
	if len(j) == 0 {
		return out
	}
	_ = json.Unmarshal(j, &out)
	return out
}

func mergeTopPathsJSON(oldJ, incJ datatypes.JSON) datatypes.JSON {
	combined := make(map[string]uint64)
	addTopPathsSlice(combined, oldJ)
	addTopPathsSlice(combined, incJ)
	raw, err := json.Marshal(topPathEntries(combined, topPathsPersistLimit))
	if err != nil {
		return incJ
	}
	return datatypes.JSON(raw)
}

func addTopPathsSlice(dst map[string]uint64, j datatypes.JSON) {
	if len(j) == 0 {
		return
	}
	var entries []pathCountEntry
	if json.Unmarshal(j, &entries) != nil {
		return
	}
	for _, e := range entries {
		dst[e.Path] += e.Requests
	}
}

func uintClamp(v uint64) uint {
	maxVal := ^uint(0)
	if v >= uint64(maxVal) {
		return maxVal
	}
	return uint(v)
}
