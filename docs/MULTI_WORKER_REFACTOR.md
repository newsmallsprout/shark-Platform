# Shark Platform：Gunicorn 多 Worker 与同步任务改造说明

本文档描述为何默认使用单 Worker、如何安全扩展到多 Worker，以及环境变量与进程拓扑。**不包含排期或时间节点。**

## 1. 背景与约束

- **TaskManager** 在进程内维护 `_tasks: Dict[str, SyncWorker]`，仅当前进程内的线程能直接驱动 `SyncWorker.run()`。
- **Turbo 模式** 由 K8s Pod 执行，状态以数据库与 K8s 为主，不依赖本机内存线程；但 **启动/恢复 Turbo 任务** 时若多个进程同时调用，可能重复创建 Pod。
- **Normal 模式** 依赖本进程内的 `SyncWorker` 线程；多 Worker 下若仅在「某一个」Worker 上拉起线程，则随机打到其他 Worker 的 HTTP 请求看不到本机 `_tasks`，且从 API 在未持有线程的 Worker 上再次 `start` 可能重复起线程。

结论：

- `GUNICORN_WORKERS=1` + 提高 `GUNICORN_THREADS` 仍是**最简单、默认安全**的部署方式。
- 需要 **Worker 数 > 1** 时：**Normal 同步必须外置到单独进程**（Supervisor），Web 进程只写数据库与配置，由 Supervisor 单进程持有 `_tasks` 并跑 `SyncWorker`。

## 2. 阶段划分

### 阶段 A：恢复（restore）全局单点

- 应用启动时 `restore_from_disk` 会为 `status=running` 的任务重新执行 `start` 或等价逻辑；多进程下必须保证 **全集群/全节点内只有一次** 真正执行恢复（至少避免重复起 Turbo Pod、重复写状态）。
- **实现**：
  - 若配置了 `TRAFFIC_REDIS_URL` 或 `REDIS_URL`：使用 Redis `SET key NX` + TTL 作为 **跨 Pod** 的 Leader 选举。
  - 否则：使用 `state/sync_restore.lock` 的 **`fcntl` 非阻塞文件锁**，适用于 **同一节点** 上多个 Gunicorn Worker。
- Web 在 **inprocess** 模式下仍通过 `run_restore_once(...)` 调用上述逻辑；仅当选上 Leader 的进程执行完整恢复。

### 阶段 B：Turbo 与列表 API

- Turbo 任务状态继续以 **DB + K8s** 为主；`get_all_tasks_status` / `get_task_status` 在本地无 `_tasks` 项时读库并查询 Pod 阶段，与多 Worker 兼容。
- **注意**：多 Worker 下从 API **新发起** Turbo `start` 若未做分布式互斥，理论上仍可能重复调 `start_task_pods`；生产建议由运维侧保证并发或后续再加任务级分布式锁（非本文档必须项）。

### 阶段 C：Normal 同步外置（Supervisor）

- 环境变量：`SHARK_SYNC_NORMAL_MODE`
  - `inprocess`（默认）：与历史行为一致，Web 进程内起线程；**应与 `GUNICORN_WORKERS=1` 同用**。
  - `supervisor`：Web 上 `start` / API 仅更新 DB 与配置，**不**在本进程内起 `SyncWorker`；由 **`sync_supervisor` 管理命令** 在 **单进程** 内轮询 `running` 且非 Turbo 的任务并启动线程；根据 DB 中 `status != running` 停止本进程内对应 Worker。
- Supervisor 进程启动时设置 `SHARK_SYNC_SUPERVISOR_PROCESS=1`，并执行完整 `restore_from_disk`（含 Normal 的线程恢复，见下）。
- Web 在 `SHARK_SYNC_NORMAL_MODE=supervisor` 且非 Supervisor 进程时：**不**在 `AppConfig.ready` 中执行恢复，避免与 Supervisor 重复争抢；由 Supervisor 负责恢复。

### restore 在 Supervisor 模式下对 Normal 的语义

- Web `start(normal)` 不写线程；若直接调用通用 `start()` 做恢复会导致无法起线程。
- 因此 Supervisor 恢复路径对 **非 Turbo** 任务调用 `_start_inprocess_worker(cfg)`：仅在本进程注册 `SyncWorker` 并起线程，不重复写 DB。

## 3. 环境变量一览

| 变量 | 含义 |
|------|------|
| `GUNICORN_WORKERS` | Gunicorn worker 数量，默认 `1`。 |
| `GUNICORN_THREADS` | 每 worker 线程数，默认 `4`。 |
| `SHARK_SYNC_NORMAL_MODE` | `inprocess` / `supervisor`，默认 `inprocess`。 |
| `SHARK_SYNC_SUPERVISOR_PROCESS` | 由 `manage.py sync_supervisor` 置为 `1`，勿在 Web 上手动设。 |
| `SHARK_SYNC_SUPERVISOR_POLL_SEC` | Supervisor 轮询秒数，默认 `2`。 |
| `SHARK_SYNC_RESTORE_LOCK_KEY` | Redis 恢复锁键，默认 `shark:sync:restore_lock`。 |
| `REDIS_URL` / `TRAFFIC_REDIS_URL` | 存在时用于跨节点恢复 Leader 选举。 |

## 4. 推荐拓扑

- **单机 / 小流量**：`GUNICORN_WORKERS=1`，`SHARK_SYNC_NORMAL_MODE=inprocess`，调高 `GUNICORN_THREADS`。
- **多 Worker Web + Normal 同步**：同一镜像内或 Sidecar：`SHARK_SYNC_NORMAL_MODE=supervisor`，`entrypoint` 拉起 `sync_supervisor` 后置背景运行；Web 设 `GUNICORN_WORKERS>1`；跨多副本时需 **Redis** 以保证恢复 Leader 与 Traffic 等一致。
- **仅 Turbo、无 Normal**：可考虑仍为 `inprocess` + 多 Worker，但恢复依赖 Redis 或共盘文件锁；建议为 Turbo 配置 Redis URL。

## 5. 与 Traffic / 快照等改造的关系

Traffic 侧滚动聚合、快照缓存、Redis 硬顶等与 Web Worker 数正交；多 Worker 时同一请求可能由不同进程计算快照，依赖 **共享 Redis/DB/物化视图** 可避免不一致。本文档范围内的同步任务改造不替代 Traffic 缓存策略，但可同时部署。
