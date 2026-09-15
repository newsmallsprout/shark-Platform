# 基础设施清单（Compose / K8s）

本目录存放 **Docker Compose** 与 **Kubernetes 示例 YAML**，与 Django 应用内的 **`deploy/`**（服务器批量部署引擎）无关。

**完整说明与索引**见 **[docs/deployment/README.md](../docs/deployment/README.md)**。

| 路径 | 说明 |
|------|------|
| [docker/docker-compose.yml](./docker/docker-compose.yml) | 本地编排主文件 |
| [docker/docker-compose.sync-depends.yml](./docker/docker-compose.sync-depends.yml) | 可选依赖顺序 |
| [docker/.env.example](./docker/.env.example) | Compose 环境变量示例 |
| [kubernetes/](./kubernetes/) | Deployment / Service / ConfigMap / PVC 等 |
| [kubernetes/middleware-system/](./kubernetes/middleware-system/) | Traffic：Redis、GeoIP、ClickHouse 等 |
| [kubernetes/monitor/pvc-stats-exporter/](./kubernetes/monitor/pvc-stats-exporter/) | PVC 用量 Prometheus exporter（PRD 已部署） |
| [clickhouse/](./clickhouse/) | ClickHouse DDL 参考 |

一键部署：`./scripts/oneclick-deploy.sh`（交互向导）或 `./scripts/deploy-local.sh`（轻量）。若手写 `docker compose` 且尚无 `infra/docker/.env.deploy`，请先：`cp infra/docker/.env.deploy.sample infra/docker/.env.deploy` 并修改密钥。
