package traffic

import (
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// BlackboxConfig Prometheus Blackbox 摘要（对齐 Django fetch_blackbox_summary 返回结构）。
type BlackboxConfig struct {
	PrometheusURL string
	PromQL        string
	HTTPClient    *http.Client
}

func roundFloat(v float64, prec int) float64 {
	p := math.Pow10(prec)
	return math.Round(v*p) / p
}

func fetchBlackboxSummary(cfg BlackboxConfig) map[string]any {
	client := cfg.HTTPClient
	if client == nil {
		client = http.DefaultClient
	}
	base := strings.TrimSuffix(strings.TrimSpace(cfg.PrometheusURL), "/")
	promql := strings.TrimSpace(cfg.PromQL)
	if promql == "" {
		promql = "probe_success"
	}

	refreshed := iso8601ZMicro(time.Now().UTC())
	out := map[string]any{
		"refreshed_at":            refreshed,
		"prometheus_configured":   base != "",
		"targets":                 []any{},
		"availability_pct":        nil,
	}

	if base == "" {
		return out
	}

	vectors := queryInstantPrometheus(client, base, promql)
	targets := make([]any, 0, len(vectors))
	upCount := 0
	for _, v := range vectors {
		m, _ := v["metric"].(map[string]any)
		valStr := promInstantValue(v)
		up := false
		if f, err := strconv.ParseFloat(valStr, 64); err == nil && f >= 1.0 {
			up = true
			upCount++
		}
		inst := metricPick(m, "instance", "target", "probe")
		name := metricPick(m, "job", "service")
		if name == "" {
			name = inst
		}
		targets = append(targets, map[string]any{
			"name":       name,
			"instance":   inst,
			"up":         up,
			"raw_value":  valStr,
			"avg_latency_ms": 0.0,
		})
	}

	latByInst := map[string]float64{}
	for _, v := range queryInstantPrometheus(client, base, "probe_duration_seconds") {
		m, _ := v["metric"].(map[string]any)
		inst := metricPick(m, "instance")
		if inst == "" {
			continue
		}
		if vStr := promInstantValue(v); vStr != "" {
			if sec, err := strconv.ParseFloat(vStr, 64); err == nil {
				latByInst[inst] = sec * 1000.0
			}
		}
	}

	for i := range targets {
		t := targets[i].(map[string]any)
		inst, _ := t["instance"].(string)
		if ms, ok := latByInst[inst]; ok {
			t["avg_latency_ms"] = roundFloat(ms, 2)
		}
	}

	out["targets"] = targets
	n := len(targets)
	if n > 0 {
		out["availability_pct"] = roundFloat(float64(upCount)/float64(n)*100.0, 3)
	}
	return out
}

func metricPick(m map[string]any, keys ...string) string {
	for _, k := range keys {
		if s, ok := m[k].(string); ok && s != "" {
			return s
		}
	}
	return ""
}

func promInstantValue(v map[string]any) string {
	arr, _ := v["value"].([]any)
	if len(arr) < 2 {
		return "0"
	}
	switch x := arr[1].(type) {
	case string:
		return x
	case float64:
		return strconv.FormatFloat(x, 'f', -1, 64)
	default:
		return fmt.Sprint(x)
	}
}

func queryInstantPrometheus(client *http.Client, base, promql string) []map[string]any {
	u := base + "/api/v1/query"
	req, err := http.NewRequest(http.MethodGet, u, nil)
	if err != nil {
		return nil
	}
	q := req.URL.Query()
	q.Set("query", promql)
	req.URL.RawQuery = q.Encode()
	resp, err := client.Do(req)
	if err != nil || resp == nil {
		return nil
	}
	defer resp.Body.Close()
	var wrap struct {
		Data struct {
			Result []map[string]any `json:"result"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&wrap); err != nil {
		return nil
	}
	return wrap.Data.Result
}

func iso8601ZMicro(t time.Time) string {
	s := t.UTC().Format(time.RFC3339Nano)
	s = strings.Replace(s, "+00:00", "Z", 1)
	return s
}
