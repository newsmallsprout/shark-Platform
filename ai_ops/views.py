import hashlib
import hmac
import json
import logging
import uuid
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db.models import Count, DateTimeField
from django.db.models.functions import Coalesce, TruncHour
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core.permissions import AiOpsOpsPermission

from .models import AIConfig, Incident, KnowledgeEntry, Ticket, TopologySnapshot
from .brain.ticket_manager import TicketManager
from .tasks import run_incident_langgraph

logger = logging.getLogger(__name__)


def _parse_starts_at(alert: dict):
    raw = alert.get("startsAt")
    if not raw:
        return None
    s = str(raw).replace("Z", "+00:00")
    dt = parse_datetime(s)
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def get_alert_fingerprint(alert):
    if "fingerprint" in alert:
        return alert["fingerprint"]

    labels = alert.get("labels", {})
    label_str = json.dumps(labels, sort_keys=True)
    return hashlib.md5(label_str.encode("utf-8")).hexdigest()


def _webhook_bearer_ok(request) -> bool:
    secret = (getattr(settings, "AIOPS_WEBHOOK_BEARER_TOKEN", "") or "").strip()
    if not secret:
        return True
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip(), secret):
        return True
    tok = (request.headers.get("X-Shark-Webhook-Token") or "").strip()
    return bool(tok) and hmac.compare_digest(tok, secret)


def _webhook_hmac_ok(request) -> bool:
    key = (getattr(settings, "AIOPS_WEBHOOK_HMAC_SECRET", "") or "").strip()
    if not key:
        return True
    body = request.body or b""
    expected = hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
    hdr = (request.headers.get("X-Shark-Signature") or request.headers.get("X-Hub-Signature-256") or "").strip()
    if not hdr:
        return False
    if hdr.startswith("sha256="):
        hdr = hdr[7:].strip()
    return hmac.compare_digest(hdr, expected)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, AiOpsOpsPermission])
def ai_config(request):
    if request.method == "GET":
        config = AIConfig.get_active_config()
        return Response(
            {
                "provider": config.provider,
                "api_base": config.api_base,
                "api_key": config.api_key,
                "model": config.model,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "prompt_template": config.prompt_template,
                "final_prompt_template": config.final_prompt_template,
                "enable_ai_analysis": config.enable_ai_analysis,
                "max_agent_iterations": config.max_agent_iterations,
                "max_tool_calls_per_incident": config.max_tool_calls_per_incident,
            }
        )
    config = AIConfig.get_active_config()
    data = request.data
    config.provider = data.get("provider", config.provider)
    config.api_base = data.get("api_base", config.api_base)
    config.api_key = data.get("api_key", config.api_key)
    config.model = data.get("model", config.model)
    config.max_tokens = int(data.get("max_tokens", config.max_tokens))
    config.temperature = float(data.get("temperature", config.temperature))
    config.prompt_template = data.get("prompt_template", config.prompt_template)
    config.final_prompt_template = data.get(
        "final_prompt_template", config.final_prompt_template
    )
    if "enable_ai_analysis" in data:
        config.enable_ai_analysis = bool(data.get("enable_ai_analysis"))
    if "max_agent_iterations" in data:
        config.max_agent_iterations = int(data.get("max_agent_iterations", 12))
    if "max_tool_calls_per_incident" in data:
        config.max_tool_calls_per_incident = int(
            data.get("max_tool_calls_per_incident", 36)
        )
    config.save()
    return Response({"msg": "Configuration updated"})


@api_view(["POST"])
@permission_classes([AllowAny])
def prometheus_webhook(request):
    """
    Receiver for Prometheus Alertmanager Webhook
    """
    try:
        if not _webhook_bearer_ok(request):
            return Response({"error": "unauthorized"}, status=401)
        if not _webhook_hmac_ok(request):
            return Response({"error": "invalid webhook signature"}, status=401)

        data = request.data
        alerts = data.get("alerts", [])

        for alert in alerts:
            status = alert.get("status")
            labels = alert.get("labels", {})
            alert_name = labels.get("alertname", "Unknown Alert")
            severity = labels.get("severity", "warning")
            fingerprint = get_alert_fingerprint(alert)

            if status == "resolved":
                Incident.objects.filter(
                    fingerprint=fingerprint,
                    status__in=["open", "analyzing", "analyzed"],
                ).update(status="resolved", resolved_at=timezone.now())
                logger.info(f"Alert resolved: {alert_name} ({fingerprint})")
                continue

            if status != "firing":
                continue

            now = timezone.now()
            starts_at = _parse_starts_at(alert) or now
            ann = alert.get("annotations", {}) or {}
            desc = ann.get("description", "") if isinstance(ann, dict) else ""

            incident = Incident.objects.filter(fingerprint=fingerprint).exclude(
                status="resolved"
            ).first()

            should_analyze = False

            if incident:
                incident.occurrence_count += 1
                incident.last_received_at = now
                incident.started_at = starts_at
                incident.raw_alert_data = alert
                if desc:
                    incident.description = desc
                if incident.last_analyzed_at:
                    time_since_analysis = now - incident.last_analyzed_at
                    if time_since_analysis.total_seconds() > 3600:
                        should_analyze = True
                else:
                    should_analyze = True
                if (
                    not should_analyze
                    and incident.status == "analyzed"
                ):
                    try:
                        r = incident.report
                        if starts_at > r.created_at:
                            should_analyze = True
                    except ObjectDoesNotExist:
                        pass
                incident.save()
                logger.info(
                    f"Alert duplicated: {alert_name} ({fingerprint}), count: {incident.occurrence_count}"
                )
            else:
                incident = Incident.objects.create(
                    alert_name=alert_name,
                    severity=severity,
                    started_at=starts_at,
                    description=desc,
                    raw_alert_data=alert,
                    fingerprint=fingerprint,
                    occurrence_count=1,
                    last_received_at=now,
                )
                should_analyze = True
                logger.info(f"New incident created: {alert_name} ({fingerprint})")

            if should_analyze:
                incident.last_analyzed_at = now
                incident.save(update_fields=["last_analyzed_at"])

                run_id = str(uuid.uuid4())
                create_ticket = getattr(settings, "AIOPS_AUTO_CREATE_TICKET_ON_ALERT", True)
                run_incident_langgraph.delay(
                    incident.id,
                    run_id,
                    operator_context=None,
                    human_feedback=None,
                    trigger_source="webhook",
                    create_ticket=bool(create_ticket),
                )
                logger.info(
                    "Queued Celery diagnosis incident=%s run_id=%s create_ticket=%s",
                    incident.id,
                    run_id,
                    create_ticket,
                )

        return Response({"msg": "Alerts received", "count": len(alerts)})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([IsAuthenticated, AiOpsOpsPermission])
def incident_list(request):
    cutoff = timezone.now() - timezone.timedelta(days=7)
    Incident.objects.filter(
        status="resolved", resolved_at__isnull=False, resolved_at__lt=cutoff
    ).delete()

    incidents = (
        Incident.objects.exclude(status="resolved")
        .annotate(
            _activity=Coalesce(
                "last_received_at",
                "last_analyzed_at",
                "created_at",
                output_field=DateTimeField(),
            )
        )
        .order_by("-_activity", "-id")
    )
    data = []
    for inc in incidents:
        data.append(
            {
                "id": inc.id,
                "alert_name": inc.alert_name,
                "severity": inc.severity,
                "status": inc.status,
                "started_at": inc.started_at,
                "created_at": inc.created_at,
                "last_received_at": getattr(inc, "last_received_at", None),
                "occurrence_count": inc.occurrence_count,
            }
        )
    return Response({"incidents": data})


def _report_payload(report):
    return {
        "phenomenon": report.phenomenon,
        "root_cause": report.root_cause,
        "mitigation": report.mitigation,
        "prevention": report.prevention,
        "refactoring": report.refactoring,
        "platform_linkage": report.platform_linkage,
        "solutions": report.solutions,
        "related_metrics": report.related_metrics,
        "diagnosis_logs": report.diagnosis_logs,
        "k8s_events": report.k8s_events,
        "k8s_pod_status": report.k8s_pod_status,
        "created_at": report.created_at,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated, AiOpsOpsPermission])
def incident_detail(request, pk):
    try:
        incident = Incident.objects.get(pk=pk)
        report = None
        if hasattr(incident, "report"):
            report = _report_payload(incident.report)

        chart_metrics = None
        if report and report.get("related_metrics"):
            chart_metrics = report["related_metrics"]
        elif incident.prefetched_metrics:
            chart_metrics = incident.prefetched_metrics

        return Response(
            {
                "id": incident.id,
                "alert_name": incident.alert_name,
                "severity": incident.severity,
                "status": incident.status,
                "description": incident.description,
                "raw_alert_data": incident.raw_alert_data,
                "prefetched_metrics": incident.prefetched_metrics,
                "chart_metrics": chart_metrics,
                "report": report,
                "agent_trace": getattr(incident, "agent_trace", None) or [],
                "last_received_at": getattr(incident, "last_received_at", None),
                "occurrence_count": incident.occurrence_count,
            }
        )
    except Incident.DoesNotExist:
        return Response({"error": "Incident not found"}, status=404)


@api_view(["POST"])
@permission_classes([IsAuthenticated, AiOpsOpsPermission])
def diagnose_incident(request, incident_id=None):
    """
    一键触发 LangGraph+Celery 诊断：立即返回 run_id，客户端用 sse_stream_url 订阅事件流。
    - URL：POST ``/api/ai_ops/diagnose/<incident_id>/``，可选 JSON ``{"operator_context": "..."}``
    - 兼容：POST ``/api/ai_ops/diagnose/``，body ``{"incident_id": n, "operator_context": "..."}``
    """
    if incident_id is not None:
        try:
            iid = int(incident_id)
        except (TypeError, ValueError):
            return Response({"error": "incident_id 无效"}, status=400)
    else:
        raw_id = request.data.get("incident_id")
        if raw_id is None or raw_id == "":
            return Response({"error": "incident_id 必填"}, status=400)
        try:
            iid = int(raw_id)
        except (TypeError, ValueError):
            return Response({"error": "incident_id 必须为整数"}, status=400)

    if not Incident.objects.filter(pk=iid).exists():
        return Response({"error": "Incident 不存在"}, status=404)

    data = request.data if isinstance(request.data, dict) else {}
    operator_context = (data.get("operator_context") or "").strip() or None

    run_id = str(uuid.uuid4())
    run_incident_langgraph.delay(
        iid,
        run_id,
        operator_context=operator_context,
        human_feedback=None,
        trigger_source="manual",
        create_ticket=True,
    )

    base = getattr(settings, "AGENT_SSE_PUBLIC_BASE", "http://localhost:8010").rstrip("/")
    sse_stream_url = f"{base}/api/agent/stream/{run_id}"

    return Response(
        {
            "status": "processing",
            "run_id": run_id,
            "sse_stream_url": sse_stream_url,
        },
        status=200,
    )


def _ticket_payload(t: Ticket) -> dict:
    return {
        "ticket_id": str(t.ticket_id),
        "incident_id": t.incident_id,
        "run_id": t.run_id,
        "status": t.status,
        "summary": t.summary,
        "root_cause": t.root_cause,
        "proposed_action": t.proposed_action,
        "approval_comment": t.approval_comment,
        "approved_at": t.approved_at.isoformat() if t.approved_at else None,
        "executed_at": t.executed_at.isoformat() if t.executed_at else None,
        "ticket_class": getattr(t, "ticket_class", "reactive"),
        "impact_scope": getattr(t, "impact_scope", None) or {},
        "ai_confidence": float(getattr(t, "ai_confidence", 0) or 0),
        "routing": getattr(t, "routing", "") or "",
        "auto_heal_dispatched": bool(getattr(t, "auto_heal_dispatched", False)),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated, AiOpsOpsPermission])
def dashboard_summary(request):
    """Bento 大屏：健康分、拓扑、AI 状态、待办工单、近期自愈。"""
    topo = TopologySnapshot.objects.filter(scope="global").first()
    open_n = Incident.objects.exclude(status="resolved").count()
    analyzing = Incident.objects.filter(status="analyzing").exists()
    critical_open = Incident.objects.filter(
        severity="critical", status__in=["open", "analyzing", "awaiting_evidence"]
    ).exists()

    if topo:
        health = float(topo.health_score)
    else:
        health = max(20.0, 100.0 - open_n * 6.0)

    if critical_open:
        health = min(health, 55.0)

    def _tmini(x: Ticket):
        return {
            "ticket_id": str(x.ticket_id),
            "summary": (x.summary or "")[:120],
            "status": x.status,
            "routing": getattr(x, "routing", "") or "",
            "ai_confidence": float(getattr(x, "ai_confidence", 0) or 0),
        }

    pending = Ticket.objects.filter(status=Ticket.STATUS_PENDING_APPROVAL).order_by(
        "-updated_at"
    )[:10]
    pending_n = Ticket.objects.filter(status=Ticket.STATUS_PENDING_APPROVAL).count()
    heals = (
        Ticket.objects.filter(status=Ticket.STATUS_EXECUTED)
        .select_related("incident")
        .order_by("-executed_at")[:10]
    )

    mode = getattr(settings, "AIOPS_DEPLOYMENT_MODE", "unspecified")
    in_k8s = getattr(settings, "AIOPS_IN_KUBERNETES_POD", False)

    now = timezone.now()
    window_start = now - timedelta(hours=24)
    inc_by_bucket = {
        row["bucket"]: row["c"]
        for row in Incident.objects.filter(created_at__gte=window_start)
        .annotate(bucket=TruncHour("created_at"))
        .values("bucket")
        .annotate(c=Count("id"))
    }
    heal_by_bucket = {
        row["bucket"]: row["c"]
        for row in Ticket.objects.filter(
            status=Ticket.STATUS_EXECUTED,
            executed_at__isnull=False,
            executed_at__gte=window_start,
        )
        .annotate(bucket=TruncHour("executed_at"))
        .values("bucket")
        .annotate(c=Count("ticket_id"))
    }
    trend_labels: list[str] = []
    trend_incidents: list[int] = []
    trend_heals: list[int] = []
    for i in range(23, -1, -1):
        t_end = now - timedelta(hours=i)
        bucket = t_end.replace(minute=0, second=0, microsecond=0)
        trend_labels.append(t_end.strftime("%m-%d %H:00"))
        trend_incidents.append(inc_by_bucket.get(bucket, 0))
        trend_heals.append(heal_by_bucket.get(bucket, 0))

    sev_rows = (
        Incident.objects.exclude(status="resolved")
        .values("severity")
        .annotate(n=Count("id"))
    )
    severity_open = {"critical": 0, "warning": 0, "info": 0}
    for row in sev_rows:
        k = row.get("severity") or ""
        if k in severity_open:
            severity_open[k] = row["n"]

    nodes = topo.nodes if topo else []
    edges = topo.edges if topo else []
    healthy_nodes = sum(1 for x in nodes if isinstance(x, dict) and x.get("healthy") is not False)

    return Response(
        {
            "health_score": round(health, 1),
            "topology": {
                "nodes": nodes,
                "edges": edges,
            },
            "ai_status": "analyzing" if analyzing else ("degraded" if critical_open else "idle"),
            "open_incidents": open_n,
            "pending_approval_count": pending_n,
            "pending_tickets": [_tmini(t) for t in pending],
            "recent_heals": [
                {
                    "ticket_id": str(t.ticket_id),
                    "summary": (t.summary or "")[:100],
                    "executed_at": t.executed_at.isoformat() if t.executed_at else None,
                    "routing": getattr(t, "routing", "") or "",
                }
                for t in heals
            ],
            "knowledge_entries": KnowledgeEntry.objects.count(),
            "auto_heal_threshold": float(
                getattr(settings, "AIOPS_AUTO_HEAL_CONFIDENCE_THRESHOLD", 0.95)
            ),
            "deployment": {
                "mode": mode,
                "center_in_kubernetes_pod": in_k8s,
                "edge_heartbeat_expected": mode in ("physical", "hybrid"),
                "cluster_data_via_api": mode in ("kubernetes", "hybrid"),
            },
            "topology_stats": {
                "node_count": len(nodes),
                "edge_count": len(edges) if isinstance(edges, list) else 0,
                "healthy_nodes": healthy_nodes,
            },
            "severity_open": severity_open,
            "trends": {
                "granularity": "1h",
                "window_hours": 24,
                "labels": trend_labels,
                "incidents_new": trend_incidents,
                "tickets_executed": trend_heals,
            },
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, AiOpsOpsPermission])
def ticket_detail(request, ticket_id):
    try:
        tid = UUID(str(ticket_id))
    except ValueError:
        return Response({"error": "invalid ticket_id"}, status=400)
    try:
        t = Ticket.objects.select_related("incident").get(pk=tid)
    except Ticket.DoesNotExist:
        return Response({"error": "Ticket 不存在"}, status=404)
    return Response(_ticket_payload(t))


@api_view(["POST"])
@permission_classes([IsAuthenticated, AiOpsOpsPermission])
def ticket_submit(request, ticket_id):
    try:
        tid = UUID(str(ticket_id))
    except ValueError:
        return Response({"error": "invalid ticket_id"}, status=400)
    try:
        t = TicketManager.submit_for_approval(tid)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    return Response(_ticket_payload(t))


@api_view(["POST"])
@permission_classes([IsAuthenticated, AiOpsOpsPermission])
def ticket_approve(request, ticket_id):
    try:
        tid = UUID(str(ticket_id))
    except ValueError:
        return Response({"error": "invalid ticket_id"}, status=400)
    comment = (request.data.get("comment") or "") if isinstance(request.data, dict) else ""
    try:
        t = TicketManager.approve(tid, request.user, comment=comment)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    return Response(_ticket_payload(t))


@api_view(["POST"])
@permission_classes([IsAuthenticated, AiOpsOpsPermission])
def ticket_reject(request, ticket_id):
    try:
        tid = UUID(str(ticket_id))
    except ValueError:
        return Response({"error": "invalid ticket_id"}, status=400)
    reason = (request.data.get("reason") or "") if isinstance(request.data, dict) else ""
    reason = str(reason).strip()
    if not reason:
        return Response({"error": "驳回须填写 reason"}, status=400)
    try:
        t = TicketManager.reject(tid, request.user, reason=reason)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)

    new_run_id = str(uuid.uuid4())
    run_incident_langgraph.delay(
        t.incident_id,
        new_run_id,
        operator_context=None,
        human_feedback=reason,
        trigger_source="rejection_retry",
        create_ticket=True,
    )
    base = getattr(settings, "AGENT_SSE_PUBLIC_BASE", "http://localhost:8010").rstrip("/")
    new_sse_stream_url = f"{base}/api/agent/stream/{new_run_id}"

    return Response(
        {
            "status": "rejected",
            "new_run_id": new_run_id,
            "new_sse_stream_url": new_sse_stream_url,
            "ticket": _ticket_payload(t),
        },
        status=200,
    )
