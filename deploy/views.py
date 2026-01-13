from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import JsonResponse
from .models import Server, DeployPlan
from .schemas import DeployRequestSchema, ServerConfigSchema
from .engine import deploy_engine
import json

@api_view(['GET', 'POST'])
def server_list(request):
    if request.method == 'GET':
        servers = Server.objects.all()
        data = []
        for s in servers:
            data.append({
                "id": s.id,
                "name": s.name,
                "host": s.host,
                "port": s.port,
                "user": s.user,
                "auth_method": s.auth_method,
                "password": s.password,
                "key_path": s.key_path
            })
        return Response({"servers": data})
    
    elif request.method == 'POST':
        try:
            data = request.data
            # Basic validation using schema
            schema = ServerConfigSchema(**data)
            
            server, created = Server.objects.update_or_create(
                id=schema.id,
                defaults={
                    "name": schema.name,
                    "host": schema.host,
                    "port": schema.port,
                    "user": schema.user,
                    "auth_method": schema.auth_method,
                    "password": schema.password,
                    "key_path": schema.key_path
                }
            )
            return Response({"status": "ok", "id": server.id})
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
def run_deploy(request):
    try:
        # Validate request
        req = DeployRequestSchema(**request.data)
        plan = deploy_engine.run(req)
        
        # Return plan data
        # We can construct the response manually or use a serializer
        plan_data = {
            "id": plan.id,
            "req": plan.req,
            "artifacts": plan.artifacts,
            "commands": plan.commands,
            "requirements": plan.requirements,
            "targets": plan.targets,
            "logs": plan.logs,
            "progress": plan.progress,
            "status": plan.status,
            "error": plan.error,
        }
        return Response({"status": "ok", "plan": plan_data})
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
def execute_plan(request, plan_id):
    deploy_engine.execute_async(plan_id)
    return Response({"status": "ok"})

@api_view(['GET'])
def get_plan(request, plan_id):
    try:
        plan = DeployPlan.objects.get(id=plan_id)
        plan_data = {
            "id": plan.id,
            "req": plan.req,
            "artifacts": plan.artifacts,
            "commands": plan.commands,
            "requirements": plan.requirements,
            "targets": plan.targets,
            "logs": plan.logs,
            "progress": plan.progress,
            "status": plan.status,
            "error": plan.error,
        }
        return Response(plan_data)
    except DeployPlan.DoesNotExist:
        return Response({"detail": "Plan not found"}, status=404)
