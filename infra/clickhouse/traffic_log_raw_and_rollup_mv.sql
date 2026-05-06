-- =============================================================================
-- Traffic ClickHouse：原始访问日志 + 分钟级 AggregatingMergeTree + 物化视图
--
-- 设计对齐：
--   - Nginx JSON：timestamp / source / ip / path / status / latency（见 shark nginx_log.normalize_json_record）
--   - Postgres TrafficMinuteRollup：bucket_start→minute、requests、sum/count_latency、
--     status_2xx/4xx/5xx、p95（及可选 top/geo 中间状态）
--
-- 引擎选型简述（详见仓库文档或下方注释）：
--   - MergeTree(raw)：按时间分区、按 source+time+path 排序 → 时间范围裁剪 + source 过滤快，
--     path 在排序键中便于「单路径」诊断查询（高基数路径会增大排序开销，可后续改为 ORDER BY (source, timestamp) + bloom）。
--   - AggregatingMergeTree(rollup)：增量合并聚合状态，MV 写入轻量；查询侧用 *Merge 合并同一 minute+source 的多 parts。
--   - geo_counts：sumMap 状态 → 多国计数可无损合并；查时用 sumMapMerge → Map(Tuple keys, values) 再转 JSON。
--
-- 兼容说明：现有 Django 双写表 traffic.traffic_minute_rollup（ReplacingMergeTree）仍在
-- traffic_minute_rollup.sql；本文件为「日志先入 CH → 自动聚合」的另一条链路，可按需选用。
-- =============================================================================

CREATE DATABASE IF NOT EXISTS traffic;

-- -----------------------------------------------------------------------------
-- 1) 原始日志：MergeTree
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS traffic.traffic_log_raw
(
    `timestamp` DateTime64(3, 'UTC'),
    `source` LowCardinality(String) DEFAULT '',
    `ip` String COMMENT 'remote_addr / X-Forwarded-For 解析后的客户端 IP（IPv4/IPv6 文本）',
    `method` Enum8(
        'UNKNOWN' = 0,
        'GET' = 1,
        'HEAD' = 2,
        'POST' = 3,
        'PUT' = 4,
        'PATCH' = 5,
        'DELETE' = 6,
        'OPTIONS' = 7,
        'CONNECT' = 8,
        'TRACE' = 9,
        'OTHER' = 127
    ) DEFAULT 'UNKNOWN',
    `path` String COMMENT 'request_uri 去 query，与 nginx_log.normalize_json_record 一致',
    `status` UInt16 COMMENT 'HTTP status',
    -- duration：Nginx $request_time（秒）。latency_ms 省略时可由 DEFAULT 推导；JSON 直写毫秒时请填 latency_ms。
    `duration` Float64 DEFAULT 0 COMMENT '与 Nginx $request_time 一致：秒（浮点）',
    `latency_ms` Float64 DEFAULT if(isFinite(duration) AND duration > 0, duration * 1000, 0)
        COMMENT '与 TrafficMinuteRollup.sum_latency_ms / count_latency 对齐：毫秒',
    `country_code` FixedString(2) COMMENT 'ISO 3166-1 alpha-2，未知建议写入 ZZ',
    `referer` String DEFAULT '',
    `user_agent` String DEFAULT '',
    `body_bytes_sent` UInt64 DEFAULT 0
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (source, timestamp, path)
TTL timestamp + toIntervalDay(7)
SETTINGS index_granularity = 8192;

-- 可选：IPv6 入库过长时可改用 IPv6 类型；当前 String 与现有管线一致。

-- -----------------------------------------------------------------------------
-- 2) 分钟聚合（本地表）：AggregatingMergeTree
--    查询示例（合并 states）：
--
--    SELECT
--        minute,
--        source,
--        sumMerge(requests) AS requests,
--        sumMerge(sum_latency_ms) AS sum_latency_ms,
--        sumMerge(count_latency) AS count_latency,
--        arrayElement(quantilesMerge(0.95)(p95_duration_ms), 1) AS p95_ms,
--        quantilesTDigestMerge(0.5, 0.95, 0.99)(latency_digest) AS latency_tuple,
--        sumMerge(status_2xx) AS status_2xx,
--        sumMerge(status_4xx) AS status_4xx,
--        sumMerge(status_5xx) AS status_5xx,
--        sumMapMerge(geo_counts) AS geo_map
--    FROM traffic.traffic_rollup_min_local
--    WHERE minute >= ... AND minute < ...
--    GROUP BY minute, source;
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS traffic.traffic_rollup_min_local
(
    `minute` DateTime COMMENT 'UTC 分钟起点，对齐 bucket_start',
    `source` LowCardinality(String) DEFAULT '',

    `requests` SimpleAggregateFunction(sum, UInt64),

    -- 与 Postgres 整数口径一致（毫秒总和 / 样本数 → 平均延迟）
    `sum_latency_ms` SimpleAggregateFunction(sum, UInt64),
    `count_latency` SimpleAggregateFunction(sum, UInt64),

    -- 用户指定：quantiles(0.95) 状态（精确合并；超高 QPS 时可改为 quantileTDigestState）
    `p95_duration_ms` AggregateFunction(quantiles(0.95), Float64),

    -- 可选：与 Django rollup 中 p50/p99 同源的 TDigest 状态（查询 quantilesTDigestMerge(0.5,0.95,0.99)(...)）
    `latency_digest` AggregateFunction(quantilesTDigest(0.5, 0.95, 0.99), Float64),

    `status_2xx` SimpleAggregateFunction(sum, UInt64),
    `status_4xx` SimpleAggregateFunction(sum, UInt64),
    `status_5xx` SimpleAggregateFunction(sum, UInt64),

    -- 多国计数：写入 sumMapState([cc], [1])；合并后 sumMapMerge → (keys, vals)
    `geo_counts` AggregateFunction(sumMap, FixedString(2), UInt64),

    -- 与 TrafficMinuteRollup.top_paths 近似对应：TopK 合并为近似结果（非精确 JSON 榜单）
    `top_paths` AggregateFunction(topKWeighted(100), String, UInt64)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMMDD(minute)
ORDER BY (source, minute)
TTL minute + toIntervalDay(180)
SETTINGS index_granularity = 8192;

-- -----------------------------------------------------------------------------
-- 3) 物化视图：raw INSERT → 增量写入 rollup 状态
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS traffic.traffic_log_to_rollup_mv
TO traffic.traffic_rollup_min_local
AS
SELECT
    toStartOfMinute(timestamp) AS minute,
    source,
    sumSimpleState(toUInt64(1)) AS requests,
    sumSimpleState(toUInt64(round(latency_ms))) AS sum_latency_ms,
    sumSimpleState(toUInt64(if(isFinite(latency_ms) AND latency_ms >= 0, 1, 0))) AS count_latency,
    quantilesState(0.95)(if(isFinite(latency_ms), latency_ms, 0.)) AS p95_duration_ms,
    quantilesTDigestState(0.5, 0.95, 0.99)(if(isFinite(latency_ms), latency_ms, 0.)) AS latency_digest,
    sumSimpleState(toUInt64(if(status >= 200 AND status <= 299, 1, 0))) AS status_2xx,
    sumSimpleState(toUInt64(if(status >= 400 AND status <= 499, 1, 0))) AS status_4xx,
    sumSimpleState(toUInt64(if(status >= 500 AND status <= 599, 1, 0))) AS status_5xx,
    sumMapState(
        [if(country_code = defaultValueOfTypeName('FixedString(2)), cast('ZZ', 'FixedString(2)'), country_code)],
        [toUInt64(1)]
    ) AS geo_counts,
    topKWeightedState(100)(path, toUInt64(1)) AS top_paths
FROM traffic.traffic_log_raw
GROUP BY
    minute,
    source;

-- -----------------------------------------------------------------------------
-- 已有集群变更 TTL（表已存在时执行）
-- -----------------------------------------------------------------------------
-- ALTER TABLE traffic.traffic_log_raw MODIFY TTL timestamp + INTERVAL 7 DAY;
-- ALTER TABLE traffic.traffic_rollup_min_local MODIFY TTL minute + INTERVAL 180 DAY;
