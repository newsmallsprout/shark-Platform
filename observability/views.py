from __future__ import annotations

import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .aggregate import summarize_stream, traffic_visual_extras
from .models import LogInsight, LogStream
from .pipeline import run_observability_pipeline_impl
from .tasks import run_observability_pipeline

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def stream_list(request):
    rows = LogStream.objects.all()[:200]
    return Response(
        {
            "streams": [
                {
                    "stream_key": s.stream_key,
                    "display_name": s.display_name or s.stream_key,
                    "last_event_at": s.last_event_at.isoformat()
                    if s.last_event_at
                    else None,
                }
                for s in rows
            ]
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def traffic_summary(request):
    sk = (request.GET.get("stream_key") or "").strip()[:128]
    if not sk:
        first = LogStream.objects.order_by("-last_event_at").first()
        if not first:
            return Response(
                {
                    "stream_key": None,
                    "summary": None,
                    "hint": "尚无日志流；请用 go-log-collector 推送并携带 stream_key / log_format。",
                }
            )
        sk = first.stream_key
    try:
        minutes = int(request.GET.get("minutes") or "60")
    except ValueError:
        minutes = 60
    minutes = max(5, min(minutes, 24 * 60))
    summary = summarize_stream(sk, window_minutes=minutes)
    payload = summary.to_dict()
    payload.update(traffic_visual_extras(sk, minutes))
    return Response({"stream_key": sk, "summary": payload})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def insight_list(request):
    sk = (request.GET.get("stream_key") or "").strip()[:128]
    qs = LogInsight.objects.all()
    if sk:
        qs = qs.filter(stream_key=sk)
    lim = int(request.GET.get("limit") or "30")
    lim = max(1, min(lim, 100))
    rows = qs[:lim]
    return Response(
        {
            "insights": [
                {
                    "id": str(x.pk),
                    "stream_key": x.stream_key,
                    "insight_type": x.insight_type,
                    "severity": x.severity,
                    "title": x.title,
                    "body": x.body,
                    "evidence": x.evidence,
                    "source": x.source,
                    "created_at": x.created_at.isoformat(),
                }
                for x in rows
            ]
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def traffic_analyze(request):
    """触发异步流水线：规则 + LLM（若已配置 AI）。"""
    data = request.data if isinstance(request.data, dict) else {}
    sk = str(data.get("stream_key") or "").strip()[:128]
    if not sk:
        return Response({"error": "stream_key required"}, status=400)
    try:
        minutes = int(data.get("window_minutes") or 60)
    except (TypeError, ValueError):
        minutes = 60

    prefer_async = request.GET.get("async", "1") != "0"
    if prefer_async:
        try:
            run_observability_pipeline.delay(sk, window_minutes=minutes)
            return Response(
                {
                    "status": "queued",
                    "stream_key": sk,
                    "window_minutes": minutes,
                }
            )
        except Exception as e:
            logger.warning("celery delay failed, sync fallback: %s", e)
    result = run_observability_pipeline_impl(sk, window_minutes=minutes)
    return Response({"status": "completed", **result})
