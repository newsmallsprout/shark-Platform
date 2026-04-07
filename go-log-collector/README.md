# go-log-collector

Edge **log shipper** for **shark-aiops**. Batches text lines and POSTs JSON to the control plane ingest endpoint.

## Environment

| Variable | Description |
|----------|-------------|
| `SHARK_AIOPS_CENTER_URL` | Base URL (no trailing slash) |
| `SHARK_AIOPS_EDGE_TOKEN` | Must match center `SHARK_EDGE_TOKEN` |
| `SHARK_AIOPS_LOG_SOURCE` | Logical source label (default `edge`) |
| `SHARK_AIOPS_LOG_PATHS` | Comma-separated file paths; if empty, reads **stdin** |

## Build

```bash
cd go-log-collector
go build -o shark-log-collector .
```

## Examples

```bash
# Tail a file
export SHARK_AIOPS_EDGE_TOKEN=secret
export SHARK_AIOPS_LOG_PATHS=/var/log/nginx/access.json.log
./shark-log-collector
```

```bash
tail -F /var/log/app.log | SHARK_AIOPS_EDGE_TOKEN=secret ./shark-log-collector
```

Center accepts payloads shaped as `{ "source": "...", "lines": ["...", ...] }` at `POST /api/edge/logs`.
