from rest_framework.decorators import api_view
from rest_framework.response import Response
import os
import json
from .models import InspectionConfig, InspectionReport
from .engine import inspection_engine

@api_view(['GET', 'POST'])
def inspection_config(request):
    if request.method == 'GET':
        cfg = InspectionConfig.load()
        return Response({
            "prometheus_url": cfg.prometheus_url,
            "ark_base_url": cfg.ark_base_url,
            "ark_api_key": cfg.ark_api_key,
            "ark_model_id": cfg.ark_model_id
        })
    elif request.method == 'POST':
        data = request.data
        cfg = InspectionConfig.load()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        cfg.save()
        return Response({"msg": "saved"})

@api_view(['POST'])
def run_inspection(request):
    # Update config if provided
    data = request.data
    if data:
        cfg = InspectionConfig.load()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        cfg.save()
        # Refresh engine config
        inspection_engine.config = cfg
        
    report = inspection_engine.run()
    return Response(report)

@api_view(['GET'])
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
def history(request):
    # Get IDs from DB
    db_items = list(InspectionReport.objects.values_list('report_id', flat=True))
    
    # Get IDs from file
    file_items = []
    path = 'state/inspection_reports/daily'
    if os.path.exists(path):
        file_items = [f.replace('.json', '') for f in os.listdir(path) if f.endswith('.json')]
    
    # Merge and sort
    all_items = sorted(list(set(db_items + file_items)), reverse=True)
    return Response({"items": all_items})
