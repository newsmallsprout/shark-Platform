"""
巡检完成后按需自动生成运维工单（去重：同一 report_id 仅一条 [巡检自动] 工单）。
"""

from __future__ import annotations

from django.db import transaction

from core.logging import log

from .models import SystemOpsTicket

AUTO_TICKET_TITLE_PREFIX = "[巡检自动]"


def ensure_auto_ticket_from_inspection(report_id: str, content: dict) -> SystemOpsTicket | None:
    """
    当存在宕机目标、Firing 告警或健康分偏低时创建工单；已存在同日报自动工单则跳过。
    """
    if not report_id:
        return None

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

    # 完全正常则不生成
    health_issue = False
    if isinstance(reasons, list):
        for r in reasons:
            if isinstance(r, str) and r.strip() and r not in ("System Healthy", "resource_max=OK"):
                health_issue = True
                break

    low_score = score_f < 85.0
    needs_ticket = bool(down_targets) or bool(firing) or low_score or health_issue or critical_total > 0

    if not needs_ticket:
        return None

    if SystemOpsTicket.objects.filter(
        inspection_report_id=report_id,
        title__startswith=AUTO_TICKET_TITLE_PREFIX,
    ).exists():
        log("inspection", f"Auto ops ticket already exists for report_id={report_id}, skip.")
        return None

    top_alerts = alerts_summary.get("top_alerts") or []
    title = f"{AUTO_TICKET_TITLE_PREFIX} {report_id} · 巡检异常待处置"

    lines = [
        f"巡检报告 ID：**{report_id}**",
        f"健康分：**{score_f}**",
        f"宕机采集目标：**{len(down_targets)}**",
        f"Firing 告警：**{len(firing)}**（Critical 计数：**{critical_total}**）",
        "",
        "**健康原因：**",
    ]
    if reasons:
        for r in reasons[:20]:
            lines.append(f"- {r}")
    else:
        lines.append("- （无）")
    lines.append("")
    lines.append("**TOP 告警：**")
    if top_alerts:
        for a in top_alerts[:10]:
            lines.append(f"- {a.get('name', '?')} × {a.get('count', 0)}")
    elif firing:
        for a in firing[:10]:
            lines.append(f"- {a.get('name', '?')} [{a.get('severity', '')}]")
    else:
        lines.append("- （无）")

    description = "\n".join(lines)

    if critical_total > 0 or down_targets:
        severity = SystemOpsTicket.SEVERITY_CRITICAL
    elif firing or low_score:
        severity = SystemOpsTicket.SEVERITY_HIGH
    else:
        severity = SystemOpsTicket.SEVERITY_MEDIUM

    snapshot = {
        "source": "inspection_auto",
        "score": score_f,
        "down_targets_count": len(down_targets),
        "firing_count": len(firing),
        "critical_total": critical_total,
        "health_reasons": reasons[:30] if isinstance(reasons, list) else [],
        "top_alerts": top_alerts[:15],
    }

    with transaction.atomic():
        ticket = SystemOpsTicket.objects.create(
            title=title[:255],
            description=description,
            inspection_report_id=report_id,
            inspection_snapshot=snapshot,
            severity=severity,
            status=SystemOpsTicket.STATUS_OPEN,
            created_by=None,
        )

    log("inspection", f"Created auto system ops ticket id={ticket.id} report_id={report_id}")
    return ticket
