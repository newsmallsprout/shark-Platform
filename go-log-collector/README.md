# go-log-collector

**AIOps Platform** 轻量日志上报：可选 **关键行过滤**、**边缘正则脱敏**，批量 POST 至中心。

**与 Kubernetes 的关系**：Pod 标准输出/文件日志在集群内通常应由 **Loki、EFK、或中心服务拉取 Pod 日志** 完成，不必再经 sidecar 重复推送。本采集器更适合 **集群外节点**、**无 CRI 日志汇总的遗留系统**，或 **合规要求必须在边缘脱敏后再出网** 的场景。

## Environment

| Variable | Description |
|----------|-------------|
| `SHARK_AIOPS_CENTER_URL` | Base URL (no trailing slash) |
| `SHARK_AIOPS_EDGE_TOKEN` | Must match center `SHARK_EDGE_TOKEN` |
| `SHARK_AIOPS_LOG_SOURCE` | Logical source label (default `edge`) |
| `SHARK_AIOPS_LOG_PATHS` | Comma-separated files; if empty, reads **stdin** |
| `SHARK_AIOPS_LOG_SEVERITY` | `error` (default) / `warn` / `all` |
| `SHARK_AIOPS_REDACT_REGEX` | Optional extra rules: `pattern@@@replacement` separated by `\|\|` |

Built-in redaction covers email-like strings, long digit runs (PAN-shaped), and `Bearer …` tokens.

## Build

```bash
cd go-log-collector
go build -o aiops-log-collector .
```

## Examples

```bash
export SHARK_AIOPS_EDGE_TOKEN=secret
export SHARK_AIOPS_LOG_PATHS=/var/log/nginx/error.log
./aiops-log-collector
```

```bash
tail -F /var/log/app.log | SHARK_AIOPS_EDGE_TOKEN=secret ./aiops-log-collector
```

Center endpoint: `POST /api/edge/logs` with body `{ "source": "...", "lines": ["...", ...] }`.
