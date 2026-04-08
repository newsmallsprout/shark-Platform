# PostgreSQL 可选：按时间分区 `observability_logevent`

Django 默认创建**非分区**普通表，便于 SQLite / PG 共用同一套 migration。

在 **仅 PostgreSQL** 且数据量极大时，可由 DBA 在新环境执行**原生分区表**方案（需停写或迁移数据，此处仅作参考）：

1. 新建分区父表 + `PARTITION BY RANGE (event_time)`。
2. 按月 `CREATE TABLE ... PARTITION OF ... FOR VALUES FROM ... TO ...`。
3. 应用双写或迁移历史数据后切换表名。

示例脚本见 `pg_partition_logevent.template.sql`（执行前请按环境修改表名/时间范围，**勿在生产直接运行未审核脚本**）。

ClickHouse 侧已在 `clickhouse_store.ensure_schema()` 中按 `toYYYYMM(toDate(event_time))` 自动分区，并带 **180 天 TTL**。
