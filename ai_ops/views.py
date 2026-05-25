from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from .models import Incident, AnalysisReport, AIConfig

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def ai_config(request):
    if request.method == 'GET':
        config = AIConfig.get_active_config()
        return Response({
            "provider": config.provider,
            "api_base": config.api_base,
            "api_key": config.api_key,
            "model": config.model,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "prompt_template": config.prompt_template
        })
    elif request.method == 'POST':
        config = AIConfig.get_active_config()
        data = request.data
        config.provider = data.get('provider', config.provider)
        config.api_base = data.get('api_base', config.api_base)
        config.api_key = data.get('api_key', config.api_key)
        config.model = data.get('model', config.model)
        config.max_tokens = int(data.get('max_tokens', config.max_tokens))
        config.temperature = float(data.get('temperature', config.temperature))
        config.prompt_template = data.get('prompt_template', config.prompt_template)
        config.save()
        return Response({"msg": "Configuration updated"})
from .services.analyzer import FaultAnalyzer
import json
import logging
from django.utils import timezone
import threading
import hashlib

logger = logging.getLogger(__name__)

def get_alert_fingerprint(alert):
    if 'fingerprint' in alert:
        return alert['fingerprint']
    
    labels = alert.get('labels', {})
    label_str = json.dumps(labels, sort_keys=True)
    return hashlib.md5(label_str.encode('utf-8')).hexdigest()

@api_view(['POST'])
@permission_classes([AllowAny]) # Prometheus Webhook usually doesn't have auth, or uses Basic Auth (handled by middleware if configured)
def prometheus_webhook(request):
    """
    Receiver for Prometheus Alertmanager Webhook
    Payload example:
    {
      "alerts": [
        {
          "status": "firing",
          "labels": { "alertname": "HighCPU", "instance": "server1" },
          "startsAt": "2024-01-01T10:00:00Z"
        }
      ]
    }
    """
    try:
        data = request.data
        alerts = data.get('alerts', [])
        
        for alert in alerts:
            status = alert.get('status')
            labels = alert.get('labels', {})
            alert_name = labels.get('alertname', 'Unknown Alert')
            severity = labels.get('severity', 'warning')
            fingerprint = get_alert_fingerprint(alert)
            
            # Handle Resolution
            if status == 'resolved':
                Incident.objects.filter(
                    fingerprint=fingerprint,
                    status__in=['open', 'analyzing', 'analyzed']
                ).update(
                    status='resolved',
                    resolved_at=timezone.now()
                )
                logger.info(f"Alert resolved: {alert_name} ({fingerprint})")
                continue

            if status != 'firing':
                continue
            
            # Handle Firing
            # Find existing active incident
            incident = Incident.objects.filter(
                fingerprint=fingerprint
            ).exclude(status='resolved').first()
            
            should_analyze = False
            
            if incident:
                # Deduplicate
                incident.occurrence_count += 1
                
                # Check throttle (1 hour)
                if incident.last_analyzed_at:
                    time_since_analysis = timezone.now() - incident.last_analyzed_at
                    if time_since_analysis.total_seconds() > 3600:
                        should_analyze = True
                else:
                    # Never analyzed (e.g. created before migration or failed previously)
                    should_analyze = True
                
                incident.save()
                logger.info(f"Alert duplicated: {alert_name} ({fingerprint}), count: {incident.occurrence_count}")
            else:
                # Create New Incident
                incident = Incident.objects.create(
                    alert_name=alert_name,
                    severity=severity,
                    started_at=alert.get('startsAt', timezone.now()),
                    description=alert.get('annotations', {}).get('description', ''),
                    raw_alert_data=alert,
                    fingerprint=fingerprint,
                    occurrence_count=1
                )
                should_analyze = True
                logger.info(f"New incident created: {alert_name} ({fingerprint})")
            
            # Trigger Analysis if needed
            if should_analyze:
                # Update timestamp immediately
                incident.last_analyzed_at = timezone.now()
                incident.save(update_fields=['last_analyzed_at'])
                
                def run_analysis(inc):
                    analyzer = FaultAnalyzer(inc)
                    analyzer.analyze()
                    
                threading.Thread(target=run_analysis, args=(incident,)).start()
            
        return Response({"msg": "Alerts received", "count": len(alerts)})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def incident_list(request):
    cutoff = timezone.now() - timezone.timedelta(days=7)
    Incident.objects.filter(status='resolved', resolved_at__isnull=False, resolved_at__lt=cutoff).delete()

    incidents = Incident.objects.exclude(status='resolved').order_by('-created_at')
    data = []
    for inc in incidents:
        data.append({
            "id": inc.id,
            "alert_name": inc.alert_name,
            "severity": inc.severity,
            "status": inc.status,
            "started_at": inc.started_at,
            "created_at": inc.created_at
        })
    return Response({"incidents": data})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def incident_detail(request, pk):
    try:
        incident = Incident.objects.get(pk=pk)
        report = None
        if hasattr(incident, 'report'):
            report = {
                "phenomenon": incident.report.phenomenon,
                "root_cause": incident.report.root_cause,
                "mitigation": incident.report.mitigation,
                "prevention": incident.report.prevention,
                "refactoring": incident.report.refactoring,
                "solutions": incident.report.solutions,
                "related_metrics": incident.report.related_metrics,
                "created_at": incident.report.created_at
            }
            
        return Response({
            "id": incident.id,
            "alert_name": incident.alert_name,
            "severity": incident.severity,
            "status": incident.status,
            "description": incident.description,
            "raw_alert_data": incident.raw_alert_data,
            "report": report
        })
    except Incident.DoesNotExist:
        return Response({"error": "Incident not found"}, status=404)
