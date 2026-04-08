# go-log-collector

**AIOps Platform** 轻量日志上报：可选 **关键行过滤**、**边缘正则脱敏**，批量 `POST` 至中心 `POST /api/edge/logs`。

**与 Kubernetes 的关系**：Pod 标准输出/文件日志在集群内通常应由 **Loki、EFK、或中心服务拉取 Pod 日志** 完成。本采集器更适合 **集群外节点**、**与中心同机或 sidecar 挂载同一日志目录**（例如 **Nginx `access_log` / `error_log`**），或 **必须在边缘脱敏后再出网** 的场景。

## Environment

| Variable | Description |
|----------|-------------|
| `SHARK_AIOPS_CENTER_URL` | 中心根 URL，无尾部斜杠（Compose 内常用 `http://web:8000`） |
| `SHARK_AIOPS_EDGE_TOKEN` | 须与中心环境变量 `SHARK_EDGE_TOKEN` 一致；未配置时中心拒绝 ingest |
| `SHARK_AIOPS_LOG_SOURCE` | 逻辑来源标签，写入 JSON `source`（如 `nginx`、`edge`） |
| `SHARK_AIOPS_LOG_PATHS` | 逗号分隔的多个日志文件路径；为空则从 **stdin** 读 |
| `SHARK_AIOPS_LOG_SEVERITY` | `error`（默认）/ `warn` / **`all`**。**Nginx access 一般为 200/304，须用 `all`** |
| `SHARK_AIOPS_LOG_FOLLOW` | `1` / `true`：持续跟随文件增长（类 `tail -f`），并支持 **多路径各开一个协程** |
| `SHARK_AIOPS_LOG_FROM_END` | 仅在 `LOG_FOLLOW=1` 时有效。默认 `1`：启动后只推**新行**；`0`：先把文件已有内容读完再跟随 |
| `SHARK_AIOPS_REDACT_REGEX` | 可选：`pattern@@@replacement`，多条用 `\|\|` 分隔 |
| `SHARK_AIOPS_STREAM_KEY` | 写入 JSON `stream_key`，按域名/环境隔离落库（多采集器实例各设不同值） |
| `SHARK_AIOPS_LOG_FORMAT` | 如 `nginx_json`（与中心 Nginx `shark_json` 一致）或留空走 `auto` |

内置脱敏：类邮箱、长数字串（卡号形）、`Bearer …` token。

## Build

```bash
cd go-log-collector
go build -o aiops-log-collector .
```

Docker：`docker build -t aiops-log-collector ./go-log-collector`

## Nginx 访问日志（推荐）

镜像内 Nginx 已将访问/错误日志写到固定路径（见仓库根目录 `nginx.conf`）：

- `/var/log/nginx/shark_access.log` — `combined` 格式，含 method、URI、状态码、User-Agent 等  
- `/var/log/nginx/shark_error.log`

采集示例（**必须** `SHARK_AIOPS_LOG_SEVERITY=all`）：

```bash
export SHARK_AIOPS_EDGE_TOKEN=your-secret   # 与中心 SHARK_EDGE_TOKEN 相同
export SHARK_AIOPS_CENTER_URL=http://127.0.0.1:8000
export SHARK_AIOPS_LOG_SOURCE=nginx
export SHARK_AIOPS_LOG_PATHS=/var/log/nginx/shark_access.log,/var/log/nginx/shark_error.log
export SHARK_AIOPS_LOG_FOLLOW=1
export SHARK_AIOPS_LOG_SEVERITY=all
./aiops-log-collector
```

不启用 `LOG_FOLLOW` 时，可用管道跟踪单文件（多文件建议用上面的 `LOG_PATHS` + `LOG_FOLLOW=1`）：

```bash
tail -F /var/log/nginx/shark_access.log | \
  SHARK_AIOPS_LOG_SEVERITY=all SHARK_AIOPS_EDGE_TOKEN=secret ./aiops-log-collector
```

## Docker Compose

根目录 `docker-compose.yml` 中 `web` 已将 `/var/log/nginx` 挂到卷 `nginx_logs`。启用侧车采集：

```bash
export SHARK_EDGE_TOKEN=your-secret
docker compose --profile logs up -d
```

## Center API

`POST /api/edge/logs`，JSON：`{ "source": "nginx", "lines": ["...", ...] }`，请求头 `X-Shark-Edge-Token`（与中心配置一致）。

当前中心实现主要做接收与计数日志；若要在「数据大屏」里展示 QPS/延迟，需要在后端增加落库或聚合（可再迭代）。
