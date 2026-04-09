"""
Agent ↔ 大模型 机读协议：<EXECUTE> 只读取证、<TICKET> 生成人类审批工单。

主场景：**Linux 主机**（systemd、网络、资源、journald）与 **Kubernetes**（kubectl 只读）。
扩展（默认关）：Worker 上的 docker/crictl、多云 CLI、terraform —— 由环境变量按需开启。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from django.conf import settings

from ai_ops.services.sre_tools import query_log_monitor_errors, query_prometheus

logger = logging.getLogger(__name__)

M2M_SYSTEM_PROMPT = """# Role: AIOps 自动排障决策大脑 (Autonomous Diagnostic Brain)

## Profile
对话对象是**自动化执行 Agent**，不是人类。目标：基于**Linux 主机**与 **Kubernetes** 环境的只读取证，形成《修复审批工单》。

**主路径**：告警标签 / 上下文 → **Prometheus（PromQL）** → **kubectl 只读** → **Linux 主机**（systemd、journal、网络、/proc、资源）。Worker 上需具备：可访问的 Prometheus、kubectl+kubeconfig（查集群时）、以及常见 Linux 诊断命令。

**辅路径**（仅当平台开启对应能力且与故障相关）：`HTTPGET|` 探活、`LOGMON|` 查平台落盘 error 日志；若运维显式在 Worker 上启用了 docker/crictl/云 CLI，Observation 成功时才继续用，否则回到主路径。

## 交互与输出规范（机读，Strict）
1. **禁止客套话**。
2. **每轮二选一**：`<EXECUTE>`+`<REASON>` **或** 仅 `<TICKET>`。

## 状态 A：命令行（一行一条）
### 通用硬禁止
Shell 元字符：`;` `&&` `||` 反引号 `$()`；禁止裸 `|`（**例外**：`PROMQL|`、`PROMQLR|...`、`HTTPGET|`、`LOGMON|` 等协议前缀行；PromQL 表达式内勿含 `|`）。

### A. Prometheus
- `PROMQL|<instant PromQL>`
- `PROMQLR|<minutes>|<step>|<PromQL>`

### B. HTTP 探测
- `HTTPGET|<http(s) URL>`

### C. 平台落盘日志
- `LOGMON|<namespace 或空>|<pod 名子串>`

### D. Kubernetes（kubectl + kubeconfig）
允许：get, describe, logs, top, explain, version, api-resources, cluster-info, config view, auth can-i。禁止一切变更类子命令（apply/delete/scale/rollout/exec 等）。

### E. Linux 主机（在 Worker 本机执行）
`df` `free` `uptime` `uname` `hostname` `lscpu` `lsblk` `mount` `vmstat`；`systemctl status|show|list-units|list-jobs|cat`；`journalctl`（禁 vacuum/flush/rotate）；`ip addr|route|link|neigh|rule` `ss` `netstat` `dig` `nslookup` `ping -c≤10`；`cat /proc/...`；`dmesg`（禁清环缓 `-c/-C`）。

### F. 可选（平台开启时）
`docker` / `crictl` 只读子命令；`aws` / `az` / `gcloud` 只读（有黑名单）；`terraform` state/show 等。未开启或命令不存在时勿纠缠，改用 D/E。

## 状态 B：<TICKET>
<TICKET>
# 故障修复审批工单
- **告警摘要**：
- **环境类型**：（如：Kubernetes 集群内 / Linux 工作节点 / 纯 Linux 主机 / 组合）
- **影响范围**：（namespace、工作负载、节点、实例等）
- **根因分析**：
- **修复方案**：
- **待执行脚本/YAML**：（```bash 或 ```yaml）
- **回滚方案**：
- **风险评估**：（高/中/低）
</TICKET>

## 工作流约束
- 同一条命令失败 3 次 → 换思路或 `<TICKET>` 转人工。
- `<EXECUTE>` 阶段只读；变更只写在 `<TICKET>`。
- 取证顺序建议：**PromQL ↔ kubectl describe/logs/get ↔ 节点或 Worker 上 journalctl / ip / ss**。
"""

_EXEC_RE = re.compile(r"<EXECUTE>\s*(.*?)\s*</EXECUTE>", re.IGNORECASE | re.DOTALL)
_REASON_RE = re.compile(r"<REASON>\s*(.*?)\s*</REASON>", re.IGNORECASE | re.DOTALL)
_TICKET_RE = re.compile(r"<TICKET>\s*(.*?)\s*</TICKET>", re.IGNORECASE | re.DOTALL)

_KUBECTL_OK = re.compile(
    r"^kubectl\s+("
    r"get|describe|logs|top|explain|version|api-resources|cluster-info|auth\s+can-i|config\s+view"
    r")\b",
    re.IGNORECASE,
)

_FORBIDDEN_K = (
    "kubectl apply",
    "kubectl delete",
    "kubectl create",
    "kubectl patch",
    "kubectl replace",
    "kubectl scale",
    "kubectl rollout",
    "kubectl run",
    "kubectl exec",
    "kubectl attach",
    "kubectl port-forward",
    "kubectl proxy",
    "kubectl edit",
    "kubectl drain",
    "kubectl cordon",
    "kubectl uncordon",
    "kubectl taint",
)

_SHELL_META = re.compile(r"[;&`]|&&|\|\||\$\(")


def _flag(name: str, default: bool = True) -> bool:
    ev = os.environ.get(name)
    if ev is not None:
        return str(ev).strip().lower() in ("1", "true", "yes", "on")
    gv = getattr(settings, name, None)
    if gv is not None:
        return bool(gv)
    return default


def _has_shell_meta(s: str) -> bool:
    return bool(_SHELL_META.search(s))


def _cloud_line_blocked(line: str) -> bool:
    low = line.lower()
    rx = re.compile(
        r"\b("
        r"delete|terminate|remove|destroy|stop-instances|start-instances|run-instances|"
        r"create-|put-bucket|put-object|delete-object|attach-volume|detach-volume|"
        r"authorize-|revoke-|associate-|disassociate-|allocate-address|release-address|"
        r"invoke|ssm\s+start-session|lambda\s+invoke|ddb\s+put|ddb\s+delete|"
        r"s3\s+cp\b|s3\s+sync\b|s3\s+mv\b|s3\s+rm\b|"
        r"az\s+\w+\s+create\b|deployment\s+create|group\s+create|"
        r"run-command|snapshot\s+create"
        r")\b",
        re.I,
    )
    return bool(rx.search(low))


def _azure_line_blocked(line: str) -> bool:
    return bool(
        re.search(
            r"\b(create|delete|update|set|remove|purge|stop|start|restart|scale|deploy|run-command)\b",
            line,
            re.I,
        )
    )


def _gcloud_line_blocked(line: str) -> bool:
    return bool(re.search(r"\b(create|delete|update|patch|ssh|scp|deploy|run|start|stop)\b", line, re.I))


_DOCKER_OK = re.compile(
    r"^docker\s+(ps|images|inspect|stats|logs|version|info|network\s+ls|volume\s+ls)\b",
    re.I,
)

_CRICTL_OK = re.compile(
    r"^crictl\s+(ps|pods|images|inspecti|inspectp|inspect|logs|version)\b",
    re.I,
)

_TERRAFORM_OK = re.compile(
    r"^terraform\s+(state\s+list|state\s+show|show|version|output)\b",
    re.I,
)


def _journalctl_safe(s: str) -> bool:
    if not re.match(r"^journalctl\b", s, re.I):
        return True
    return not bool(re.search(r"--vacuum|flush|--rotate|--disk-usage|\+\+", s, re.I))


def _ping_safe(s: str) -> bool:
    if not re.match(r"^ping\b", s, re.I):
        return True
    m = re.search(r"-c\s+(\d+)", s, re.I)
    if not m:
        return False
    return int(m.group(1)) <= 10


def _matches_host_readonly(s: str) -> bool:
    if not _journalctl_safe(s) or not _ping_safe(s):
        return False
    if re.match(r"^dmesg\b", s, re.I):
        if re.search(r"\s-[cC](\s|$)", s):
            return False
        return True
    patterns = [
        r"^df(\s|$)",
        r"^free(\s|$)",
        r"^uptime(\s|$)",
        r"^uname(\s|$)",
        r"^hostname(\s|$)",
        r"^lscpu(\s|$)",
        r"^lsblk(\s|$)",
        r"^mount(\s|$)",
        r"^vmstat(\s|$)",
        r"^hostnamectl\s+status\b",
        r"^systemctl\s+(status|show|list-units|list-jobs|cat)\s",
        r"^journalctl\b",
        r"^ip\s+(addr|route|link|neigh|rule)\s",
        r"^ss\b",
        r"^netstat\b",
        r"^dig\s",
        r"^nslookup\s",
        r"^cat\s+/proc/",
        r"^ping(\s+-\S+)*\s+-c\s+\d+\s+\S",
    ]
    for p in patterns:
        if re.match(p, s, re.I):
            return True
    return False


def plan_exec_line(line: str) -> tuple[bool, str, str]:
    """
    返回 (allowed, error_code, kind)。
    kind: promql | promql_range | httpget | logmon | kubectl | aws | az | gcloud | docker | crictl | terraform | host
    """
    s = (line or "").strip()
    if not s or s.startswith("#"):
        return False, "empty_or_comment", ""

    sl = s.lower()
    if sl.startswith("promql|"):
        rest = s.split("|", 1)[1]
        if _has_shell_meta(rest):
            return False, "forbidden_metacharacters", ""
        expr = rest.strip()
        if not expr or "|" in expr:
            return False, "invalid_promql_payload", ""
        if not _flag("AIOPS_M2M_ENABLE_PROMQL", True):
            return False, "promql_disabled", ""
        return True, "", "promql"

    if sl.startswith("promqlr|"):
        parts = s.split("|", 3)
        if len(parts) < 4:
            return False, "promqlr_need_4_segments", ""
        _, mins_s, step_s, query = parts[0], parts[1], parts[2], parts[3]
        if _has_shell_meta(mins_s + step_s + query):
            return False, "forbidden_metacharacters", ""
        if "|" in query:
            return False, "promql_query_must_not_contain_pipe", ""
        try:
            mins = int(mins_s.strip())
            mins = max(5, min(mins, 1440))
        except ValueError:
            return False, "promqlr_invalid_minutes", ""
        if not step_s.strip():
            return False, "promqlr_invalid_step", ""
        if not _flag("AIOPS_M2M_ENABLE_PROMQL", True):
            return False, "promql_disabled", ""
        return True, "", "promql_range"

    if sl.startswith("httpget|"):
        url = s.split("|", 1)[1].strip()
        if _has_shell_meta(url):
            return False, "forbidden_metacharacters", ""
        if not _flag("AIOPS_M2M_ENABLE_HTTPGET", True):
            return False, "httpget_disabled", ""
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc:
            return False, "httpget_only_http_https_with_host", ""
        return True, "", "httpget"

    if sl.startswith("logmon|"):
        if not _flag("AIOPS_M2M_ENABLE_LOGMON", True):
            return False, "logmon_disabled", ""
        m = re.match(r"(?i)^LOGMON\|([^|]*)\|(.*)$", s)
        if not m:
            return False, "logmon_need_LOGMON|ns|pod_sub", ""
        ns, pod = m.group(1).strip(), m.group(2).strip()
        rest = f"{ns}|{pod}"
        if _has_shell_meta(rest):
            return False, "forbidden_metacharacters", ""
        return True, "", "logmon"

    if _has_shell_meta(s) or "|" in s:
        return False, "forbidden_metacharacters_or_unexpected_pipe", ""

    low = s.lower()
    if low.startswith("kubectl "):
        for bad in _FORBIDDEN_K:
            if bad in low:
                return False, f"forbidden_kubectl:{bad}", ""
        if not _KUBECTL_OK.match(s):
            return False, "kubectl_subcommand_not_allowlisted", ""
        if not _flag("AIOPS_M2M_ENABLE_KUBECTL", True):
            return False, "kubectl_disabled", ""
        return True, "", "kubectl"

    if low.startswith("aws "):
        if not _flag("AIOPS_M2M_ENABLE_CLOUD_CLI", False):
            return False, "cloud_cli_disabled", ""
        if _cloud_line_blocked(s):
            return False, "aws_mutating_or_blocked_pattern", ""
        return True, "", "aws"

    if low.startswith("az "):
        if not _flag("AIOPS_M2M_ENABLE_CLOUD_CLI", False):
            return False, "cloud_cli_disabled", ""
        if _azure_line_blocked(s):
            return False, "az_mutating_or_blocked_pattern", ""
        return True, "", "az"

    if low.startswith("gcloud "):
        if not _flag("AIOPS_M2M_ENABLE_CLOUD_CLI", False):
            return False, "cloud_cli_disabled", ""
        if _gcloud_line_blocked(s):
            return False, "gcloud_mutating_or_blocked_pattern", ""
        return True, "", "gcloud"

    if low.startswith("docker "):
        if not _flag("AIOPS_M2M_ENABLE_DOCKER_CLI", False):
            return False, "docker_cli_disabled", ""
        if not _DOCKER_OK.match(s):
            return False, "docker_subcommand_not_allowlisted", ""
        return True, "", "docker"

    if low.startswith("crictl "):
        if not _flag("AIOPS_M2M_ENABLE_DOCKER_CLI", False):
            return False, "crictl_disabled", ""
        if not _CRICTL_OK.match(s):
            return False, "crictl_subcommand_not_allowlisted", ""
        return True, "", "crictl"

    if low.startswith("terraform "):
        if not _flag("AIOPS_M2M_ENABLE_TERRAFORM", False):
            return False, "terraform_disabled", ""
        if not _TERRAFORM_OK.match(s):
            return False, "terraform_subcommand_not_allowlisted", ""
        return True, "", "terraform"

    if _matches_host_readonly(s):
        if not _flag("AIOPS_M2M_ENABLE_HOST_CLI", True):
            return False, "host_cli_disabled", ""
        return True, "", "host"

    return False, "line_not_recognized_allowed_readonly", ""


def parse_model_turn(content: str) -> Dict[str, Any]:
    raw = content or ""
    exec_blocks = _EXEC_RE.findall(raw)
    lines: List[str] = []
    for block in exec_blocks:
        for ln in block.splitlines():
            t = ln.strip()
            if t and not t.startswith("#"):
                lines.append(t)
    reason_m = _REASON_RE.search(raw)
    reason = (reason_m.group(1).strip() if reason_m else "")[:8000]
    ticket_m = _TICKET_RE.search(raw)
    ticket = (ticket_m.group(1).strip() if ticket_m else None)
    if ticket:
        ticket = ticket[:50000]
    return {"execute_lines": lines, "reason": reason, "ticket_body": ticket}


def _run_subprocess_argv(
    argv: List[str],
    *,
    line: str,
    timeout_sec: int,
) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=os.environ.copy(),
        )
        out = (proc.stdout or "")[-200_000:]
        err = (proc.stderr or "")[-80_000:]
        success = proc.returncode == 0
        return {
            "ok": success,
            "command": line,
            "returncode": proc.returncode,
            "stdout": out,
            "stderr": err,
            "error": "" if success else (err.strip() or f"exit {proc.returncode}"),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "command": line, "stdout": "", "stderr": ""}
    except FileNotFoundError:
        return {"ok": False, "error": f"binary_not_found:{argv[0]}", "command": line, "stdout": "", "stderr": ""}
    except Exception as e:
        logger.exception("subprocess")
        return {"ok": False, "error": str(e)[:500], "command": line, "stdout": "", "stderr": ""}


def _http_get_probe(url: str) -> Dict[str, Any]:
    try:
        r = requests.get(
            url,
            timeout=float(os.environ.get("AIOPS_HTTPGET_TIMEOUT_SEC", "15")),
            allow_redirects=True,
            headers={"User-Agent": "shark-aiops-m2m/1.0"},
        )
        body = (r.text or "")[:_http_max_bytes()]
        return {
            "ok": True,
            "url": url,
            "status_code": r.status_code,
            "headers_sample": dict(list(r.headers.items())[:24]),
            "body_excerpt": body,
            "truncated": len(r.text or "") > len(body),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:500], "url": url}


def _http_max_bytes() -> int:
    try:
        return max(1024, min(int(os.environ.get("AIOPS_HTTPGET_MAX_BYTES", "524288")), 2_097_152))
    except ValueError:
        return 524_288


def run_diagnostic_line(
    line: str,
    *,
    prometheus_url: str,
    log_start_iso: str = "",
    log_end_iso: str = "",
) -> Dict[str, Any]:
    ok, why, kind = plan_exec_line(line)
    if not ok:
        return {"ok": False, "error": why, "command": line, "stdout": "", "stderr": ""}

    stripped = line.strip()
    timeout = int(os.environ.get("AIOPS_M2M_CMD_TIMEOUT_SEC", "120"))
    timeout = max(5, min(timeout, 600))

    if kind == "promql":
        expr = stripped.split("|", 1)[1].strip()
        return query_prometheus(
            {"query": expr, "query_type": "instant", "range_minutes": 60, "step": "60s"},
            prometheus_url,
        )

    if kind == "promql_range":
        _, mins_s, step_s, query = stripped.split("|", 3)
        return query_prometheus(
            {
                "query": query.strip(),
                "query_type": "range",
                "range_minutes": int(mins_s.strip()),
                "step": step_s.strip() or "60s",
            },
            prometheus_url,
        )

    if kind == "httpget":
        url = stripped.split("|", 1)[1].strip()
        obs = _http_get_probe(url)
        obs["command"] = line
        return obs

    if kind == "logmon":
        m = re.match(r"(?i)^LOGMON\|([^|]*)\|(.*)$", stripped)
        ns = (m.group(1) or "").strip()
        pod_sub = (m.group(2) or "").strip()
        args = {
            "start_iso8601": log_start_iso or "",
            "end_iso8601": log_end_iso or "",
            "namespace": ns,
            "pod_name_substring": pod_sub,
            "max_entries": 60,
        }
        return query_log_monitor_errors(args)

    if kind == "kubectl":
        kubectl_bin = (
            getattr(settings, "AIOPS_KUBECTL_PATH", None)
            or os.environ.get("AIOPS_KUBECTL_PATH")
            or "kubectl"
        )
        try:
            parts = shlex.split(stripped, posix=True)
        except ValueError as e:
            return {"ok": False, "error": f"shlex:{e}", "command": line, "stdout": "", "stderr": ""}
        if not parts:
            return {"ok": False, "error": "empty_argv", "command": line, "stdout": "", "stderr": ""}
        parts[0] = kubectl_bin
        return _run_subprocess_argv(parts, line=line, timeout_sec=timeout)

    try:
        parts = shlex.split(stripped, posix=True)
    except ValueError as e:
        return {"ok": False, "error": f"shlex:{e}", "command": line, "stdout": "", "stderr": ""}
    if not parts:
        return {"ok": False, "error": "empty_argv", "command": line, "stdout": "", "stderr": ""}

    return _run_subprocess_argv(parts, line=line, timeout_sec=timeout)


def _extract_markdown_field(body: str, label: str) -> str:
    patterns = [
        rf"(?im)^\s*-\s*\*\*{re.escape(label)}\*\*\s*[:：]\s*(.+)$",
        rf"(?im)^\s*\*\*{re.escape(label)}\*\*\s*[:：]\s*(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, body)
        if m:
            return m.group(1).strip()
    return ""


def _extract_code_blocks(body: str) -> List[str]:
    blocks: List[str] = []
    for m in re.finditer(r"```(?:bash|sh|shell|yaml|yml)?\s*\n(.*?)```", body, re.DOTALL | re.IGNORECASE):
        t = m.group(1).strip()
        if t:
            blocks.append(t)
    return blocks


def ticket_body_to_final_report(body: str, incident_alert_name: str) -> Dict[str, Any]:
    summary = _extract_markdown_field(body, "告警摘要") or incident_alert_name
    env_type = _extract_markdown_field(body, "环境类型")
    impact = _extract_markdown_field(body, "影响范围")
    root = _extract_markdown_field(body, "根因分析")
    fix = _extract_markdown_field(body, "修复方案")
    rollback = _extract_markdown_field(body, "回滚方案")
    risk = _extract_markdown_field(body, "风险评估")

    root_parts = [x for x in [env_type and f"【环境】{env_type}", impact and f"【影响范围】{impact}", root, fix] if x]
    root_combined = "\n\n".join(root_parts).strip() or body[:8000]

    blocks = _extract_code_blocks(body)
    mitigation: List[str] = []
    for b in blocks:
        for ln in b.splitlines():
            t = ln.strip()
            if t and not t.startswith("#"):
                mitigation.append(t)
    if not mitigation and blocks:
        mitigation = ["\n".join(blocks)]

    prev: List[str] = []
    if rollback:
        prev.append(f"回滚方案：{rollback}")

    rl = (risk or "").lower()
    if "高" in risk or "high" in rl:
        conf = "high"
    elif "低" in risk or "low" in rl:
        conf = "low"
    else:
        conf = "medium"

    return {
        "incident_summary": summary[:4000],
        "root_cause": root_combined[:12000],
        "mitigation_commands": mitigation[:80],
        "prevention": prev,
        "confidence": conf,
        "evidence_chain": [],
        "data_citations": [{"type": "m2m_ticket", "excerpt": body[:3000]}],
    }


class CommandStrikeTracker:
    def __init__(self, limit: int = 3) -> None:
        self._counts: Dict[str, int] = {}
        self._limit = max(1, limit)

    def key(self, cmd: str) -> str:
        return re.sub(r"\s+", " ", cmd.strip())

    def record(self, cmd: str, success: bool) -> None:
        k = self.key(cmd)
        if success:
            self._counts.pop(k, None)
            return
        self._counts[k] = self._counts.get(k, 0) + 1

    def blocked(self, cmd: str) -> bool:
        k = self.key(cmd)
        return self._counts.get(k, 0) >= self._limit
