"""
巡检完成后按「单个问题」自动生成运维工单（去重：同一 report_id + problem_key 仅一条）。
可选调用巡检配置的 LLM，为每条工单生成处理意见与排查命令。
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests
from django.db import transaction

from core.logging import log

from .models import SystemOpsTicket

AUTO_TICKET_TITLE_PREFIX = "[巡检自动]"

# 资源类工单数量上限，避免主机过多时刷屏
_MAX_RESOURCE_TICKETS = 40


def _inspection_needs_tickets(content: dict) -> bool:
    down_targets = content.get("down_targets") or []
    firing = content.get("firing_alerts") or []
    health = content.get("health_summary") or {}
    score = health.get("score")
    if score is None:
        score = content.get("score")
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        score_f = 100.0

    reasons = health.get("reasons") or []
    alerts_summary = content.get("alerts_summary") or {}
    critical_total = int(alerts_summary.get("critical_total") or 0)

    health_issue = False
    if isinstance(reasons, list):
        for r in reasons:
            if isinstance(r, str) and r.strip() and r not in ("System Healthy", "resource_max=OK"):
                health_issue = True
                break

    low_score = score_f < 85.0
    return bool(down_targets) or bool(firing) or low_score or health_issue or critical_total > 0


def _alert_to_ticket_severity(sev: str) -> str:
    s = (sev or "").lower()
    if s in ("critical", "high"):
        return SystemOpsTicket.SEVERITY_CRITICAL
    if s in ("warning", "warn"):
        return SystemOpsTicket.SEVERITY_HIGH
    return SystemOpsTicket.SEVERITY_MEDIUM


def _resource_metric_severity(kind: str, val: float) -> str:
    if kind == "disk" and val >= 95:
        return SystemOpsTicket.SEVERITY_CRITICAL
    if kind in ("cpu", "mem") and val >= 95:
        return SystemOpsTicket.SEVERITY_CRITICAL
    if kind == "disk" and val >= 90:
        return SystemOpsTicket.SEVERITY_HIGH
    if kind in ("cpu", "mem") and val >= 85:
        return SystemOpsTicket.SEVERITY_HIGH
    return SystemOpsTicket.SEVERITY_MEDIUM


def enumerate_inspection_problems(content: dict) -> list[dict[str, Any]]:
    """将巡检结果拆成若干独立问题项，每项稍后对应一张工单。"""
    problems: list[dict[str, Any]] = []

    for dt in content.get("down_targets") or []:
        if not isinstance(dt, dict):
            continue
        job = str(dt.get("job") or "unknown")
        inst = str(dt.get("instance") or "unknown")
        pkey = f"down:{job}:{inst}"
        problems.append(
            {
                "problem_key": pkey,
                "category": "采集目标不可用",
                "title_suffix": f"{job} / {inst}",
                "severity": SystemOpsTicket.SEVERITY_CRITICAL,
                "context": {
                    "kind": "down_target",
                    "job": job,
                    "instance": inst,
                    "last_error": str(dt.get("last_error") or ""),
                },
            }
        )

    for idx, alert in enumerate(content.get("firing_alerts") or []):
        if not isinstance(alert, dict):
            continue
        name = str(alert.get("name") or "UnknownAlert")
        pkey = f"alert:{idx}:{name}"
        problems.append(
            {
                "problem_key": pkey,
                "category": "告警",
                "title_suffix": name,
                "severity": _alert_to_ticket_severity(str(alert.get("severity") or "")),
                "context": {
                    "kind": "alert",
                    "name": name,
                    "severity": str(alert.get("severity") or ""),
                    "summary": str(alert.get("summary") or ""),
                },
            }
        )

    servers = content.get("servers") or []
    resource_candidates: list[tuple[float, dict[str, Any]]] = []
    if isinstance(servers, list):
        for srv in servers:
            if not isinstance(srv, dict):
                continue
            inst = str(srv.get("instance") or "").strip()
            if not inst:
                continue
            cpu = float(srv.get("cpu_pct") or 0)
            mem = float(srv.get("mem_pct") or 0)
            disk = float(srv.get("disk_pct") or 0)
            if cpu >= 85:
                resource_candidates.append(
                    (-cpu, {"problem_key": f"res:cpu:{inst}", "subtype": "cpu", "instance": inst, "value": cpu})
                )
            if mem >= 85:
                resource_candidates.append(
                    (-mem, {"problem_key": f"res:mem:{inst}", "subtype": "mem", "instance": inst, "value": mem})
                )
            if disk >= 90:
                resource_candidates.append(
                    (-disk, {"problem_key": f"res:disk:{inst}", "subtype": "disk", "instance": inst, "value": disk})
                )

    resource_candidates.sort(key=lambda x: x[0])
    seen_keys: set[str] = set()
    for _, rc in resource_candidates[:_MAX_RESOURCE_TICKETS]:
        pk = rc["problem_key"]
        if pk in seen_keys:
            continue
        seen_keys.add(pk)
        subtype = rc["subtype"]
        inst = rc["instance"]
        val = rc["value"]
        label = {"cpu": "CPU", "mem": "内存", "disk": "磁盘"}.get(subtype, subtype)
        problems.append(
            {
                "problem_key": pk,
                "category": f"资源-{label}",
                "title_suffix": f"{inst} · {label} {val}%",
                "severity": _resource_metric_severity(subtype, val),
                "context": {"kind": "resource", "metric": subtype, "instance": inst, "value_pct": val},
            }
        )

    return problems


def _load_inspection_llm_config():
    try:
        from inspection.models import InspectionConfig

        return InspectionConfig.load()
    except Exception:
        return None


def _call_gemini_json(cfg, user_prompt: str, system_prompt: str) -> str:
    api_key = cfg.ark_api_key
    model = cfg.ark_model_id or "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
    }
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_openai_compatible_json(cfg, user_prompt: str, system_prompt: str) -> str:
    url = f"{cfg.ark_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": cfg.ark_model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {cfg.ark_api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _batch_ai_guidance(problems: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """一次请求返回所有 problem_key 的建议；失败返回空 dict。"""
    cfg = _load_inspection_llm_config()
    if not cfg or not getattr(cfg, "ark_api_key", None):
        return {}

    payload_items = []
    for p in problems:
        payload_items.append({"id": p["problem_key"], "category": p["category"], "context": p["context"]})

    user_prompt = json.dumps({"inspection_problems": payload_items}, ensure_ascii=False, indent=2)
    system_prompt = (
        "你是资深 SRE。下面是同一次巡检拆分出的多个独立问题，每条有唯一 id。\n"
        "请为每条问题给出：简明的中文处理意见（步骤化）、以及可在 Linux/K8s/Prometheus 环境下执行的排查命令列表。\n"
        "命令需具体可粘贴执行；若信息不足请给出典型排查命令并注明需替换的占位符。\n"
        "严格只输出一个 JSON 数组，不要有其它文字。数组元素格式：\n"
        '[{"id":"<与输入一致>","handling_opinion":"<中文>","troubleshooting_commands":["命令1","命令2"]}]\n'
    )

    ids = [p["problem_key"] for p in problems]
    try:
        model_id = (cfg.ark_model_id or "").lower()
        if "gemini" in model_id:
            text = _call_gemini_json(cfg, user_prompt, system_prompt)
        elif cfg.ark_base_url:
            text = _call_openai_compatible_json(cfg, user_prompt, system_prompt)
        else:
            return {}
    except Exception as exc:
        log("inspection", f"Batch AI guidance for ops tickets failed: {exc}")
        return {}

    return _parse_ai_guidance_json(text, ids)


def _parse_ai_guidance_json(text: str, problem_ids: list[str]) -> dict[str, dict[str, Any]]:
    raw = (text or "").strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if m:
            raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    id_set = set(problem_ids)
    out: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            data = data["items"]
        else:
            return {}
    if not isinstance(data, list):
        return {}

    for item in data:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        if pid not in id_set:
            continue
        opinion = str(item.get("handling_opinion") or "").strip()
        cmds = item.get("troubleshooting_commands") or item.get("commands") or []
        if isinstance(cmds, str):
            cmds = [cmds]
        cmds = [str(c).strip() for c in cmds if str(c).strip()]
        out[pid] = {"handling_opinion": opinion, "troubleshooting_commands": cmds}
    return out


def _fallback_guidance(prob: dict[str, Any]) -> tuple[str, list[str]]:
    ctx = prob.get("context") or {}
    kind = ctx.get("kind")
    if kind == "down_target":
        inst = ctx.get("instance") or ""
        return (
            "确认目标进程与机器存活；检查 Prometheus 抓取配置、网络与安全组；查看目标 exporter 日志与机器负载。",
            [
                f"# 在 Prometheus 节点探测目标（按需替换地址）\ncurl -sS 'http://127.0.0.1:9090/api/v1/targets' | jq .",
                f"# 登录主机 {inst} 检查 exporter 与防火墙（按需）\nsudo systemctl status node_exporter || true",
            ],
        )
    if kind == "alert":
        name = ctx.get("name") or ""
        return (
            f"根据告警「{name}」核对近期变更与依赖服务；在 Grafana/Prometheus 中查看相关指标与告警规则表达式。",
            [
                "# Prometheus 告警列表（按需替换地址）\ncurl -sS 'http://127.0.0.1:9090/api/v1/alerts' | jq .",
            ],
        )
    if kind == "resource":
        metric = ctx.get("metric")
        inst = ctx.get("instance") or ""
        tips = {
            "cpu": "排查高 CPU 进程、定时任务与突发流量；必要时 limit/request 与扩容。",
            "mem": "排查内存泄漏与大页缓存；检查 OOM 记录与容器限制。",
            "disk": "清理日志与临时文件；扩容磁盘或调整日志轮转策略。",
        }.get(metric, "结合主机监控逐项排查资源瓶颈。")
        return (
            tips,
            [
                f"# SSH 到 {inst} 查看整体负载\nuptime && top -b -n 1 | head -20",
                "df -h && df -ih",
            ],
        )
    return ("请结合巡检上下文人工分析并制定处置步骤。", [])


def _build_ticket_description(
    report_id: str,
    prob: dict[str, Any],
    opinion: str,
    commands: list[str],
) -> str:
    ctx = prob.get("context") or {}
    lines = [
        f"**巡检报告：** {report_id}",
        f"**问题分类：** {prob.get('category')}",
        "",
        "**现象与上下文：**",
        "```json",
        json.dumps(ctx, ensure_ascii=False, indent=2),
        "```",
        "",
        "**AI 处理意见：**",
        opinion or "（无）",
        "",
        "**建议排查命令：**",
    ]
    if commands:
        for i, c in enumerate(commands, 1):
            lines.append(f"{i}. ```bash\n{c}\n```")
    else:
        lines.append("（无）")
    return "\n".join(lines)


def ensure_auto_tickets_from_inspection(report_id: str, content: dict) -> list[SystemOpsTicket]:
    """
    当巡检存在异常时：按问题拆分为多张待处理工单；同一 report_id + problem_key 不重复创建。
    """
    created: list[SystemOpsTicket] = []
    if not report_id:
        return created

    if not _inspection_needs_tickets(content):
        return created

    problems = enumerate_inspection_problems(content)
    if not problems:
        health = content.get("health_summary") or {}
        score = health.get("score")
        if score is None:
            score = content.get("score")
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            score_f = 0.0
        problems = [
            {
                "problem_key": f"aggregate:{report_id}",
                "category": "综合",
                "title_suffix": "巡检异常综合待处置",
                "severity": SystemOpsTicket.SEVERITY_HIGH,
                "context": {
                    "kind": "aggregate",
                    "health_summary": health,
                    "score": score_f,
                    "note": "未拆出独立问题项时的兜底工单",
                },
            }
        ]

    ai_map = _batch_ai_guidance(problems)

    health = content.get("health_summary") or {}
    try:
        score_f = float(health.get("score") if health.get("score") is not None else content.get("score") or 100)
    except (TypeError, ValueError):
        score_f = 100.0

    for prob in problems:
        pkey = prob["problem_key"]
        if SystemOpsTicket.objects.filter(
            inspection_report_id=report_id,
            inspection_snapshot__problem_key=pkey,
        ).exists():
            log("inspection", f"Auto ops ticket exists report_id={report_id} problem_key={pkey}, skip.")
            continue

        ai_row = ai_map.get(pkey) or {}
        opinion = str(ai_row.get("handling_opinion") or "").strip()
        commands = ai_row.get("troubleshooting_commands") or []
        if not isinstance(commands, list):
            commands = []
        commands = [str(c).strip() for c in commands if str(c).strip()]
        if not opinion and not commands:
            opinion, commands = _fallback_guidance(prob)

        cat = str(prob.get("category") or "其它")
        suffix = str(prob.get("title_suffix") or "")[:180]
        title = f"{AUTO_TICKET_TITLE_PREFIX} {report_id} · {cat} · {suffix}"
        title = title[:255]

        description = _build_ticket_description(report_id, prob, opinion, commands)
        snapshot = {
            "source": "inspection_auto",
            "problem_key": pkey,
            "category": cat,
            "score_at_inspection": score_f,
            "context": prob.get("context") or {},
            "ai_handling_opinion": opinion,
            "ai_troubleshooting_commands": commands,
        }

        with transaction.atomic():
            ticket = SystemOpsTicket.objects.create(
                title=title,
                description=description,
                inspection_report_id=report_id,
                inspection_snapshot=snapshot,
                severity=prob.get("severity") or SystemOpsTicket.SEVERITY_MEDIUM,
                status=SystemOpsTicket.STATUS_OPEN,
                created_by=None,
            )
        created.append(ticket)
        log("inspection", f"Created auto system ops ticket id={ticket.id} report_id={report_id} problem_key={pkey}")

    return created


# 兼容旧名称（若有外部引用）
def ensure_auto_ticket_from_inspection(report_id: str, content: dict) -> SystemOpsTicket | None:
    tickets = ensure_auto_tickets_from_inspection(report_id, content)
    return tickets[0] if tickets else None
