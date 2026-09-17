# pvc-stats-exporter

从 kubelet `nodes/*/proxy/stats/summary` 抽出 PVC `usedBytes` / `capacityBytes`，暴露：

- `pvc_stats_used_bytes{namespace,persistentvolumeclaim}`
- `pvc_stats_capacity_bytes{namespace,persistentvolumeclaim}`

PRD 已部署在 `monitor` namespace（镜像 `etz/pvc-stats-exporter:v1.1.0`）。Prometheus 靠 `prometheus.io/scrape` 注解抓取。

Shark 巡检（System Inspection）和 `scripts/inspect-prd.sh` 都读这组指标，用来回答「这块盘是哪个服务、用了多少」，而不是只看 IP。

## 部署

```bash
kubectl apply -f deploy.yaml
```

构建：

```bash
docker build -t <registry>/etz/pvc-stats-exporter:v1.1.0 .
```

ServiceAccount 需要 `nodes` / `nodes/proxy` / `nodes/stats` 的 get/list。
