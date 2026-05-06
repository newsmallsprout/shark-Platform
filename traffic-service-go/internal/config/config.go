package config

import (
	"os"
	"strconv"
	"strings"
)

// Config 运行时配置（后续可换 viper / envconfig）。
type Config struct {
	HTTPAddr            string
	PostgresDSN         string
	GeoIPDBPath         string
	GinMode             string
	DBMaxOpenConn       int
	DBMaxIdleConn       int
	IngestQueueDepth    int
	IngestWorkerCount   int
	PrometheusURL       string
	BlackboxPromQL      string
	AccessLogMode       string
	RollupIngestEnabled bool
	RedisURL            string // 用于 log_configured 判定（与 Django TRAFFIC_REDIS_URL 一致）

	// ClickHouse（设置 TRAFFIC_CLICKHOUSE_ADDR 启用 ingest → traffic_log_raw 批量写入）
	ClickHouseAddrs             string
	ClickHouseUser              string
	ClickHousePassword          string
	ClickHouseDatabase          string
	ClickHouseTable             string
	ClickHouseTLS               bool
	ClickHouseMaxOpenConn       int
	ClickHouseBatchRows         int
	ClickHouseFlushSec          int
	ClickHouseIngestCap         int
	ClickHouseRollupTable       string
	ClickHouseSnapshotTimeoutMs int
}

func (c Config) LogConfigured() bool {
	return strings.TrimSpace(c.PostgresDSN) != "" || strings.TrimSpace(c.RedisURL) != ""
}

// ClickHouseEnabled TRAFFIC_CLICKHOUSE_ADDR 非空则 ingest 走批量写入 ClickHouse。
func (c Config) ClickHouseEnabled() bool {
	return strings.TrimSpace(c.ClickHouseAddrs) != ""
}

// ClickHouseAddrList 支持逗号分隔多节点（原生协议）。
func (c Config) ClickHouseAddrList() []string {
	var out []string
	for _, p := range strings.Split(c.ClickHouseAddrs, ",") {
		if s := strings.TrimSpace(p); s != "" {
			out = append(out, s)
		}
	}
	return out
}

func envBool(key string) bool {
	v := strings.TrimSpace(strings.ToLower(os.Getenv(key)))
	return v == "1" || v == "true" || v == "yes" || v == "on"
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getenvInt(key string, def int) int {
	s := os.Getenv(key)
	if s == "" {
		return def
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return def
	}
	return n
}

func Load() Config {
	redisURL := getenv("TRAFFIC_REDIS_URL", "")
	if redisURL == "" {
		redisURL = getenv("REDIS_URL", "")
	}
	return Config{
		HTTPAddr:            getenv("HTTP_ADDR", ":8080"),
		PostgresDSN:         getenv("DATABASE_URL", ""),
		GeoIPDBPath:         getenv("TRAFFIC_GEOIP_DB", ""),
		GinMode:             getenv("GIN_MODE", "release"),
		DBMaxOpenConn:       getenvInt("DB_MAX_OPEN_CONN", 25),
		DBMaxIdleConn:       getenvInt("DB_MAX_IDLE_CONN", 10),
		IngestQueueDepth:    getenvInt("TRAFFIC_INGEST_QUEUE_DEPTH", 10000),
		IngestWorkerCount:   getenvInt("TRAFFIC_INGEST_WORKERS", 20),
		PrometheusURL:       getenv("TRAFFIC_PROMETHEUS_URL", ""),
		BlackboxPromQL:      getenv("TRAFFIC_BLACKBOX_PROMQL", ""),
		AccessLogMode:       getenv("TRAFFIC_ACCESS_LOG_MODE", "redis"),
		RollupIngestEnabled: envBool("TRAFFIC_ROLLUP_ENABLED"),
		RedisURL:            redisURL,

		ClickHouseAddrs:             getenv("TRAFFIC_CLICKHOUSE_ADDR", ""),
		ClickHouseUser:              getenv("TRAFFIC_CLICKHOUSE_USER", ""),
		ClickHousePassword:          getenv("TRAFFIC_CLICKHOUSE_PASSWORD", ""),
		ClickHouseDatabase:          getenv("TRAFFIC_CLICKHOUSE_DATABASE", "traffic"),
		ClickHouseTable:             getenv("TRAFFIC_CLICKHOUSE_TABLE", "traffic_log_raw"),
		ClickHouseTLS:               envBool("TRAFFIC_CLICKHOUSE_TLS"),
		ClickHouseMaxOpenConn:       getenvInt("TRAFFIC_CLICKHOUSE_MAX_OPEN_CONN", 16),
		ClickHouseBatchRows:         getenvInt("TRAFFIC_CLICKHOUSE_BATCH_ROWS", 5000),
		ClickHouseFlushSec:          getenvInt("TRAFFIC_CLICKHOUSE_FLUSH_SEC", 5),
		ClickHouseIngestCap:         getenvInt("TRAFFIC_CLICKHOUSE_INGEST_CAP", 65536),
		ClickHouseRollupTable:       getenv("TRAFFIC_CLICKHOUSE_ROLLUP_TABLE", "traffic_rollup_min_local"),
		ClickHouseSnapshotTimeoutMs: getenvInt("TRAFFIC_CLICKHOUSE_SNAPSHOT_TIMEOUT_MS", 25000),
	}
}
