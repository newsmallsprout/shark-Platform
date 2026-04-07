# go-agent

**AIOps Platform** 边缘探针：主机心跳 + **Playbook 轮询执行**（中心下发的 shell 脚本）。

**与 Kubernetes 的关系**：业务运行在 Pod 内时，一般**不需要**在每个容器里跑本探针；指标交给 Prometheus，日志由平台经 **Kubernetes API** 或集中日志系统获取。本程序适用于 **裸金属/VM**、**需要宿主机视角的 DaemonSet**，或 **集群内专用「执行器」Deployment**（用固定 `SHARK_AIOPS_NODE_ID` 轮询 Playbook 并执行 `kubectl` 等）。

## Environment

| Variable | Description |
|----------|-------------|
| `SHARK_AIOPS_CENTER_URL` | Base URL (no trailing slash) |
| `SHARK_AIOPS_EDGE_TOKEN` | Must match center `SHARK_EDGE_TOKEN` (header `X-Shark-Edge-Token`) |
| `SHARK_AIOPS_NODE_ID` | Stable node id; must align with center `AIOPS_DEFAULT_PLAYBOOK_NODE` |
| `SHARK_AIOPS_INTERVAL` | Heartbeat interval, default `30s` |
| `SHARK_AIOPS_PLAYBOOK_POLL` | Playbook poll interval, default `5s` |

## Build

```bash
cd go-agent
go mod tidy
go build -o aiops-agent .
```

## Run

```bash
export SHARK_AIOPS_CENTER_URL=https://your-center
export SHARK_AIOPS_EDGE_TOKEN=your-shared-secret
export SHARK_AIOPS_NODE_ID=prod-edge-1
./aiops-agent
```

Playbooks are executed as `/bin/sh -c <script>` with an 8-minute timeout; results are POSTed to `/api/edge/playbooks/<id>/complete`.
