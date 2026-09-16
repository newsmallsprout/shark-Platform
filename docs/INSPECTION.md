# 巡检（System Inspection）

日常「集群好不好」走这一套，不要和 Log Monitor（拉 Pod 日志告警）混在一起。

## 两路入口，同一张清单

| 入口 | 适用 | 数据从哪来 |
|------|------|------------|
| Shark **System Inspection** | 定时 08:00 + 页面手动 Run | Prometheus 即时查询 |
| [`scripts/inspect-prd.sh`](../scripts/inspect-prd.sh) | ops-host 上手动（先 `kauth-prd-admin`） | kubectl + Prom 代理 |

Job 失败会带上 `kube_job_status_start_time`。CronJob 产生的失败记录超过 24 小时视为历史，不进发现问题；一次性 Job 失败仍会报。

`HostDown` / node-exporter down：实例 IP 不在当前 kube 节点（InternalIP）上，单独进「已下线残留」（能扫到、但机器已经不在集群里），不进发现问题、不扣健康分，避免忘记摘 scrape。真正还在集群里的 NotReady 节点仍会报。

工作负载一眼看 Deploy/STS 的 **Ready n/m**（等价 `kubectl get deploy`）。展开才是 Pod 名、Pod IP、节点 IP。默认不扫 `kube-system` / `kube-public` / `kube-node-lease`，其它 namespace 只要 Prom 里有就会出现，不靠白名单。别名只是展示名。节点 CPU/内存/磁盘仍在原来的机器表。PVC 用量仍走 `pvc_stats_*`。

## PVC 用量

PRD 已部署 [`pvc-stats-exporter`](../infra/kubernetes/monitor/pvc-stats-exporter/)。巡检优先查：

```text
pvc_stats_used_bytes
pvc_stats_capacity_bytes
```

报告列出 **每一块 PVC** 的 used/cap/百分比，不合并。别名只是额外一列（撮合 / Flink / Traefik）。

## Elasticsearch

走 `monitor` 里已有的 **elasticsearch-exporter**（Prometheus），不调 `_cluster/health` HTTP：

- `elasticsearch_cluster_health_status`（green/yellow/red）
- 节点数、未分配分片
- `elasticsearch_jvm_memory_*{area="heap"}` 堆用量

## 中间件（按指标名扫描）

Shark **只读 Prometheus**，不调 `aws rds describe-*`。

每次巡检先拉 `/api/v1/label/__name__/values`，再按前缀套食谱。**扫到才检查，没扫到的族不列出**（未覆盖 ≠ 健康）：

| 扫到的前缀 | 当成 |
|------------|------|
| `redis_` | Redis / ElastiCache（`redis_up`、内存 used/max；max=0 显示用量+无上限） |
| `mysql_` / `mysqld_` | MySQL / RDS（`mysql_up`、InnoDB 缓冲池） |
| `pg_` | PostgreSQL / RDS（探活） |
| `mongodb_` | MongoDB（`mongodb_up`、WT 缓存或 RSS） |
| `rabbitmq_` | RabbitMQ / Amazon MQ（探活、内存、磁盘剩余水位） |
| `kafka_` | Kafka（探活；有 JVM 堆指标才显示堆） |
| `nats_` | NATS（探活） |
| `minio_` | MinIO（探活、集群盘 used/total） |
| `aws_rds_` | RDS CloudWatch exporter（CPU、replica lag） |
| `aws_elasticache_` | ElastiCache CloudWatch exporter（CPU、内存%） |
| 其它 `*_up`（排除 `node_*` / `kube_*` / `up`） | 未登记的 exporter，按 up/down 列出 |

实例名来自指标标签（`instance` / `addr` / `dimension_DBInstanceIdentifier`），不写死。要把 AWS 上的 RDS、ElastiCache 纳进巡检，先让对应 exporter 进 Prometheus。

## 配置

页面 **System → Configure AI**：

- **Prometheus Endpoint**：集群内填 `http://prometheus.monitor.svc:9090`（Service 名是 `prometheus`，不是 `prometheus-k8s`）
- 确认该 Prometheus 已抓取 `pvc-stats-exporter`（`monitor` 命名空间，端口 9100）
- 有 kube-state-metrics / blackbox 时，对应检查项才会从 skip 变成正常/关注

## 报告怎么读

1. **总体评估** + 检查清单（正常 / 关注 / 严重）
2. **发现问题**（不含已知常态、不含已下线残留）
3. **已下线残留**：还能扫到、但不在当前节点上（关机后没摘 scrape）
4. **未覆盖**（缺指标，不等于健康）
5. **业务服务**、**PVC 用量**
6. 节点 CPU/内存/磁盘、firing 告警、AI 分析

手动 kubectl 版：

```bash
# 在 ops-host
kauth-prd-admin <MFA码>
bash scripts/inspect-prd.sh
# 或 INSPECT_OUT=/tmp/prd.md bash scripts/inspect-prd.sh
```
