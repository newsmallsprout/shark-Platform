# ============================================================
# security/views.py — DRF 视图 (pentest FastAPI router → DRF)
# 挂载于 /api/v1/，响应契约与 pentest 一致
# ============================================================

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    SecurityTask,
    ScanSession,
    ScanTool,
    Asset,
    Vulnerability,
    SecurityReport,
    KnowledgeDoc,
    GuidedSession,
    ChatMessage,
)
from .serializers import (
    SecurityTaskSerializer,
    ScanSessionSerializer,
    ScanToolSerializer,
    AssetSerializer,
    VulnerabilitySerializer,
    SecurityReportSerializer,
    KnowledgeDocSerializer,
    GuidedSessionSerializer,
    ChatMessageSerializer,
)
from . import services


def _paged(items, total, page, page_size):
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ---- Tasks ----


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def task_list(request):
    if request.method == "GET":
        qp = request.query_params
        page = int(qp.get("page", 1))
        page_size = int(qp.get("page_size", 20))
        items, total = services.list_tasks(
            request.user,
            page=page,
            page_size=page_size,
            status=qp.get("status"),
            platform=qp.get("platform"),
            mode=qp.get("mode"),
            search=qp.get("search"),
        )
        return Response(_paged(SecurityTaskSerializer(items, many=True).data, total, page, page_size))

    data = request.data
    if not data.get("title") or not data.get("target"):
        return Response({"detail": "title 和 target 必填"}, status=400)
    task = services.create_task(request.user, data)
    return Response(SecurityTaskSerializer(task).data, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def task_detail(request, task_id):
    try:
        task = services.get_task(task_id)
    except ValueError:
        return Response({"detail": "任务不存在"}, status=404)

    if request.method == "GET":
        return Response(SecurityTaskSerializer(task).data)

    if request.method == "PATCH":
        task = services.update_task(task_id, request.data)
        return Response(SecurityTaskSerializer(task).data)

    services.delete_task(task_id)
    return Response(status=204)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_start(request, task_id):
    try:
        task = services.start_task(task_id)
    except ValueError as e:
        return Response({"detail": str(e)}, status=400)
    return Response(SecurityTaskSerializer(task).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_pause(request, task_id):
    try:
        task = services.update_task(task_id, {"status": "paused"})
    except ValueError:
        return Response({"detail": "任务不存在"}, status=404)
    return Response(SecurityTaskSerializer(task).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_resume(request, task_id):
    try:
        task = services.update_task(task_id, {"status": "running"})
    except ValueError:
        return Response({"detail": "任务不存在"}, status=404)
    return Response(SecurityTaskSerializer(task).data)


# ---- Scans ----


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def scan_session(request, task_id):
    session = services.get_or_create_scan_session(task_id)
    return Response(ScanSessionSerializer(session).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def scan_assets(request, task_id):
    assets = Asset.objects.filter(session__task_id=task_id)
    return Response(AssetSerializer(assets, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def scan_tools(request, task_id):
    tools = ScanTool.objects.filter(session__task_id=task_id).order_by("created_at")
    return Response(ScanToolSerializer(tools, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_vulnerabilities(request, task_id):
    vulns = Vulnerability.objects.filter(task_id=task_id).order_by("-found_at")
    return Response(VulnerabilitySerializer(vulns, many=True).data)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def vuln_status(request, task_id, vuln_id):
    try:
        vuln = Vulnerability.objects.get(id=vuln_id, task_id=task_id)
    except Vulnerability.DoesNotExist:
        return Response({"detail": "漏洞不存在"}, status=404)
    new_status = request.data.get("status")
    if new_status not in ("new", "confirmed", "false_positive", "duplicate", "accepted", "fixed"):
        return Response({"detail": "无效的状态"}, status=400)
    vuln.status = new_status
    vuln.save()
    return Response(VulnerabilitySerializer(vuln).data)


# ---- Reports ----


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_list(request):
    qp = request.query_params
    page = int(qp.get("page", 1))
    page_size = int(qp.get("page_size", 20))
    qs = SecurityReport.objects.all().order_by("-updated_at")
    if qp.get("status"):
        qs = qs.filter(status=qp.get("status"))
    total = qs.count()
    items = list(qs[(page - 1) * page_size : (page - 1) * page_size + page_size])
    return Response(_paged(SecurityReportSerializer(items, many=True).data, total, page, page_size))


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def report_detail(request, report_id):
    try:
        report = SecurityReport.objects.get(id=report_id)
    except SecurityReport.DoesNotExist:
        return Response({"detail": "报告不存在"}, status=404)

    if request.method == "GET":
        return Response(SecurityReportSerializer(report).data)

    for field in ("title", "content", "edited_content", "status"):
        if field in request.data:
            setattr(report, field, request.data[field])
    report.save()
    return Response(SecurityReportSerializer(report).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def report_generate(request, task_id):
    try:
        report = services.generate_report(task_id)
    except ValueError:
        return Response({"detail": "任务不存在"}, status=404)
    return Response(SecurityReportSerializer(report).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def report_submit(request, report_id):
    try:
        report = SecurityReport.objects.get(id=report_id)
    except SecurityReport.DoesNotExist:
        return Response({"detail": "报告不存在"}, status=404)
    report.status = "submitted"
    from datetime import datetime, timezone

    report.submitted_at = datetime.now(timezone.utc)
    report.save()
    return Response(SecurityReportSerializer(report).data)


# ---- Knowledge ----


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def knowledge_list(request):
    qp = request.query_params
    page = int(qp.get("page", 1))
    page_size = int(qp.get("page_size", 20))
    qs = KnowledgeDoc.objects.all().order_by("-created_at")
    if qp.get("source"):
        qs = qs.filter(source=qp.get("source"))
    if qp.get("search"):
        qs = qs.filter(title__icontains=qp.get("search"))
    total = qs.count()
    items = list(qs[(page - 1) * page_size : (page - 1) * page_size + page_size])
    return Response(_paged(KnowledgeDocSerializer(items, many=True).data, total, page, page_size))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def knowledge_ingest(request):
    data = request.data
    if not data.get("title") or not data.get("content"):
        return Response({"detail": "title 和 content 必填"}, status=400)
    doc = KnowledgeDoc(
        title=data["title"],
        source=data.get("source", "custom"),
        content=data["content"],
        tags=data.get("tags"),
        url=data.get("url"),
    )
    doc.save()
    return Response(KnowledgeDocSerializer(doc).data, status=201)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def knowledge_delete(request, doc_id):
    KnowledgeDoc.objects.filter(id=doc_id).delete()
    return Response(status=204)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def knowledge_stats(request):
    count = KnowledgeDoc.objects.count()
    last = KnowledgeDoc.objects.order_by("-updated_at").first()
    return Response({
        "document_count": count,
        "vector_count": count,  # 简化为 1:1（向量化阶段再接入）
        "last_updated": last.updated_at if last else None,
    })


# ---- Guided ----


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def guided_session(request, task_id):
    session = services.get_or_create_guided_session(task_id)
    return Response(GuidedSessionSerializer(session).data)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def guided_messages(request, task_id):
    if request.method == "POST":
        return guided_send_message(request, task_id)

    qp = request.query_params
    page = int(qp.get("page", 1))
    page_size = int(qp.get("page_size", 50))
    session = services.get_or_create_guided_session(task_id)
    msgs = ChatMessage.objects.filter(session=session).order_by("timestamp")
    total = msgs.count()
    start = (page - 1) * page_size
    items = list(msgs[start : start + page_size])
    return Response({
        "messages": ChatMessageSerializer(items, many=True).data,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def guided_stage(request, task_id):
    session = services.get_or_create_guided_session(task_id)
    stage = request.data.get("stage")
    valid = ("briefing", "recon", "enumeration", "vuln_analysis", "exploit", "post_exploit", "summary")
    if stage not in valid:
        return Response({"detail": "无效的阶段"}, status=400)
    session.current_stage = stage
    session.save()
    return Response(GuidedSessionSerializer(session).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def guided_send_message(request, task_id):
    """发送消息并流式返回 AI 回复 (SSE)"""
    import json

    from django.http import StreamingHttpResponse

    content = (request.data or {}).get("content")
    if not content:
        return Response({"detail": "content 必填"}, status=400)

    try:
        ai_content, cmd = services.guided_reply(task_id, content)
    except ValueError:
        return Response({"detail": "任务不存在"}, status=404)

    def sse_stream():
        for i in range(0, len(ai_content), 20):
            chunk = ai_content[i : i + 20]
            yield f"data: {json.dumps({'type': 'text', 'content': chunk}, ensure_ascii=False)}\n\n"
        if cmd:
            yield f"data: {json.dumps({'type': 'command', 'command': cmd}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    resp = StreamingHttpResponse(sse_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp
