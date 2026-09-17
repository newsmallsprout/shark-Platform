# 部署与运维文档（索引）

Shark Platform 的**环境搭建、编排与生产上线**说明集中在本目录；功能使用手册仍在 `docs/` 根下。

| 文档 | 说明 |
|------|------|
| [docker-compose.md](./docker-compose.md) | 本地 Docker Compose：默认仅应用、可选 `sync` profile（MySQL/Mongo/Redis 等） |
| [kubernetes.md](./kubernetes.md) | 生产 Kubernetes：RBAC、Secret、PVC、Ingress、初始化与维护 |
| [traffic-middleware.md](./traffic-middleware.md) | Traffic 相关中间件：GeoIP PVC、Redis、ingest、ClickHouse（YAML 在 `infra/kubernetes/middleware-system/`） |

**交互式一键部署**（控制台引导必填项、生成 `infra/docker/.env.deploy`、启动 Compose）：

```bash
chmod +x scripts/oneclick-deploy.sh   # 首次克隆后
./scripts/oneclick-deploy.sh
./scripts/oneclick-deploy.sh --yes --sync --traffic   # 非交互示例
```

**轻量一键**（较少提示，从 `.env.deploy.sample` 生成缺失的 `.env.deploy`）：

```bash
./scripts/deploy-local.sh
./scripts/deploy-local.sh --sync
./scripts/deploy-local.sh --migrate
```

**清单路径**

| 用途 | 路径 |
|------|------|
| Compose 主文件 | `infra/docker/docker-compose.yml` |
| 依赖顺序覆盖 | `infra/docker/docker-compose.sync-depends.yml` |
| Compose 环境示例 | `infra/docker/.env.example`、`infra/docker/.env.deploy.sample` |
| 本机密钥（勿提交） | `infra/docker/.env.deploy`（由一键脚本生成） |
| K8s 应用示例 | `infra/kubernetes/shark-platform.yaml` 等 |
| Traffic 中间件 YAML | `infra/kubernetes/middleware-system/*.yaml` |
| PVC 用量 exporter | `infra/kubernetes/monitor/pvc-stats-exporter/` |
| PRD kubectl 巡检脚本 | `scripts/inspect-prd.sh`（与 System Inspection 同一清单） |
| ClickHouse DDL | `infra/clickhouse/traffic_minute_rollup.sql` |

根目录 [Dockerfile](../../Dockerfile)、[entrypoint.sh](../../entrypoint.sh)、[nginx.conf](../../nginx.conf) 为镜像与进程入口。健康检查：`GET /api/system/health`（无鉴权）。
