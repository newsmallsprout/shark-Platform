from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import InspectionConfig

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
    return Response({"msg": "started", "report_id": "dummy"})

@api_view(['GET'])
def get_report(request, report_id):
    return Response({"id": report_id, "content": "Dummy Report"})

@api_view(['GET'])
def history(request):
    return Response({"reports": []})
