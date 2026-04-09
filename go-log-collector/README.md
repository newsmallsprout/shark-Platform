# go-log-collector

**AIOps Platform** 轻量日志上报：可选 **关键行过滤**、**边缘正则脱敏**，批量 `POST` 至中心 `POST /api/edge/logs`。

**与 Kubernetes 的关系**：Pod 标准输出/文件日志在集群内通常应由 **Loki、EFK、或中心服务拉取 Pod 日志** 完成。本采集器更适合 **集群外节点**、**与中心同机或 sidecar 挂载同一日志目录**（例如 **Nginx `access_log` / `error_log`**），或 **必须在边缘脱敏后再出网** 的场景。

## Environment

| Variable | Description |
|----------|-------------|
| `SHARK_AIOPS_CENTER_URL` | 中心根 URL，无尾部斜杠（Compose 内常用 `http://web:8000`） |
| `SHARK_AIOPS_EDGE_TOKEN` | 须与中心环境变量 `SHARK_EDGE_TOKEN` 一致；未配置时中心拒绝 ingest |
| `SHARK_AIOPS_LOG_SOURCE` | 逻辑来源标签，写入 JSON `source`（如 `nginx`、`edge`） |
| `SHARK_AIOPS_LOG_PATHS` | 逗号分隔；支持 `*`、`?`、`[` **glob**。可与真实路径混写，例如 `access_*.json.log,/var/log/nginx/access.log` |
| `SHARK_AIOPS_LOG_SEVERITY` | `error`（默认）/ `warn` / **`all`**。**Nginx access 一般为 200/304，须用 `all`** |
| `SHARK_AIOPS_LOG_FOLLOW` | `1` / `true`：持续跟随文件增长（类 `tail -f`），并支持 **多路径各开一个协程** |
| `SHARK_AIOPS_LOG_FROM_END` | 仅在 `LOG_FOLLOW=1` 时有效。默认 `1`：启动后只推**新行**；`0`：先把文件已有内容读完再跟随 |
| `SHARK_AIOPS_REDACT_REGEX` | 可选：`pattern@@@replacement`，多条用 `\|\|` 分隔 |
| `SHARK_AIOPS_STREAM_KEY` | 写入 JSON `stream_key`，按域名/环境隔离落库（多采集器实例各设不同值） |
| `SHARK_AIOPS_LOG_FORMAT` | 如 `nginx_json`（与中心 Nginx `shark_json` 一致）或留空走 `auto` |
| `SHARK_AIOPS_LOG_BATCH_SIZE` | 每批上报行数，默认 `100`。经 Docker 桥接访问 VPN/跨网段时大包易被 RST，可改为 `10`～`30` 试 |

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

### `access_*.json.log` 在宿主机上不存在？

默认 YUM/APT 安装的 Nginx 通常只有 **`/var/log/nginx/access.log`**，不会自动生成 `access_api.json.log` 等文件名。任选其一：

1. **改 `SHARK_AIOPS_LOG_PATHS`** 指向真实文件（并保证 `log_format` 与中心解析一致，JSON 行用 `nginx_json` 或留空由平台推断）。
2. **在 Nginx 里按业务拆分 `access_log`**，使磁盘上出现与 glob 一致的文件名。

在 **`LOG_FOLLOW=1` 且路径含 glob** 时，若当前无匹配文件，采集器会 **保留运行** 并约每 45 秒重试 glob（不再因 `restart: unless-stopped` 反复崩溃刷日志）。一次性采集（无 follow）仍会在无匹配时退出。

### 宿主机 `curl` 正常，容器里 `push: connection reset by peer`

说明 **中心可达**，但 **经 Docker 默认网桥（`172.17.x.x`）发出的较大 POST** 被对端或中间网络掐断；小请求（如健康检查、短 `curl`）仍可能成功。

1. **优先**：`docker run` 增加 **`--network host`**（Linux），使采集器与你在宿主机执行的 `curl` 走同一网络栈。  
2. **或** 减小批量：`SHARK_AIOPS_LOG_BATCH_SIZE=20`（或 `10`）。  
3. **验证**：`docker exec` 进容器，对同一 URL 发 **大体积** JSON POST（模拟多行 access），看是否复现 RST。

## Docker Compose

根目录 `docker-compose.yml` 中 `web` 已将 `/var/log/nginx` 挂到卷 `nginx_logs`。启用侧车采集：

```bash
export SHARK_EDGE_TOKEN=your-secret
docker compose --profile logs up -d
```

## 大屏「无 client_ip」是什么意思？

中心会把 **每条 JSON 行里的 `remote_addr` / `http_x_forwarded_for` / `http_x_real_ip` 等** 解析成入库字段 **`client_ip`**，**不要求**你的日志里本来就有一个键叫 `client_ip`。

若聚合里出现 **「无 client_ip …」**，表示有一部分行 **没有解析出任何合法 IP**，常见原因：

1. **该行不是 JSON**（例如普通文本、`error.log` 混进 access 文件），`parse_line` 拿不到 IP。  
2. **JSON 里没有 `remote_addr`**（或全是 `"-"` / 空串），且 XFF、X-Real-IP 也为空。  
3. **一行 JSON 数组** `[{...}]`：现已支持 **仅含一个对象的数组**；多条对象的数组仍会跳过。  
4. **历史数据**：改 Nginx 格式或解析规则前写入的行仍是空 `client_ip`，可对 PG/CH 做 Geo 与 IP 相关回填（见中心 `backfill_*` 命令）。

建议在 `shark_json` 中保留 **`remote_addr`**，代理后增加 **`http_x_forwarded_for`**；若使用 `real_ip`，可打 **`http_x_real_ip`**（见仓库 `nginx-log-format.conf`）。

## Center API

`POST /api/edge/logs`，JSON：`{ "source": "nginx", "lines": ["...", ...], "stream_key": "...", "log_format": "nginx_json" }`，请求头 `X-Shark-Edge-Token`（与中心配置一致）。中心会解析并落库，供大屏 QPS/Geo 等聚合使用。
