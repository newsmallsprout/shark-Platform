# ============================================================
# security/services.py — 业务逻辑 (pentest services → Django ORM)
# 逻辑与 pentest 的 task_service/report_service 一致，改用 Django ORM
# ============================================================

import uuid
from datetime import datetime, timezone

from django.db.models import Q, Count

from .models import (
    SecurityTask,
    ScanSession,
    Vulnerability,
    SecurityReport,
    GuidedSession,
    ChatMessage,
)


def list_tasks(
    user,
    page=1,
    page_size=20,
    status=None,
    platform=None,
    mode=None,
    search=None,
):
    """任务列表（分页 + 筛选 + 搜索）"""
    qs = SecurityTask.objects.filter(user=user)

    if status:
        qs = qs.filter(status=status)
    if platform:
        qs = qs.filter(platform=platform)
    if mode:
        qs = qs.filter(mode=mode)
    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(target__icontains=search))

    qs = qs.order_by("-updated_at")
    total = qs.count()
    start = (page - 1) * page_size
    items = list(qs[start : start + page_size])
    return items, total


def get_task(task_id) -> SecurityTask:
    try:
        return SecurityTask.objects.get(id=task_id)
    except SecurityTask.DoesNotExist:
        raise ValueError(f"Task not found: {task_id}")


def create_task(user, data: dict) -> SecurityTask:
    task = SecurityTask(
        title=data.get("title"),
        platform=data.get("platform", "custom"),
        platform_task_id=data.get("platform_task_id"),
        mode=data.get("mode", "auto"),
        status="pending",
        target=data.get("target"),
        scope=data.get("scope") or {},
        tags=data.get("tags"),
        notes=data.get("notes"),
        user=user,
    )
    task.save()
    return task


def update_task(task_id, data: dict) -> SecurityTask:
    task = get_task(task_id)
    allowed = {"title", "status", "progress", "vuln_count", "notes", "tags"}
    for field, value in data.items():
        if field in allowed and value is not None:
            setattr(task, field, value)
    if data.get("status") == "completed":
        task.completed_at = datetime.now(timezone.utc)
    task.save()
    return task


def delete_task(task_id) -> None:
    # Django on_delete=CASCADE 自动清关联数据
    get_task(task_id).delete()


def start_task(task_id) -> SecurityTask:
    task = get_task(task_id)
    if task.status not in ("pending", "paused"):
        raise ValueError(f"任务状态 {task.status} 不允许启动")

    task.status = "running"
    task.progress = 0
    task.save()

    if task.mode == "auto":
        # 延迟导入避免循环依赖；Celery worker 未就绪时会抛异常（扫描引擎阶段接入）
        from security.tasks import run_auto_scan

        run_auto_scan.delay(str(task.id))
    else:
        GuidedSession.objects.get_or_create(task=task, defaults={"current_stage": "recon"})

    return task


def update_vuln_count(task: SecurityTask) -> None:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for row in (
        Vulnerability.objects.filter(task=task)
        .values("severity")
        .annotate(cnt=Count("id"))
    ):
        sev = row["severity"]
        if sev in counts:
            counts[sev] = row["cnt"]
    task.vuln_count = counts
    task.save(update_fields=["vuln_count", "updated_at"])


def get_or_create_scan_session(task_id) -> ScanSession:
    session, _ = ScanSession.objects.get_or_create(
        task_id=task_id, defaults={"current_stage": "init"}
    )
    return session


# ---- 报告 ----


def generate_report(task_id) -> SecurityReport:
    task = get_task(task_id)

    vulns = Vulnerability.objects.filter(task_id=task_id).exclude(status="false_positive")
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for v in vulns:
        if v.severity in severity_counts:
            severity_counts[v.severity] += 1

    overall_severity = "info"
    for sev in ["critical", "high", "medium", "low", "info"]:
        if severity_counts[sev] > 0:
            overall_severity = sev
            break

    parts = [
        f"# {task.title} — 安全测试报告",
        "",
        "## 基本信息",
        f"- 目标 URL: {task.target}",
        f"- 测试时间: {task.created_at.isoformat()}",
        f"- 测试模式: {'自动扫描' if task.mode == 'auto' else '引导模式'}",
        f"- 总体评级: {overall_severity}",
        "",
        "## 漏洞统计",
    ]
    for sev, count in severity_counts.items():
        if count > 0:
            parts.append(f"- {sev}: {count}")

    parts.extend(["", "## 漏洞详情", ""])
    for i, v in enumerate(vulns):
        parts.extend([
            f"### {i + 1}. {v.title}",
            f"- 等级: {v.severity}",
            f"- 类型: {v.type}",
            f"- 端点: {v.endpoint or 'N/A'}",
            f"- 描述: {v.description}",
            f"- 修复建议: {v.recommendation}",
            "",
        ])

    content = "\n".join(parts)

    report = SecurityReport.objects.filter(task_id=task_id).first()
    if report:
        report.content = content
        report.vuln_count = severity_counts
        report.severity = overall_severity
    else:
        report = SecurityReport(
            task_id=task_id,
            title=f"{task.title} — 安全测试报告",
            status="draft",
            severity=overall_severity,
            content=content,
            vuln_count=severity_counts,
            target_info={"url": task.target, "scope": task.scope},
        )
    report.save()
    return report


# ---- 引导模式 ----


def get_or_create_guided_session(task_id) -> GuidedSession:
    session, _ = GuidedSession.objects.get_or_create(
        task_id=task_id, defaults={"current_stage": "recon"}
    )
    return session


def add_message(session_id, role, msg_type="text", content=None, command=None) -> ChatMessage:
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        type=msg_type,
        content=content,
        command=command,
        timestamp=datetime.now(timezone.utc),
    )
    msg.save()
    return msg


def guided_reply(task_id, content: str):
    """处理引导模式用户消息：保存消息 → 运行 guided graph → 返回 AI 回复"""
    import asyncio

    from langchain_core.messages import AIMessage, HumanMessage

    task = get_task(task_id)
    session = get_or_create_guided_session(task_id)

    # 保存用户消息
    add_message(session.id, "user", "text", content)

    # 加载历史对话
    history = list(ChatMessage.objects.filter(session=session).order_by("timestamp"))
    conversation = []
    for m in history:
        if m.role == "user":
            conversation.append(HumanMessage(content=m.content or ""))
        elif m.role == "assistant":
            conversation.append(AIMessage(content=m.content or ""))

    state = {
        "task_id": str(task_id),
        "target": task.target,
        "scope": task.scope or {},
        "current_stage": session.current_stage,
        "conversation_history": conversation,
        "context": "",
        "found_vulns": [],
        "current_command": None,
        "error": None,
    }

    from security.agents.guided.graph import get_guided_graph

    result = asyncio.run(get_guided_graph().ainvoke(state))

    ai_content = ""
    cmd = result.get("current_command")
    if cmd:
        ai_content = (
            f"## 下一步指令\n\n**{cmd.get('description', '')}**\n\n"
            f"```bash\n{cmd.get('command', '')}\n```\n\n"
            f"预期输出: {cmd.get('expected_output', '')}"
        )
    else:
        for m in reversed(result.get("conversation_history", [])):
            if getattr(m, "type", None) == "ai":
                ai_content = getattr(m, "content", "") or ""
                break

    # 保存 AI 回复
    if ai_content:
        add_message(session.id, "assistant", "text", ai_content)

    # 更新阶段
    new_stage = result.get("current_stage", session.current_stage)
    if new_stage != session.current_stage:
        session.current_stage = new_stage
        session.save(update_fields=["current_stage", "updated_at"])

    return ai_content, cmd
