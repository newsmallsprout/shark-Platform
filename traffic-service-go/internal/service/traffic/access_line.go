package traffic

import (
	"bytes"
	"encoding/json"
	"net"
	"strconv"
	"strings"
)

// AccessLineRaw Nginx JSON access 日志单行（按需字段，减轻解码开销）。
type AccessLineRaw struct {
	MSec        string          `json:"msec"`
	TimeLocal   string          `json:"time_local"`
	RemoteAddr  string          `json:"remote_addr"`
	Method      string          `json:"method"`
	RequestURI  string          `json:"request_uri"`
	Status      int             `json:"status"`
	RequestTime json.RawMessage `json:"request_time"`
	Referer     string          `json:"http_referer"`
	UserAgent   string          `json:"http_user_agent"`
	BodyBytes   json.RawMessage `json:"body_bytes_sent"`
}

// CleanedRecord Worker 输出：下游内存聚合器 / ClickHouse 批量写入。
type CleanedRecord struct {
	Source        string
	RemoteAddr    string
	CountryISO    string
	Method        string
	Referer       string
	UserAgent     string
	BodyBytesSent uint64
	RequestURI    string
	Status        int
	RequestTimeS  float64 // Nginx 原始秒
	MSecUnix      float64 // $msec Unix 秒（若有）
}

// PathForStore request_uri 去掉 query，供 ClickHouse path 列及榜单口径对齐 Django normalize_json_record。
func PathForStore(uri string) string {
	uri = strings.TrimSpace(uri)
	if i := strings.IndexByte(uri, '?'); i >= 0 {
		uri = uri[:i]
	}
	if uri == "" {
		return "/"
	}
	return uri
}

func parseBodyBytesSent(raw json.RawMessage) uint64 {
	raw = bytes.TrimSpace(raw)
	if len(raw) == 0 {
		return 0
	}
	if raw[0] == '"' {
		var s string
		if err := json.Unmarshal(raw, &s); err != nil {
			return 0
		}
		v, err := strconv.ParseUint(s, 10, 64)
		if err != nil {
			return 0
		}
		return v
	}
	var n uint64
	if err := json.Unmarshal(raw, &n); err != nil {
		return 0
	}
	return n
}

func parseRequestTimeSeconds(raw json.RawMessage) float64 {
	raw = bytes.TrimSpace(raw)
	if len(raw) == 0 {
		return 0
	}
	if raw[0] == '"' {
		var s string
		if err := json.Unmarshal(raw, &s); err != nil {
			return 0
		}
		v, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return 0
		}
		return v
	}
	var f float64
	if err := json.Unmarshal(raw, &f); err != nil {
		return 0
	}
	return f
}

func parseMSecUnix(s string) float64 {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 0
	}
	return v
}

func firstForwardedIP(s string) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexByte(s, ','); i >= 0 {
		s = strings.TrimSpace(s[:i])
	}
	if host, _, err := net.SplitHostPort(s); err == nil {
		return host
	}
	return s
}
