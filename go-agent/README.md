# go-agent

Edge **system probe** for **shark-aiops**. Periodically POSTs a JSON snapshot to the control plane.

## Environment

| Variable | Description |
|----------|-------------|
| `SHARK_AIOPS_CENTER_URL` | Base URL (no trailing slash), e.g. `https://ops.example.com` |
| `SHARK_AIOPS_EDGE_TOKEN` | Must match center `SHARK_EDGE_TOKEN` |
| `SHARK_AIOPS_NODE_ID` | Optional stable node id (default: host id) |
| `SHARK_AIOPS_INTERVAL` | Go duration, default `30s` |

## Build

```bash
cd go-agent
go mod tidy
go build -o shark-agent .
```

## Run

```bash
export SHARK_AIOPS_CENTER_URL=https://your-center
export SHARK_AIOPS_EDGE_TOKEN=your-shared-secret
./shark-agent
```

Extend `collect()` in `main.go` to add custom metrics or pull lists from a future PML/config endpoint.
