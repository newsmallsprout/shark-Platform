from datetime import datetime, timedelta

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from api.views import HasRolePermission
import os
import json
from .models import InspectionConfig, InspectionReport
from .engine import inspection_engine


def _redact_inspection_config(cfg: InspectionConfig) -> dict:
    key = (cfg.ark_api_key or "").strip()
    return {
        "prometheus_url": cfg.prometheus_url,
        "ark_base_url": cfg.ark_base_url,
        "ark_api_key": "",
        "ark_api_key_set": bool(key),
        "ark_model_id": cfg.ark_model_id,
    }


def _apply_inspection_config(data: dict, cfg: InspectionConfig) -> None:
    for k, v in data.items():
        if k == "ark_api_key" and (v is None or str(v).strip() == ""):
            continue
        if hasattr(cfg, k):
            setattr(cfg, k, v)


@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def inspection_config(request):
    if request.method == 'GET':
        cfg = InspectionConfig.load()
        return Response(_redact_inspection_config(cfg))
    elif request.method == 'POST':
        data = request.data
        cfg = InspectionConfig.load()
        _apply_inspection_config(data, cfg)
        cfg.save()
        return Response({"msg": "saved"})

@api_view(['POST'])
@permission_classes([HasRolePermission])
def run_inspection(request):
    # Update config if provided
    data = request.data
    if data:
        cfg = InspectionConfig.load()
        _apply_inspection_config(data, cfg)
        cfg.save()
        # Refresh engine config
        inspection_engine.config = cfg
        
    report = inspection_engine.run()
    return Response(report)

@api_view(['GET'])
@permission_classes([HasRolePermission])
def get_report(request, report_id):
    # Try DB first
    try:
        report = InspectionReport.objects.get(report_id=report_id)
        return Response(report.content)
    except InspectionReport.DoesNotExist:
        # Fallback to file for backward compatibility
        path = f'state/inspection_reports/daily/{report_id}.json'
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return Response(json.load(f))
        return Response({"error": "Report not found"}, status=404)

@api_view(['GET'])
@permission_classes([HasRolePermission])
def history(request):
    # Get all reports from DB
    reports = InspectionReport.objects.all().order_by('-report_id')
    
    results = []
    for r in reports:
        content = r.content
        health = content.get('health_summary', {}) or content.get('risk_summary', {})
        health_score = health.get('score', 0)
            
        results.append({
            "report_id": r.report_id,
            "score": health_score,
            "summary": content.get('ai_analysis', '')[:100] + '...' if content.get('ai_analysis') else 'No analysis available'
        })
    
    # Handle legacy file items if any
    db_ids = [r.report_id for r in reports]
    path = 'state/inspection_reports/daily'
    if os.path.exists(path):
        for f in os.listdir(path):
            if f.endswith('.json'):
                rid = f.replace('.json', '')
                if rid not in db_ids:
                    with open(os.path.join(path, f), 'r', encoding='utf-8') as f_in:
                        try:
                            content = json.load(f_in)
                            health = content.get('health_summary', {}) or content.get('risk_summary', {})
                            health_score = health.get('score', 0)
                            
                            results.append({
                                "report_id": rid,
                                "score": health_score,
                                "summary": content.get('ai_analysis', '')[:100] + '...' if content.get('ai_analysis') else 'No analysis available'
                            })
                        except:
                            pass
    
    # Sort results by report_id desc
    results.sort(key=lambda x: x['report_id'], reverse=True)
    return Response({"items": results})

@api_view(['GET'])
@permission_classes([HasRolePermission])
def get_aggregated_report(request):
    rtype = request.query_params.get('type', 'weekly') # weekly, monthly
    days = 30 if rtype == 'monthly' else 7
    
    today = datetime.now().date()
    start_date = today - timedelta(days=days)
    
    reports = InspectionReport.objects.filter(
        report_id__gte=start_date.strftime('%Y-%m-%d'),
        report_id__lte=today.strftime('%Y-%m-%d')
    ).order_by('report_id')
    
    if not reports:
        return Response({"error": "No data available for this period"}, status=404)
        
    # Aggregation Logic
    total_score = 0
    count = 0
    scores_trend = []
    common_issues = {}
    
    for r in reports:
        content = r.content
        health = content.get('health_summary', {}) or content.get('risk_summary', {})
        health_score = health.get('score', 0)
        reasons = health.get('reasons', [])
            
        total_score += health_score
        count += 1
        scores_trend.append({"date": r.report_id, "score": health_score})
        
        # Count issues
        for reason in reasons:
            if reason not in ["System Healthy", "resource_max=OK"]:
                common_issues[reason] = common_issues.get(reason, 0) + 1
                
    avg_score = round(total_score / count, 1) if count > 0 else 0
    sorted_issues = sorted(common_issues.items(), key=lambda x: x[1], reverse=True)[:5]
    
    return Response({
        "type": rtype,
        "start_date": start_date.strftime('%Y-%m-%d'),
        "end_date": today.strftime('%Y-%m-%d'),
        "average_score": avg_score,
        "report_count": count,
        "trend": scores_trend,
        "top_issues": [{"issue": k, "count": v} for k, v in sorted_issues]
    })
