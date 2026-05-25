# Shark Platform

[![Python](https://img.shields.io/badge/python-3.9%2B-green.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-4.2-green.svg)](https://www.djangoproject.com/)
[![Vue](https://img.shields.io/badge/Vue-3.0-green.svg)](https://vuejs.org/)
[![Element Plus](https://img.shields.io/badge/Element_Plus-2.0-blue.svg)](https://element-plus.org/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-blue.svg)](https://www.docker.com/)

综合运维管理平台（Django REST Framework + Vue 3），包含：

- MySQL → MongoDB 同步（全量 + Binlog 增量）
- K8s 日志监控与 Slack 告警（多 namespace）
- AIOps（接收 Alertmanager webhook、自动分析与展示）
- 巡检（定时任务/报告）
- 排班（值班表 + 电话告警/回调）
- 服务器部署（批量执行/分发）

生产部署与所有人工操作请以 [K8S_RBAC_GUIDE.md](file:///Users/chenshun/Desktop/mysql_to_mongo/K8S_RBAC_GUIDE.md) 为准（包含 RBAC、PVC/gp3、Ingress、生产 kubeconfig、上线后初始化）。本文 README 作为“项目总览 + 快速入口 + 常见运维”。

---

## 目录

- 快速开始（Compose / K8s / 本地开发）
- 配置清单（环境变量 / Web UI 配置）
- 常用运维（排班去重、查看日志、升级）
- 常见问题（鉴权/告警/@人/排班重复）
- 项目结构

---

## 快速开始

### 方式一：Docker Compose（本地/测试推荐）

1) 准备挂载目录（否则 MySQL 容器可能因挂载失败启动异常）

```bash
mkdir -p mysql_conf mysql_init
```

2) 启动

```bash
docker-compose up -d --build
```

3) 访问

- Web：`http://localhost:8000/`
- 默认账号：`admin`
- 默认密码：`admin`（首次启动自动创建，务必改密）

说明：
- `docker-compose.yml` 里默认挂载 `./mysql_conf/my.cnf` 和 `./mysql_init/`，可以按需要补充初始化脚本/配置。

### 方式二：Kubernetes（生产推荐）

- **生产部署**：直接按 [K8S_RBAC_GUIDE.md](file:///Users/chenshun/Desktop/mysql_to_mongo/K8S_RBAC_GUIDE.md) 的“一体 YAML + 傻瓜式步骤”执行（包含 RBAC、PVC/gp3、Ingress、生产 kubeconfig、上线后初始化）。
- **示例清单试跑**：`k8s/` 目录可快速验证流程（注意是示例值，需要自行改 namespace/镜像/域名）。

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/shark-platform.yaml
```

说明：
- 仓库里没有 `k8s/secrets.yaml`，Secret 已合并在 [k8s/configmap.yaml](file:///Users/chenshun/Desktop/mysql_to_mongo/k8s/configmap.yaml)。

### 方式三：本地开发

后端：

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

---

## 配置清单

### 环境变量（K8s ConfigMap / Compose environment）

- `DJANGO_SECRET_KEY`：必须设置（生产请随机生成后 base64）
- `DEBUG`：`False/True`
- `ALLOWED_HOSTS`：例如 `*` 或指定域名
- `CSRF_TRUSTED_ORIGINS`：逗号分隔 URL 列表（不要带反引号/多余空格）
- `PUBLIC_URL`：用于 Slack deep link（例如 `https://ubest-ops.prd.exc888.org`）
- `DEFAULT_MONITOR_NAMESPACE`：日志监控默认 namespace（可选）

### Web UI（上线后必配）

1) 修改默认管理员密码（首次启动默认 `admin/admin`）。

2) Schedules → Phone Alert Config

- External 回调只发送两种状态：`PROCESSING` / `COMPLETED`
- Oncall Slack Mapping：配置“姓名 → Slack 用户 ID（Uxxxx）”，系统会转成 `<@Uxxxx>` 真正@人
- 同一时间段多个值班人员会合并为多个 `<@U...>` 一起发送

3) Log Monitor

- 同集群部署：任务 kubeconfig 留空即可（走 in-cluster config），但 RBAC 必须允许 `pods`/`pods/log`
- 多 namespace：任务支持逗号分隔

---

## 常用运维

### 查看应用日志（K8s）

```bash
kubectl logs -f -n middleware-system deploy/shark-platform
```

### 清理历史重复排班（只需一次）

排班接口已做幂等 upsert，但历史重复数据需要手动清理一次：

```bash
kubectl exec -n middleware-system deploy/shark-platform -- python3 manage.py dedup_schedules
kubectl exec -n middleware-system deploy/shark-platform -- python3 manage.py dedup_schedules --apply
```

可选按日期范围：

```bash
kubectl exec -n middleware-system deploy/shark-platform -- \
  python3 manage.py dedup_schedules --from-date 2026-02-01 --to-date 2026-02-10 --apply
```

---

## 常见问题

- **排班重复推送导致列表越变越多**：已修复为幂等写入；历史数据用 `dedup_schedules --apply` 清理一次。
- **Slack 没有真实@到人**：必须使用 `<@Uxxxx>`；请在 Phone Alert Config 配 Oncall Slack Mapping（姓名→U-id）。
- **外部回调看着 200 但业务提示 unauthorized**：对方可能用 JSON `code` 表示错误；系统已记录 `app_code/effective_status` 便于排查。

---

## 项目结构

```text
mysql_to_mongo/
├── ai_ops/                  # AIOps（webhook、事件、分析报告）
├── deploy/                  # 服务器部署
├── inspection/              # 巡检
├── monitor/                 # K8s 日志监控
├── schedules/               # 排班 + 电话告警
├── tasks/                   # MySQL → Mongo 同步引擎
├── frontend/                # Vue 3 前端
├── k8s/                     # 示例 K8s 清单（生产以 K8S_RBAC_GUIDE 为准）
├── entrypoint.sh            # 容器启动脚本（自动 migrate + 默认 admin）
└── manage.py
```

---

## 许可证

本项目仅供学习与研究使用。
