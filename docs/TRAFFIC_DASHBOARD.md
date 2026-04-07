# Traffic Dashboard 配置与运维手册

本文说明 **Shark Platform · Traffic Dashboard**（原 Dashboard 已替换为流量大盘）所需的后端、Nginx 日志、GeoIP、Prometheus Blackbox 与前端依赖配置。

---

## 1. 功能概览

- 从 **Nginx access 日志**解析请求：支持 **本机/挂载卷读文件**，或 **独立 Nginx 机经 HTTP 推入 Redis List** 后在 K8s 内聚合。
- 可选 **MaxMind GeoIP2 / GeoLite2**（`geoip2` Python 库 + **`.mmdb` 城市库**）解析 `remote_addr` → 国家/省份，驱动地图与排行。
- 通过 **Prometheus HTTP API** 查询 **Blackbox Exporter**（如 `probe_success`、`probe_duration_seconds`）展示可用性。
- **Jaeger**：第二 Tab 为占位 + 模拟 Trace 列表；后续对接 Jaeger Query API 即可替换。
- 前端：**Vue 3 + ECharts 6 + echarts-gl**（3D 地球）、世界地图 JSON 自 jsDelivr 加载（需浏览器出网或使用自建 CDN）。

---

## 2. 部署必做步骤

### 2.1 数据库迁移

```bash
cd /path/to/mysql_to_mongo
pip install -r requirements.txt   # 含 geoip2
python manage.py migrate traffic
```

### 2.2 前端依赖（echarts-gl 与 echarts 6 需放宽 peer）

```bash
cd frontend
npm install
# 若未安装 echarts-gl：
npm install echarts-gl@2.0.9 --save --legacy-peer-deps
npm run build
```

### 2.3 Django `INSTALLED_APPS`

已加入 `traffic`；URL 已挂载：`/api/traffic/*`。

---

## 3. 环境变量（推荐生产使用）

### 3.1 通用

| 变量 | 说明 |
|------|------|
| `TRAFFIC_NGINX_ACCESS_LOG` | **文件模式**：access 日志绝对路径；未在后台配置时作默认值。 |
| `TRAFFIC_GEOIP_DB` | **MaxMind** `GeoIP2-City.mmdb` 或 `GeoLite2-City.mmdb` 的绝对路径。与后台「MaxMind mmdb」二选一，**后台优先**。 |
| `TRAFFIC_ACCESS_LOG_MODE` | 可选：`file` / `redis`，覆盖默认；通常用后台「采集模式」即可。 |

### 3.2 Redis 远程推送模式（Nginx 与 Shark 分机 / K8s）

| 变量 | 说明 |
|------|------|
| `TRAFFIC_REDIS_URL` | Redis 连接串，如 `redis://redis.traffic.svc.cluster.local:6379/1`。建议**独立 logical DB**，避免与 Celery 等混用。未设置时 Redis 模式不可用。 |
| `TRAFFIC_INGEST_TOKEN` | `POST /api/traffic/ingest` 的 Bearer 密钥；**未设置则接入接口返回 503**。 |
| `TRAFFIC_INGEST_MAX_BODY_LINES` | 可选，单次请求最大行数（默认 `20000`，上限 `100000`）。 |
| `TRAFFIC_DASHBOARD_MAX_TAIL_BYTES` | （可选）**文件模式**：大盘单次尾部读取字节上限（默认 `4MB`），与后台「尾部读取字节」取较小值。 |
| `REDIS_URL` | 若未设 `TRAFFIC_REDIS_URL`，会回退读取（兼容其他组件）。 |

示例（文件模式 + GeoIP）：

```bash
export TRAFFIC_NGINX_ACCESS_LOG=/var/log/nginx/access.json.log
export TRAFFIC_GEOIP_DB=/usr/share/GeoIP/GeoLite2-City.mmdb
```

示例（K8s Shark + 远程 Nginx）：

```bash
export TRAFFIC_REDIS_URL=redis://redis:6379/2
export TRAFFIC_INGEST_TOKEN="$(openssl rand -hex 24)"
export TRAFFIC_GEOIP_DB=/data/geoip/GeoLite2-City.mmdb
```

---

## 4. 后台配置（三种方式任选/组合）

### 4.1 Django Admin

1. 进入 `/admin/`，打开 **Traffic Dashboard Config**（单例）。
2. 填写：
   - **Access log mode**：`file` = 读本地路径；`redis` = 从 Redis List 读入站日志（需 `TRAFFIC_REDIS_URL`）。
   - **Access log path**：仅 file 模式；与 `TRAFFIC_NGINX_ACCESS_LOG` 相同含义。
   - **Redis log key** / **Redis max lines**：仅 redis 模式；List 的 key 与最大保留行数（超出则丢弃最旧）。
   - **Dashboard fetch max lines**：仅 redis 模式意义最大；大盘每次从 List 尾部读取的最大行数（与 ingest 保留量 **Redis max lines** 独立）。
   - **Log format**：`json`（推荐）或 `combined`。
   - **Max tail bytes**：仅 file 模式；每次 API 从文件**末尾**读取的最大字节数（默认 5MB）。
   - **GeoIP db path**：MaxMind **.mmdb** 城市库路径（Pod 内可读路径）。
   - **Use inspection prometheus**：勾选后 Blackbox 使用 **系统巡检**里的 Prometheus。
   - **Prometheus url override** / **Blackbox promql**：同前。

### 4.2 页面内「设置」按钮

登录后 **Traffic Dashboard** → 右上角齿轮 → 与 Admin 一致，含采集模式与 Redis 字段；`GET/POST /api/traffic/config`（需登录）。

### 4.3 仅环境变量

- **文件模式**：至少配置路径（后台或 `TRAFFIC_NGINX_ACCESS_LOG`）。
- **Redis 模式**：必须 `TRAFFIC_REDIS_URL` + `TRAFFIC_INGEST_TOKEN`，并在后台选 redis 模式。
- GeoIP：可只设 `TRAFFIC_GEOIP_DB` 或后台 **MaxMind mmdb**。

---

## 5. Nginx 日志格式（强烈推荐 JSON）

在 `http` 或 `server` 中定义：

```nginx
log_format access_json escape=json
  '{'
    '"time_local":"$time_local",'
    '"msec":"$msec",'
    '"remote_addr":"$remote_addr",'
    '"request_uri":"$request_uri",'
    '"status":$status,'
    '"request_time":"$request_time",'
    '"http_user_agent":"$http_user_agent"'
  '}';

access_log /var/log/nginx/access.json.log access_json;
```

说明：

- **`request_time`**：Nginx 秒数（浮点），后端会转为毫秒参与 P50/P95/P99。
- **时间轴按「请求发生时间」**：优先 **`$msec`**（Unix 秒，推荐），其次 **`time_local`**（英文月缩写）、**`$time_iso8601`**（可增字段 `time_iso8601`）。若都解析失败，会退化为 **推送/查询时刻**，图表会挤成一条竖线；服务器 `LC_TIME` 非英文时，旧版仅靠 `strptime` 解析 `time_local` 易失败，请升级 Shark 或务必带 **`msec`**。
- **真实客户端 IP**：若经 CDN/反代，请使用 `$http_x_forwarded_for` 或 realip 模块，保证 JSON 里 `remote_addr` 为客户端 IP（或增加 `real_ip_header` 后仍用 `$remote_addr`）。

**combined 模式**：后端使用简化正则解析，**无 `request_time` 时延迟为 0**，仅建议过渡使用。

---

## 5.1 独立 Nginx + Shark 在 K8s（Redis 推送）操作步骤

1. **集群内部署 Redis**（或用托管 Redis），记下连接串，例如：`redis://redis.traffic.svc:6379/2`。
2. **生成 ingest 密钥**：`openssl rand -hex 24`，写入 K8s Secret，例如 `traffic-ingest` 的 `token` 键。
3. **Shark Deployment** 增加环境变量：`TRAFFIC_REDIS_URL`、`TRAFFIC_INGEST_TOKEN`（及可选 `TRAFFIC_GEOIP_DB`）；确保 Pod 能连 Redis。
4. **MaxMind .mmdb**：将 `GeoLite2-City.mmdb` 或 `GeoIP2-City.mmdb` 放入 **PVC / ConfigMap（注意大小限制）/ initContainer 下载** 等，挂载到 Pod 内路径，与 `TRAFFIC_GEOIP_DB` 一致。
5. 登录 Shark → Traffic 设置 → **采集模式** 选 **远程推送 → Redis**，保存（或与 Admin 配置 `access_log_mode=redis`）。
6. **Nginx 所在机器**（可出网到 Shark Ingress / LB）定时或近实时推送，**每行一条 JSON**，与 §5 格式一致：

   ```bash
   TOKEN="<TRAFFIC_INGEST_TOKEN>"
   SHARK="https://<your-shark-host>/api/traffic/ingest"
   tail -n 1000 /var/log/nginx/access.json.log | curl -sS -X POST "$SHARK" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: text/plain; charset=utf-8" \
     --data-binary @-
   ```

   或使用 JSON 体（适合批量脚本）：

   ```bash
   curl -sS -X POST "$SHARK" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d "{\"lines\": [\"{\\\"msec\\\":\\\"1730000000.000\\\",...}\"]}"
   ```

7. 打开 `/dashboard` 确认黄条消失、图表有数据；若 Geo 仍为 Unknown，检查 mmdb 路径与公网 IP。

**说明**：ingest 接口**不校验登录 Cookie**，仅校验 `Bearer`；务必 TLS + 强随机 token。单次请求行数受 `TRAFFIC_INGEST_MAX_BODY_LINES` 限制，超高 QPS 请提高推送频率或增大该值。

**K8s 一键清单（GeoIP PVC、Redis Job、ClickHouse 等）**：见 **[deployment/README.md](./deployment/README.md)** 中「Traffic 中间件（Kubernetes）」；Filebeat 推送见 [FILEBEAT_NGINX_TRAFFIC.md](./FILEBEAT_NGINX_TRAFFIC.md)。

---

## 6. Prometheus Blackbox Exporter

1. 在 Prometheus 中抓取 Blackbox 指标（`probe_success`、`probe_duration_seconds` 等）。
2. 在 **系统巡检**（Inspection）配置中填写 **Prometheus URL**（例如 `http://prometheus:9090`），并勾选 Traffic 配置中的 **使用巡检 Prometheus**。
3. 若 Blackbox 使用非默认标签，可在 Traffic 配置中设置 **Blackbox promql**，例如：

   ```promql
   probe_success{job="blackbox"}
   ```

4. 可用性 KPI：对当前查询结果中 `probe_success==1` 的比例；无目标时前端显示 `—`。

---

## 7. MaxMind GeoIP（.mmdb 城市库）

1. 在 [MaxMind](https://www.maxmind.com/) 注册账号；下载 **GeoLite2-City**（免费）或 **GeoIP2-City**（付费）的 **`.mmdb`** 文件（二者均为 MaxMind 二进制格式）。
2. **K8s**：将 `.mmdb` 挂入 Shark Pod（PVC、Secret 单文件、或 initContainer 拉取到 `emptyDir`），路径例如 `/data/geoip/GeoLite2-City.mmdb`。
3. 设置 **`TRAFFIC_GEOIP_DB`** 或后台 **MaxMind mmdb** 为该绝对路径；确保运行 Gunicorn 的用户可读。
4. Python 依赖（已在 `requirements.txt`）：`pip install geoip2`。

未配置 mmdb 时：国家多为 `Unknown`（`??`）；内网 IP 可能显示为 `LAN`。

---

## 8. REST API

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/traffic/snapshot?range=24h&source=all` | 登录 | **推荐**：一次返回 `overview` / `timeseries` / `geo` / `top_*` / `meta`，只读 Redis·解析·GeoIP 一遍，避免多接口并行打满服务 |
| GET | `/api/traffic/overview?range=24h` | 登录 | KPI + spark + Blackbox；`log_configured` 在 file/redis 就绪时为 true |
| GET | `/api/traffic/timeseries?range=24h` | 登录 | QPS、请求量、延迟、状态码 |
| GET | `/api/traffic/geo?range=24h&granularity=country` | 登录 | 国家；`granularity=province&country=CN` 省份 |
| GET | `/api/traffic/top?range=24h&type=paths&limit=10` | 登录 | `paths` / `slow` / `status` / `ip` |
| GET | `/api/traffic/blackbox` | 登录 | Blackbox 摘要 |
| GET | `/api/traffic/jaeger/traces` | 登录 | 模拟数据 |
| GET/POST | `/api/traffic/config` | 登录 | 读/写配置（含 `access_log_mode`、`redis_*`、`redis_env_configured` 只读） |
| POST | `/api/traffic/ingest` | **`Authorization: Bearer <TRAFFIC_INGEST_TOKEN>`** | 写入 Redis List；Body：`text/plain` 多行 NDJSON，或 JSON `{"lines":["..."]}` |

`range`：`1h` | `6h` | `24h` | `7d` | `30d`。

---

## 9. 权限与菜单

- 路由仍为 `/dashboard`，权限仍为 **`view_dashboard`**。
- 侧栏名称：**Traffic Dashboard**，图标 **DataLine**。

---

## 10. 性能与限制（当前实现）

- **大盘接口**：前端默认走 **`/api/traffic/snapshot`**；单请求超时可在前端设为 120s。旧版多路 `overview`+`timeseries`+… 并行时，易重复拉 Redis、重复 GeoIP，易触发 **网关 503/超时**。
- **大盘抽样**：**Redis 模式**下，每次加载大盘从 List 尾部读取的行数在 **Traffic 设置**（或 Admin）中配置 **`dashboard_fetch_max_lines`**（默认 35000，上限 500000）；ingest 保留量仍由 **`redis_max_lines`** 决定。可选环境变量 **`TRAFFIC_DASHBOARD_MAX_TAIL_BYTES`** 限制文件模式尾部字节。
- **文件模式**：每次请求读日志尾部，适合中小流量；超高 QPS 建议 Vector/ClickHouse 等。
- **Redis 模式**：ingest 为 **RPUSH + LTRIM**。
- 世界地图依赖外网 CDN；内网请自建 `world.json` URL（见 `frontend/src/views/Dashboard/Index.vue`）。
- 3D 地球贴图来自 `echarts.apache.org`；离线可换本地 URL。

---

## 11. 故障排查

| 现象 | 处理 |
|------|------|
| 顶部黄条提示未配置日志 | **file**：配置路径且进程可读。**redis**：设置 `TRAFFIC_REDIS_URL` 且后台为 redis 模式；并已 POST ingest 写入数据。 |
| 图表全空 | file：调大 **max_tail_bytes**、核对时间与 range。redis：检查 token、ingest 是否 200、Redis key 是否与后台一致。 |
| ingest 返回 503 | 未设置 `TRAFFIC_INGEST_TOKEN` 或未设置 `TRAFFIC_REDIS_URL`。 |
| ingest 返回 403 | `Authorization` 头不是 `Bearer <正确 token>`。 |
| Geo 全为 Unknown | 检查 **MaxMind .mmdb** 路径、`pip install geoip2`、公网 IP。 |
| Blackbox 无数据 | 检查 Prometheus URL、网络连通、`probe_success` 是否有数据；自定义 **Blackbox promql**。 |
| 3D 地球不显示 | 浏览器控制台是否加载 `echarts-gl`；贴图 URL 是否被防火墙拦截。 |

---

## 12. 后续扩展（Jaeger）

- 实现 Jaeger Query HTTP 客户端后，新增视图函数替换 `traffic_jaeger_traces_mock`，保持响应字段：`trace_id`、`root_service`、`span_count`、`duration_ms`、`started_at`、`status`。
- 服务拓扑 Tab 左侧替换为依赖图组件数据源即可。
