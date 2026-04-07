# go-agent

**AIOps Platform** 边缘探针：主机心跳 + **Playbook 轮询执行**（中心下发的 shell 脚本）。

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
