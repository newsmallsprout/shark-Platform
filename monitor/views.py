from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import MonitorConfig

@api_view(['GET', 'POST'])
def monitor_config(request):
    if request.method == 'GET':
        cfg = MonitorConfig.load()
        return Response({
            "enabled": cfg.enabled,
            "es_hosts": cfg.es_hosts,
            "es_username": cfg.es_username,
            "es_password": cfg.es_password,
            "index_pattern": cfg.index_pattern,
            "slack_webhook_url": cfg.slack_webhook_url,
            "poll_interval_seconds": cfg.poll_interval_seconds,
            "alert_keywords": cfg.alert_keywords,
            "ignore_keywords": cfg.ignore_keywords,
            "record_only_keywords": cfg.record_only_keywords
        })
    elif request.method == 'POST':
        data = request.data
        cfg = MonitorConfig.load()
        cfg.enabled = data.get("enabled", cfg.enabled)
        cfg.es_hosts = data.get("es_hosts", cfg.es_hosts)
        # ... map all fields ...
        # For brevity, I'll just save what's passed if matches model
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        cfg.save()
        return Response({"msg": "saved"})

@api_view(['GET'])
def monitor_status(request):
    # Stub status
    return Response({
        "status": "stopped", 
        "last_run": None,
        "last_error": None,
        "alerts_sent": 0,
        "config": {},
        "levels": {}
    })

@api_view(['POST'])
def monitor_start(request):
    return Response({"msg": "started"})

@api_view(['POST'])
def monitor_stop(request):
    return Response({"msg": "stopped"})
