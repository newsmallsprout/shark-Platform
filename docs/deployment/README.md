# Shark Platform 部署与运维指南

本文档为仓库内**唯一**部署说明，与当前代码（Django、Vue、Docker、Kubernetes、AIOps 流式诊断、Traffic 等）对齐。旧版分散的 Compose / K8s / Traffic 多篇文档已合并到此页。

---

## 1. 术语与目录

| 名称 | 含义 |
|------|------|
| **`deploy/`**（Django 应用） | 平台内的**服务器批量部署引擎**（`/api/deploy/*`），与下述基础设施目录无关。 |
| **`infra/`** | **Docker Compose**、**Kubernetes 示例 YAML**、ClickHouse DDL 等。 |
| **`docs/deployment/README.md`** | 本文件：怎么起环境、怎么上生产、相关环境变量与运维命令。 |

---

## 2. 运行时与镜像

| 组件 | 要求 |
|------|------|
| Python | **3.9+**（根目录 `Dockerfile` 基于 `python:3.9-slim`；LangGraph 等依赖不满足 3.8） |
| 前端构建 | Node **18**（多阶段镜像内） |
| 默认 Web | 容器内 Nginx 对外 **8000**；Gunicorn 见 `entrypoint.sh` |
| 健康检查 | `GET /api/system/health`（无鉴权） |

---

## 3. 一键脚本（推荐入口）

在**仓库根目录**执行：

```bash
chmod +x scripts/oneclick-deploy.sh scripts/deploy-local.sh
```

| 脚本 | 说明 |
|------|------|
| **`scripts/oneclick-deploy.sh`** | 交互向导：生成 `infra/docker/.env.deploy`、可选 `--profile sync` / Traffic 等；非交互示例：`./scripts/oneclick-deploy.sh --yes --sync` |
| **`scripts/deploy-local.sh`** | 轻量 `docker compose up`；缺失 `.env.deploy` 时从 `infra/docker/.env.deploy.sample` 生成；支持 `--sync`、`--migrate` |

---

## 4. Docker Compose（本地）

**勿与** Django 内 `deploy/` 混淆；Compose 文件在 `infra/docker/`。

| 文件 | 说明 |
|------|------|
| `infra/docker/docker-compose.yml` | 主文件：默认仅 **应用 + SQLite**；`--profile sync` 增加 MySQL、Mongo 副本集、**Redis**、RabbitMQ |
| `infra/docker/docker-compose.sync-depends.yml` | 可选：等 MySQL 健康、Mongo 初始化后再起应用（与 `sync` profile 同用） |
| `infra/docker/.env.example` | Compose 层通用示例 |
| `infra/docker/.env.deploy.sample` | 提交样例；**实际密钥**写入 `infra/docker/.env.deploy`（已 `.gitignore`） |
| `infra/docker/mysql/` | MySQL `my.cnf` 与可选 `init/` SQL |

**常用命令**（在仓库根目录）：

```bash
# 仅应用（省资源）
docker compose -f infra/docker/docker-compose.yml up -d --build

# 联调同步栈：MySQL / Mongo / Redis / RabbitMQ
docker compose -f infra/docker/docker-compose.yml --profile sync up -d --build

# 应用等待依赖就绪后再启动
docker compose -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.sync-depends.yml \
  --profile sync up -d --build
```

也可在仓库根 `.env` 中设置 `COMPOSE_PROFILES=sync`，省略每次 `--profile sync`。

**访问**：默认 **http://localhost:8000**。首次由 `entrypoint.sh` 创建超级用户（默认 **admin / admin**），**上线或共享环境务必改密**。

---

## 5. 环境变量速查

以下为生产/联调常见项；Compose 下多写在 **`infra/docker/.env.deploy`**，K8s 下用 ConfigMap / Secret 注入。

### 5.1 Django / 安全 / 前端同源

| 变量 | 说明 |
|------|------|
| `DJANGO_SECRET_KEY` | 生产随机强密钥 |
| `ALLOWED_HOSTS` | 逗号分隔域名或 `*`（生产建议收紧） |
| `CSRF_TRUSTED_ORIGINS` | 逗号分隔完整 URL，**勿**带反引号或多余空格 |
| `PUBLIC_URL` | 对外访问根 URL（电话告警、Log Monitor 深链等） |

### 5.2 Celery 与异步任务

| 变量 | 说明 |
|------|------|
| `CELERY_BROKER_URL` | 默认 `redis://localhost:6379/0`；与 Worker 必须一致 |
| `CELERY_RESULT_BACKEND` | 默认与 broker 相同 |
| `CELERY_TIMEZONE` | 默认 `Asia/Shanghai` |

**注意**：启用 Celery 后需**单独进程**运行 Worker，例如：

```bash
celery -A shark_platform worker -l info
```

（具体模块名以 `shark_platform/celery.py` 为准。）

### 5.3 AIOps（LangGraph）事件流与 SSE

| 变量 | 说明 |
|------|------|
| `AGENT_EVENT_REDIS_URL` | 可选；Agent 事件 Pub/Sub 所用 Redis，缺省同 `CELERY_BROKER_URL` |
| `AGENT_SSE_PUBLIC_BASE` | Django 返回给前端的 **SSE 根地址**（无尾斜杠），须与浏览器可访问的 **`sse_server`** 一致，默认 `http://localhost:8010` |
| `SSE_CORS_ORIGINS` | **`sse_server.py`** 侧 CORS，逗号分隔；生产建议设为前端域名 |

**组件分工**：

1. **Django**：`POST /api/ai_ops/diagnose/<incident_id>/` 等创建 `run_id` 并入队 Celery。
2. **Celery Worker**：执行 `ai_ops.run_incident_langgraph`，经 Redis 发布 `agent:run:{run_id}` 频道事件。
3. **`sse_server.py`（FastAPI）**：订阅 Redis，对外 `GET /api/agent/stream/{run_id}`（默认端口 **8010**）。启动示例：

```bash
export CELERY_BROKER_URL=redis://localhost:6379/0
# 或与 Worker 共用 AGENT_EVENT_REDIS_URL
uvicorn sse_server:app --host 0.0.0.0 --port 8010
```

**LangGraph Redis Checkpointer**：官方 `RedisSaver` 需要 **RedisJSON + RediSearch**（或 Redis 8+ 等价能力）。若本地仅有单机 Redis 无模块，图执行可能报错，需换用合规 Redis Stack 或调整图存储方案。

### 5.4 工单闸门（可选）

| 变量 | 说明 |
|------|------|
| `SHARK_WORK_ORDER_GATE_ENABLED` | `true` / `1` 启用写操作工单校验 |
| `SHARK_WORK_ORDER_GATE_ALLOW_SUPERUSER` | 是否允许超级用户绕过（默认 true） |

批准后执行写操作需携带 **`X-Shark-Work-Order-Id`**（与 `Ticket` 联动），详见业务配置。

### 5.5 Traffic Dashboard（可选）

| 变量 | 说明 |
|------|------|
| `TRAFFIC_REDIS_URL` | 远程 ingest → Redis 模式 |
| `TRAFFIC_GEOIP_DB` | MaxMind `.mmdb` 路径 |
| `TRAFFIC_INGEST_TOKEN` | ingest API 密钥 |
| `TRAFFIC_ROLLUP_ENABLED` | 分钟聚合等 |
| `CLICKHOUSE_*` | 长期聚合入库 ClickHouse（若启用） |

使用说明见 **[docs/TRAFFIC_DASHBOARD.md](../TRAFFIC_DASHBOARD.md)**、**[docs/FILEBEAT_NGINX_TRAFFIC.md](../FILEBEAT_NGINX_TRAFFIC.md)**。

---

## 6. Kubernetes（生产）

示例与片段在 **`infra/kubernetes/`**（根目录 `shark-platform.yaml`、`configmap.yaml`、`pvc.yaml` 等）。生产环境需自行替换 **namespace、镜像、存储类、Ingress、Secret**，勿直接照搬默认值。

### 6.1 推荐步骤（概要）

1. 创建命名空间（如 `middleware-system` 或你方规范）。
2. 准备 **Secret**：至少 `DJANGO_SECRET_KEY`（`echo -n '...' | base64`）。
3. 准备 **ConfigMap**：`DEBUG=False`、`ALLOWED_HOSTS`、`CSRF_TRUSTED_ORIGINS`、`PUBLIC_URL`、同步 Runner 相关 `SYNC_RUNNER_*`（若用 Turbo Pod）等。
4. 应用 **PVC**（状态盘、日志盘等），`storageClassName` 按集群修改（如 `gp3`）。
5. **Deployment**：镜像、资源限制、`envFrom` 引用 ConfigMap/Secret；**存活/就绪探针**建议指向 `/api/system/health`。
6. **Service + Ingress**：按集群 Ingress Controller（如 Traefik、Nginx）配置 TLS 与域名。

### 6.2 日志监控 RBAC（若使用 Log Monitor）

需为运行 Shark 的 **ServiceAccount** 绑定读取 **Pod / Pod Log** 的 **ClusterRole**（跨 namespace 列表时常用 ClusterRoleBinding）。可用以下命令自检：

```bash
kubectl auth can-i list pods --as=system:serviceaccount:<ns>:<sa> -A
kubectl auth can-i get pods/log --as=system:serviceaccount:<ns>:<sa> -n <目标命名空间>
```

### 6.3 跨集群 kubeconfig（可选）

同集群部署时任务可留空 kubeconfig（in-cluster）。跨集群时示例流程：

```bash
kubectl -n <ns> create sa shark-platform-kubeconfig-sa

cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: shark-platform-kubeconfig-token
  namespace: <ns>
  annotations:
    kubernetes.io/service-account.name: shark-platform-kubeconfig-sa
type: kubernetes.io/service-account-token
YAML

kubectl create clusterrolebinding shark-platform-kubeconfig-binding \
  --clusterrole=<你的日志读角色，如 shark-log-reader> \
  --serviceaccount=<ns>:shark-platform-kubeconfig-sa

TOKEN=$(kubectl get secret shark-platform-kubeconfig-token -n <ns> -o jsonpath='{.data.token}' | base64 --decode)
CA=$(kubectl get secret shark-platform-kubeconfig-token -n <ns> -o jsonpath='{.data.ca\.crt}')
APISERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
```

将 `certificate-authority-data: ${CA}`、`server: ${APISERVER}`、`token: ${TOKEN}` 写入 kubeconfig 的 `clusters` / `users`，`current-context` 指向目标 namespace，全文粘贴到 Log Monitor 的 Kubeconfig 字段即可。

### 6.4 上线后必做

- 修改默认 **admin** 密码。
- **Schedules 去重**（如有历史重复数据）：

```bash
kubectl exec -n <ns> deploy/shark-platform -- python3 manage.py dedup_schedules
kubectl exec -n <ns> deploy/shark-platform -- python3 manage.py dedup_schedules --apply
```

- **Phone Alert / Log Monitor**：在页面配置 `PUBLIC_URL`、Slack Webhook、kubeconfig 等。

### 6.5 常用排障

```bash
kubectl get deploy,pod,svc,ingress -n <ns>
kubectl describe pod -n <ns> -l app=shark-platform | head -n 120
kubectl logs -f -n <ns> deploy/shark-platform
```

---

## 7. Traffic 中间件（Kubernetes）

清单目录：**`infra/kubernetes/middleware-system/`**（与 Django `deploy/` 无关）。

| 主题 | 操作要点 |
|------|----------|
| **命名空间** | `kubectl create namespace middleware-system`（或你的 NS） |
| **ingest 密钥** | Secret `traffic-ingest`，key `token` |
| **GeoIP PVC** | `geoip-maxmind-pvc.yaml`；首次 Job 下载 `GeoLite2-City.mmdb`；可选 CronJob 更新 |
| **Traffic Redis** | `traffic-redis.yaml` |
| **Shark 挂载** | 将 `shark-platform-geoip-traffic-patch.yaml` 中的 volume / env **合并**进现有 Deployment：`TRAFFIC_REDIS_URL`、`TRAFFIC_GEOIP_DB`、`TRAFFIC_INGEST_TOKEN` |
| **ClickHouse**（可选） | `clickhouse-traffic.yaml`、`clickhouse-traffic-init-job.yaml`、Secret `clickhouse-traffic-auth`；环境变量见 `shark-platform-clickhouse-env.yaml` |

**文件索引**：

| YAML | 说明 |
|------|------|
| `geoip-maxmind-pvc.yaml` | GeoIP PVC |
| `maxmind-geolite2-download-job.yaml` | 首次下载 Job |
| `maxmind-geolite2-cronjob.yaml` | 定期更新 |
| `traffic-redis.yaml` | Redis Service |
| `shark-platform-geoip-traffic-patch.yaml` | Shark 片段参考 |
| `shark-platform-clickhouse-env.yaml` | ClickHouse 环境片段 |
| `clickhouse-traffic.yaml` / `clickhouse-traffic-init-job.yaml` | CH 与初始化 |

大盘、ingest API、Nginx 推送格式见 **[docs/TRAFFIC_DASHBOARD.md](../TRAFFIC_DASHBOARD.md)**；大 body / Filebeat 见 **[docs/FILEBEAT_NGINX_TRAFFIC.md](../FILEBEAT_NGINX_TRAFFIC.md)**。ClickHouse DDL 参考 **`infra/clickhouse/traffic_minute_rollup.sql`**。

---

## 8. 进程与仓库入口文件

| 文件 | 说明 |
|------|------|
| 根目录 `Dockerfile` | 多阶段构建 |
| `entrypoint.sh` | 迁移、静态收集、起 Gunicorn/Nginx |
| `nginx.conf` | SPA 与 `/api/` 反代 |
| `sse_server.py` | 独立 SSE 服务（非 Django） |

---

## 9. 相关文档（非部署主线）

| 文档 | 内容 |
|------|------|
| [docs/README.md](../README.md) | 全站文档索引 |
| [docs/TRAFFIC_DASHBOARD.md](../TRAFFIC_DASHBOARD.md) | Traffic 功能与 ingest |
| [docs/SCHEDULE_API.md](../SCHEDULE_API.md) | 排班 API |
| [infra/README.md](../../infra/README.md) | `infra/` 目录索引 |
