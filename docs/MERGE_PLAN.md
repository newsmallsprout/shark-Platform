# 三项目合并方案 (Merge Plan)

> pentest-agent (前端) + pentestagent-backend (后端) + shark-Platform (主) → 单一平台
> 工作区: `~/Desktop/shark-platform-merged/` (clone，分支 `merge-pentest`，原三项目零改动)

---

## 1. 目标

以 shark-Platform 的 Django 框架为底座，把 pentest 的渗透测试后端能力作为「较新功能」合并进来，前端整体换成 pentest 的 Next.js（全面覆盖 shark 原有页面），最终一个平台、一个代码库、一套认证。

---

## 2. 合并后架构

```
┌─────────────────────────────────────────────────────────┐
│ 前端: Next.js 16 + shadcn (来自 pentest-agent)           │
│   /login /dashboard /tasks /platforms /knowledge         │
│   /reports /settings  (pentest 原有 7 页)                │
│   + /sync /logs /schedules /deploy /db /traffic /ops     │
│     /permissions ...  (shark 13 个 Vue 页面迁移过来)      │
└────────────────────────┬────────────────────────────────┘
                         │ JWT (Bearer) + REST + WebSocket
┌────────────────────────▼────────────────────────────────┐
│ 后端: Django 4.2 + DRF (shark 框架)                       │
│  ┌ 原有 app ──────────────────────────────────────────┐  │
│  │ api(core auth/users/roles/perms) deploy monitor     │  │
│  │ inspection ops_tickets tasks schedules ai_ops       │  │
│  │ db_manager traffic                                  │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌ 新增 app: security (pentest 后端功能移植) ──────────┐  │
│  │ models: SecurityTask ScanSession ScanTool Asset     │  │
│  │         Vulnerability SecurityReport Knowledge*     │  │
│  │ views: tasks scans reports knowledge guided auth    │  │
│  │ agents: auto_scan(子域/指纹/扫描/分析) guided        │  │
│  │ tools: nmap nuclei subfinder httpx                  │  │
│  │ websocket: 扫描实时流 (Django Channels)             │  │
│  └────────────────────────────────────────────────────┘  │
│  Celery (shark 已有 celery.py) → 扫描 worker             │
│  DB: SQLite(dev) / PostgreSQL(prod)，JSONField 兼容     │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 合并后目录结构（关键）

```
shark-platform-merged/
├── shark_platform/          # Django settings/urls (shark)
├── api/ core/ deploy/ monitor/ inspection/ ops_tickets/
│   tasks/ schedules/ ai_ops/ db_manager/ traffic/        # shark 原有，不动
├── security/                # ★ 新增：pentest 后端功能移植
│   ├── models.py            #   SQLAlchemy → Django 模型
│   ├── serializers.py       #   Pydantic schema → DRF serializer
│   ├── views.py urls.py     #   FastAPI router → DRF view
│   ├── services/            #   auth/task/scan/report 业务逻辑
│   ├── agents/              #   auto_scan / guided (LangGraph)
│   ├── tools/               #   nmap nuclei subfinder httpx
│   └── consumers.py         #   WebSocket (扫描流)
├── frontend/                # ★ 替换：pentest Next.js 前端
│   └── src/app/...          #   pentest 7页 + shark 13页迁移
└── docs/MERGE_PLAN.md
```

---

## 4. 后端合并映射表 (pentest FastAPI → Django)

| pentest (FastAPI) | → Django (security app) | 说明 |
|---|---|---|
| `models/user.py` | Django 自带 User + Group | 用户走 Django auth，不做自定义 User |
| `models/task.py` | `SecurityTask` | platform/platform_task_id/mode/status/target/scope(JSON)/progress/vuln_count(JSON) |
| `models/scan.py` | `ScanSession` `ScanTool` `Asset` | 3 张表 |
| `models/vulnerability.py` | `Vulnerability` | severity/type/cve/cvss/proof/steps/recommendation 等 |
| `models/report.py` | `SecurityReport` | 报告表 |
| `models/knowledge.py` | `KnowledgeEntry` | 知识库条目 |
| `models/chat.py` | `GuidedSession`/`GuidedMessage` | 引导模式会话 |
| `schemas/*.py` | `serializers.py` | Pydantic → DRF |
| `api/v1/routers/auth.py` | 并入 `api`(JWT) | JWT 认证(见 §5) |
| `api/v1/routers/tasks.py` | `security/views.py` | 任务 CRUD + start |
| `api/v1/routers/scans.py` | `security/views.py` | 扫描会话/资产/漏洞 |
| `api/v1/routers/reports.py` | `security/views.py` | 报告生成/提交 |
| `api/v1/routers/knowledge.py` | `security/views.py` | 知识库 |
| `api/v1/routers/guided.py` | `security/views.py` | 引导模式(SSE→DRF流式) |
| `api/v1/routers/websocket.py` | `security/consumers.py` | Django Channels |
| `agents/auto_scan/*` | `security/agents/auto_scan/` | 基本保留(改同步/异步适配) |
| `agents/guided/*` | `security/agents/guided/` | 保留 |
| `tools/*` | `security/tools/` | nmap/nuclei/subfinder/httpx 原样复用 |
| `services/*` | `security/services/` | 业务逻辑平移 |
| `core/security.py`(JWT) | `api/jwt_auth.py` | 用 DRF + PyJWT(或 djangorestframework-simplejwt) |
| `workers/*`(Celery) | shark 已有 `celery.py` | 扫描任务注册到 shark Celery |

**原则**：逻辑平移、不重写；能复用开源库就用（DRF、simplejwt、channels、celery），不自己造轮子。

**冲突处理（pentest 优先）**：字段命名/状态枚举/接口语义冲突时，一律以 pentest 为准；shark 已有同名 `tasks` app（数据同步），pentest 的扫描任务独立成 `security` app 的 `SecurityTask`，避免和 shark 的 `tasks.SyncTask` 冲突。

---

## 5. 权限统一方案

**结论**：认证层用 pentest 的 JWT（更好、无状态、适配前后端分离），授权层保留并完善 shark 的 RBAC。

| 层面 | 方案 | 依据 |
|---|---|---|
| 认证 | JWT Bearer（pentest 方案，替换 shark 的 session/basic） | "pentest 权限更好" |
| 密码哈希 | bcrypt（pentest 用 bcrypt） | 复用 pentest security.py |
| 用户模型 | Django 内置 User | 不重复造轮子 |
| 角色 | Django Group（Admin/User/...） | shark 现有 |
| 细粒度权限 | shark 现有 24 个 codename 全保留 + 新增 pentest 权限 | "完善 shark 权限管理" |
| 权限校验 | DRF `permission_classes`（重构 shark 的 path 匹配 HasRolePermission → 更干净的 permission 类） | 完善 |
| 前端控制 | Next.js 里 `hasPermission()`/`viewPerm` 路由守卫 | pentest 前端统一实现 |

**新增权限 codename**（pentest 功能相关）：
`view_security_tasks` `manage_security_tasks` `run_security_scan` `view_security_reports` `view_security_knowledge` `manage_security_knowledge`

**/me 接口**：返回 `{id, username, email, is_staff, is_superuser, groups, permissions[]}`（shark 现有格式，前端复用）。

---

## 6. 前端迁移方案 (Vue 13页 → Next.js)

pentest Next.js 前端作为唯一前端，shark 的 Vue 页面逐个用 Next.js + shadcn 重写：

| shark Vue 页面 | 路由路径 | Next.js 目标 |
|---|---|---|
| Login.vue | /login | 复用 pentest /login（接 Django JWT） |
| Dashboard/Index.vue (Traffic 大盘) | /traffic | /traffic |
| Tasks/Index.vue (数据同步) | /tasks | /sync（避免与 pentest /tasks 冲突） |
| Tasks/Create.vue | /tasks/create | /sync/new |
| Tasks/Logs.vue | /tasks/logs/:id | /sync/:id/logs |
| Connections/Index.vue | /connections | /connections |
| LogMonitor/Index.vue | /logs | /logs |
| Schedules/Index.vue | /schedules | /schedules |
| System/OpsTickets.vue | /system/tickets | /ops-tickets |
| System/Index.vue | /system | /system |
| Permissions/Index.vue | /permissions | /permissions ★完善 |
| DatabaseManager/Index.vue | /db | /db |
| DatabaseManagerPro/* | /db/* | /db（合并） |
| Deploy/Index.vue + Config.vue | /deploy | /deploy |

pentest 原有 7 页保留：`/login /dashboard /tasks /platforms /knowledge /reports /settings`（dashboard 与 traffic 分开，pentest 的 dashboard 是渗透总览，shark 的 traffic 大盘迁到 /traffic）。

侧边栏导航按权限 codename 动态渲染（`viewPerm`），无权限项隐藏 —— 复用 pentest 的 layout + 权限守卫。

---

## 7. 数据库决策

- shark 默认 SQLite(dev)、生产 PostgreSQL；pentest 用 PostgreSQL(JSONB/ARRAY/UUID)。
- **方案**：Django 模型统一用 `JSONField`(替代 JSONB/ARRAY) + `UUIDField` + `BigAutoField`，实现 SQLite 与 PostgreSQL 双兼容，**不强制**改生产库。
- 向量库 Qdrant → **待确认**：推荐替换为 pgvector（平台统一），或先保持简单（知识库检索用精确匹配+关键词，后续再上向量）。

---

## 8. 分阶段执行计划

- [x] 阶段 0：调研 + 工作区 + 本文档
- [ ] 阶段 1：后端 security app 骨架 + 模型 + 迁移
- [ ] 阶段 2：JWT 认证 + 权限统一（settings/urls/api/jwt）
- [ ] 阶段 3：port services/tools/agents/views/urls（tasks/scans/reports/knowledge/guided）
- [ ] 阶段 4：WebSocket(Channels) + Celery 扫描 worker
- [ ] 阶段 5：前端 pentest 接入 + JWT 对接 + 权限守卫
- [ ] 阶段 6：shark 13 页 → Next.js 迁移 + 权限管理 UI 完善
- [ ] 阶段 7：构建验证（migrate/run + next build）

---

## 9. 待确认点（一次性列出，非阻塞，可先按推荐值执行）

1. 外部平台连接器 `butian.py`/`vulbox.py`：默认**保留但低优先级**（需第三方凭证，不影响主流程）。
2. 向量库：默认**先不引 pgvector**，知识库检索用 DB 精确+关键词（最简，符合"不做非必要复杂度"）；需要语义检索时再加。
3. WebSocket：默认用 **Django Channels**（shark 框架内统一），不保留独立 FastAPI 进程。
