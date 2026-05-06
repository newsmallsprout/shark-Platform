package traffic

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"
	"unicode"

	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
	"golang.org/x/sync/errgroup"
)

const (
	chSnapshotTimeoutDefault = 25 * time.Second
	chSettingsTail           = `SETTINGS max_execution_time = 10, optimize_aggregation_in_order = 1`
)

// chRollupBucketPlan 自适应时间桶：降低返回点数与聚合开销（分钟 rollup 源数据再二次聚合）。
func chRollupBucketPlan(span time.Duration) (bucketSec int, intervalSQL string) {
	switch {
	case span <= 3*time.Hour:
		return 60, "INTERVAL 1 MINUTE"
	case span <= 48*time.Hour:
		return 300, "INTERVAL 5 MINUTE"
	case span <= 21*24*time.Hour:
		return 900, "INTERVAL 15 MINUTE"
	default:
		return 3600, "INTERVAL 1 HOUR"
	}
}

func validateCHIdentifier(ident string) error {
	ident = strings.TrimSpace(ident)
	if ident == "" {
		return fmt.Errorf("empty identifier")
	}
	for i, r := range ident {
		if i == 0 {
			if !(unicode.IsLetter(r) || r == '_') {
				return fmt.Errorf("invalid identifier %q", ident)
			}
			continue
		}
		if !(unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_') {
			return fmt.Errorf("invalid identifier %q", ident)
		}
	}
	return nil
}

func escapeCHSingleQuoted(s string) string {
	s = strings.ReplaceAll(s, `\`, `\\`)
	s = strings.ReplaceAll(s, "'", "\\'")
	return s
}

func sourceWhereSQL(source string) string {
	s := strings.TrimSpace(source)
	if s == "" || strings.EqualFold(s, "all") {
		return ""
	}
	return " AND source = '" + escapeCHSingleQuoted(s) + "'"
}

func scanGeoArrays(keysRaw interface{}, valsRaw interface{}) map[string]uint64 {
	out := make(map[string]uint64)
	var keys []string
	switch k := keysRaw.(type) {
	case []string:
		keys = k
	case [][]uint8:
		for _, b := range k {
			keys = append(keys, strings.TrimSpace(string(b)))
		}
	default:
		return out
	}
	var vals []uint64
	switch v := valsRaw.(type) {
	case []uint64:
		vals = v
	case []uint32:
		for _, x := range v {
			vals = append(vals, uint64(x))
		}
	case []int64:
		for _, x := range v {
			if x >= 0 {
				vals = append(vals, uint64(x))
			}
		}
	default:
		return out
	}
	n := len(keys)
	if len(vals) < n {
		n = len(vals)
	}
	for i := 0; i < n; i++ {
		cc := strings.TrimSpace(keys[i])
		if cc == "" {
			cc = "??"
		}
		out[cc] += vals[i]
	}
	return out
}

func parseTopPathsJSON(s string) map[string]uint64 {
	out := make(map[string]uint64)
	s = strings.TrimSpace(s)
	if s == "" || s == "[]" || s == "null" {
		return out
	}
	var raw [][]any
	if err := json.Unmarshal([]byte(s), &raw); err != nil {
		return out
	}
	for _, pair := range raw {
		if len(pair) < 2 {
			continue
		}
		ps, ok := pair[0].(string)
		if !ok {
			continue
		}
		var n uint64
		switch v := pair[1].(type) {
		case float64:
			n = uint64(v)
		case json.Number:
			x, _ := v.Int64()
			if x >= 0 {
				n = uint64(x)
			}
		default:
			continue
		}
		out[ps] += n
	}
	return out
}

// BuildClickHouseRollupSnapshot 从 AggregatingMergeTree 分钟聚合表读取大屏（不使用 PostgreSQL）。
func BuildClickHouseRollupSnapshot(
	ctx context.Context,
	conn driver.Conn,
	env SnapshotEnv,
	q SnapshotQuery,
	database, rollupTable string,
	queryTimeout time.Duration,
) (map[string]any, error) {
	if err := validateCHIdentifier(database); err != nil {
		return nil, err
	}
	if err := validateCHIdentifier(rollupTable); err != nil {
		return nil, err
	}

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

	bucketSec, intervalLit := chRollupBucketPlan(end.Sub(start))
	startU := start.Unix()
	endU := end.Unix()
	srcWhere := sourceWhereSQL(source)
	fqn := fmt.Sprintf("`%s`.`%s`", database, rollupTable)

	tsSQL := fmt.Sprintf(`
SELECT
  bucket,
  requests,
  sum_latency_ms,
  count_latency,
  s2,
  s4,
  s5,
  if(isNaN(arrayElement(lat_triple, 1)), 0, arrayElement(lat_triple, 1)) AS p50_ms,
  if(isNaN(arrayElement(lat_triple, 2)), 0, arrayElement(lat_triple, 2)) AS p95_ms,
  if(isNaN(arrayElement(lat_triple, 3)), 0, arrayElement(lat_triple, 3)) AS p99_ms
FROM (
  SELECT
    toStartOfInterval(minute, %[1]s) AS bucket,
    sumMerge(requests) AS requests,
    sumMerge(sum_latency_ms) AS sum_latency_ms,
    sumMerge(count_latency) AS count_latency,
    sumMerge(status_2xx) AS s2,
    sumMerge(status_4xx) AS s4,
    sumMerge(status_5xx) AS s5,
    quantilesTDigestMerge(0.5, 0.95, 0.99)(latency_digest) AS lat_triple
  FROM %[2]s
  WHERE minute >= toDateTime(%[3]d) AND minute < toDateTime(%[4]d)%[5]s
  GROUP BY toStartOfInterval(minute, %[1]s)
)
ORDER BY bucket
%[6]s`, intervalLit, fqn, startU, endU, srcWhere, chSettingsTail)

	geoSQL := fmt.Sprintf(`
SELECT
  tupleElement(sumMapMerge(geo_counts), 1) AS ks,
  tupleElement(sumMapMerge(geo_counts), 2) AS vs
FROM %[1]s
WHERE minute >= toDateTime(%[2]d) AND minute < toDateTime(%[3]d)%[4]s
%[5]s`, fqn, startU, endU, srcWhere, chSettingsTail)

	pathsSQL := fmt.Sprintf(`
SELECT toJSONString(topKWeightedMerge(100)(top_paths)) AS j
FROM %[1]s
WHERE minute >= toDateTime(%[2]d) AND minute < toDateTime(%[3]d)%[4]s
%[5]s`, fqn, startU, endU, srcWhere, chSettingsTail)

	if queryTimeout <= 0 {
		queryTimeout = chSnapshotTimeoutDefault
	}
	qctx, cancel := context.WithTimeout(ctx, queryTimeout)
	defer cancel()

	var merged []mergedMinutePy
	var geoCounts map[string]uint64
	var pathCounts map[string]uint64

	g, gctx := errgroup.WithContext(qctx)

	g.Go(func() error {
		rows, err := conn.Query(gctx, tsSQL)
		if err != nil {
			return fmt.Errorf("clickhouse timeseries: %w", err)
		}
		defer rows.Close()
		var out []mergedMinutePy
		for rows.Next() {
			var bucket time.Time
			var req, sumLat, cntLat, s2, s4, s5 uint64
			var p50, p95, p99 float64
			if err := rows.Scan(&bucket, &req, &sumLat, &cntLat, &s2, &s4, &s5, &p50, &p95, &p99); err != nil {
				return fmt.Errorf("scan timeseries row: %w", err)
			}
			m := mergedMinutePy{
				BucketStart:  bucket.UTC().Truncate(time.Second),
				Requests:     req,
				SumLatencyMs: sumLat,
				CountLatency: cntLat,
				S2:           s2,
				S4:           s4,
				S5:           s5,
				geo:          make(map[string]uint64),
				paths:        make(map[string]uint64),
			}
			if req > 0 {
				m.p50w = []weightedP{{p50, req}}
				m.p95w = []weightedP{{p95, req}}
				m.p99w = []weightedP{{p99, req}}
			}
			out = append(out, m)
		}
		if err := rows.Err(); err != nil {
			return err
		}
		merged = out
		return nil
	})

	g.Go(func() error {
		row := conn.QueryRow(gctx, geoSQL)
		var ks, vs any
		if err := row.Scan(&ks, &vs); err != nil {
			return fmt.Errorf("clickhouse geo: %w", err)
		}
		geoCounts = scanGeoArrays(ks, vs)
		return nil
	})

	g.Go(func() error {
		row := conn.QueryRow(gctx, pathsSQL)
		var js string
		if err := row.Scan(&js); err != nil {
			return fmt.Errorf("clickhouse top_paths: %w", err)
		}
		pathCounts = parseTopPathsJSON(js)
		return nil
	})

	if err := g.Wait(); err != nil {
		if qctx.Err() == context.DeadlineExceeded {
			return nil, &SnapshotHTTPError{Code: http.StatusGatewayTimeout, Msg: "clickhouse snapshot timeout"}
		}
		log.Printf("traffic clickhouse snapshot: %v", err)
		return nil, &SnapshotHTTPError{Code: http.StatusBadGateway, Msg: "clickhouse snapshot query failed"}
	}

	var ts map[string]any
	var ov map[string]any
	if len(merged) == 0 {
		ts = emptyTimeseriesRollupBucket(float64(startU), float64(endU), rangeLabel, bucketSec)
		ov = overviewFromMergedPy(nil, rangeLabel, ts)
	} else {
		ts = timeseriesFromMergedPyBucket(merged, rangeLabel, bucketSec)
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
	ov["rollup_rows"] = len(merged)
	ov["rollup_ingest_enabled"] = env.RollupIngestEnabled
	ov["rollup_source"] = "clickhouse"

	out := map[string]any{
		"overview":   ov,
		"timeseries": ts,
		"geo":        rollupGeoFromCounts(geoCounts, rangeLabel),
		"top_paths":  rollupTopPathsFromCounts(pathCounts, rangeLabel, 10),
		"top_slow":   map[string]any{"type": "slow", "range": rangeLabel, "items": []any{}},
		"top_ip":     map[string]any{"type": "ip", "range": rangeLabel, "items": []any{}},
		"top_status": topStatusFromMergedPy(merged, rangeLabel),
	}

	if len(merged) == 0 {
		ovRoll := out["overview"].(map[string]any)
		ovRoll["rollup_empty"] = true
		ovRoll["rollup_empty_hint"] = "所选区间内 ClickHouse 分钟聚合表无数据；请确认 MV、写入与 source。"
	}

	return out, nil
}
