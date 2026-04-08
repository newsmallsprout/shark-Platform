-- 模板：PostgreSQL 原生 RANGE 分区（非 Django migration 管理）
-- 使用前请备份；新库可考虑在首次 migrate 前用分区表替代 ORM 表（需自定义 migration）。

-- 示例：按月分区父表（字段需与 observability_logevent 一致）
-- CREATE TABLE observability_logevent_p (
--     id BIGSERIAL,
--     stream_key VARCHAR(128) NOT NULL,
--     event_time TIMESTAMPTZ NOT NULL,
--     ...
--     PRIMARY KEY (id, event_time)
-- ) PARTITION BY RANGE (event_time);
--
-- CREATE TABLE observability_logevent_y2026m01 PARTITION OF observability_logevent_p
--     FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

SELECT 1; -- placeholder
