# 文档索引

## 部署与配置（优先）

| 文档 | 说明 |
|------|------|
| **[deployment/README.md](./deployment/README.md)** | **唯一部署指南**：Docker Compose、一键脚本、Kubernetes、Traffic 中间件、AIOps（Celery / SSE）、环境变量与上线运维 |

## 功能手册

| 文档 | 说明 |
|------|------|
| [TRAFFIC_DASHBOARD.md](./TRAFFIC_DASHBOARD.md) | Traffic Dashboard：Nginx 日志、GeoIP、Blackbox、ingest API |
| [FILEBEAT_NGINX_TRAFFIC.md](./FILEBEAT_NGINX_TRAFFIC.md) | Nginx + Filebeat/Logstash 推送日志 |
| [SCHEDULE_API.md](./SCHEDULE_API.md) | 排班相关 API |

## 迁移说明

- 原 **`K8S_RBAC_GUIDE.md`** 与旧版多篇 `deployment/*.md` 已合并进 **[deployment/README.md](./deployment/README.md)**；[K8S_RBAC_GUIDE.md](./K8S_RBAC_GUIDE.md) 仅作跳转。

项目总览与快速开始见仓库根目录 [README.md](../README.md)。基础设施清单目录见 [infra/README.md](../infra/README.md)。
