# 巡检（System Inspection）

日常「集群好不好」走这一套，不要和 Log Monitor（拉 Pod 日志告警）混在一起。

## 两路入口，同一张清单

| 入口 | 适用 | 数据从哪来 |
|------|------|------------|
| Shark **System Inspection** | 定时 08:00 + 页面手动 Run | Prometheus 即时查询 |
| [`scripts/inspect-prd.sh`](../scripts/inspect-prd.sh) | ops-host 上手动（先 `kauth-prd-admin`） | kubectl + Prom 代理 |

清单对齐 `inspect-prd.sh`：**节点 / 按 Pod 名的工作负载 / 异常 Pod / OOM 与重启 / 全部 PVC 用量 / Elasticsearch（exporter）/ firing / Blackbox / ArgoCD / 副本**。缺指标的项标成 **未覆盖**，不写成健康。

工作负载一眼看 Deploy/STS 的 **Ready n/m**（等价 `kubectl get deploy`）。展开才是 Pod 名、Pod IP、节点 IP。节点 CPU/内存/磁盘仍在原来的机器表（node-exporter 的 instance IP）。不扫 `kube-system`。PVC 用量仍走 `pvc_stats_*`。

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

## 配置

页面 **System → Configure AI**：

- **Prometheus Endpoint**：集群内填 `http://prometheus.monitor.svc:9090`（Service 名是 `prometheus`，不是 `prometheus-k8s`）
- 确认该 Prometheus 已抓取 `pvc-stats-exporter`（`monitor` 命名空间，端口 9100）
- 有 kube-state-metrics / blackbox 时，对应检查项才会从 skip 变成正常/关注

## 报告怎么读

1. **总体评估** + 检查清单（正常 / 关注 / 严重 / 未覆盖）
2. **发现问题**（不含已知常态）
3. **业务服务**、**PVC 用量**
4. 节点 CPU/内存/磁盘、firing 告警、AI 分析

手动 kubectl 版：

```bash
# 在 ops-host
kauth-prd-admin <MFA码>
bash scripts/inspect-prd.sh
# 或 INSPECT_OUT=/tmp/prd.md bash scripts/inspect-prd.sh
```
