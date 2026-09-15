# 文档索引

## 部署与配置（优先）

| 文档 | 说明 |
|------|------|
| [deployment/README.md](./deployment/README.md) | **部署总索引**：Compose、K8s、Traffic 中间件、一键脚本入口 |
| [deployment/docker-compose.md](./deployment/docker-compose.md) | 本地 Docker Compose 说明 |
| [deployment/kubernetes.md](./deployment/kubernetes.md) | 生产 Kubernetes、RBAC、PVC、Ingress |
| [deployment/traffic-middleware.md](./deployment/traffic-middleware.md) | GeoIP / Redis / ingest / ClickHouse（YAML 在 `infra/kubernetes/middleware-system/`） |

## 功能手册

| 文档 | 说明 |
|------|------|
| [INSPECTION.md](./INSPECTION.md) | **巡检清单**：PVC exporter、inspect-prd.sh、业务服务别名 |
| [TRAFFIC_DASHBOARD.md](./TRAFFIC_DASHBOARD.md) | Traffic Dashboard：Nginx 日志、GeoIP、Blackbox、ingest API |
| [FILEBEAT_NGINX_TRAFFIC.md](./FILEBEAT_NGINX_TRAFFIC.md) | Nginx + Filebeat/Logstash 推送日志 |
| [SCHEDULE_API.md](./SCHEDULE_API.md) | 排班相关 API |

## 迁移说明

- 原 **`K8S_RBAC_GUIDE.md`** 已迁至 **`deployment/kubernetes.md`**；根目录 [K8S_RBAC_GUIDE.md](./K8S_RBAC_GUIDE.md) 仅作跳转。

项目总览与快速开始见仓库根目录 [README.md](../README.md)。基础设施清单目录见 [infra/README.md](../infra/README.md)。
