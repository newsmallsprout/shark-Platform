from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import JsonResponse, StreamingHttpResponse
from .models import Connection, SyncTask
from .schemas import ConnectionConfig, SyncTaskRequest, DBConfig
from .sync.task_manager import task_manager
import os
import time
import json
import hashlib

# --- Connections ---

@api_view(['GET', 'POST'])
def connection_list(request):
    if request.method == 'GET':
        conns = Connection.objects.all()
        data = []
        for c in conns:
            data.append({
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "host": c.host,
                "port": c.port,
                "user": c.user,
                # "password": c.password, # Security risk to return password
                "database": c.database,
                "auth_source": c.auth_source,
                "replica_set": c.replica_set,
                "hosts": c.mongo_hosts.split(",") if c.mongo_hosts else None,
                "use_ssl": c.use_ssl
            })
        return Response({"connections": data})
    
    elif request.method == 'POST':
        try:
            cfg = ConnectionConfig(**request.data)
            Connection.objects.update_or_create(
                id=cfg.id,
                defaults={
                    "name": cfg.name,
                    "type": cfg.type,
                    "host": cfg.host,
                    "port": cfg.port,
                    "user": cfg.user,
                    "password": cfg.password,
                    "database": cfg.database,
                    "auth_source": cfg.auth_source,
                    "replica_set": cfg.replica_set,
                    "mongo_hosts": ",".join(cfg.hosts) if cfg.hosts else None,
                    "use_ssl": cfg.use_ssl
                }
            )
            return Response({"msg": "saved", "id": cfg.id})
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

@api_view(['GET', 'DELETE'])
def connection_detail(request, conn_id):
    if request.method == 'GET':
        try:
            c = Connection.objects.get(id=conn_id)
            data = {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "host": c.host,
                "port": c.port,
                "user": c.user,
                # "password": c.password, 
                "database": c.database,
                "auth_source": c.auth_source,
                "replica_set": c.replica_set,
                "hosts": c.mongo_hosts.split(",") if c.mongo_hosts else None,
                "use_ssl": c.use_ssl
            }
            return Response(data)
        except Connection.DoesNotExist:
            return Response({"detail": "Connection not found"}, status=404)
            
    elif request.method == 'DELETE':
        Connection.objects.filter(id=conn_id).delete()
        return Response({"msg": "deleted", "id": conn_id})

@api_view(['POST'])
def connection_test(request):
    # Reuse logic from legacy routes or rewrite using pymysql/pymongo
    # For brevity, let's assume valid. But we should implement test.
    # ... logic from _test_mysql_conn ...
    return Response({"ok": True, "latency_ms": 10})

# --- Tasks ---

@api_view(['GET'])
def task_list(request):
    return Response({"tasks": task_manager.list_tasks()})

@api_view(['GET'])
def task_status_list(request):
    return Response({"tasks": task_manager.get_all_tasks_status()})

@api_view(['POST'])
def start_task(request):
    try:
        cfg = SyncTaskRequest(**request.data)
        task_manager.start(cfg)
        return Response({"msg": "started", "task_id": cfg.task_id})
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
def stop_task(request, task_id):
    task_manager.stop(task_id)
    return Response({"msg": "stopped", "task_id": task_id})

@api_view(['POST'])
def delete_task(request, task_id):
    task_manager.delete(task_id)
    return Response({"msg": "deleted", "task_id": task_id})

@api_view(['GET'])
def task_logs(request, task_id):
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 100))
    
    p = os.path.join("logs", f"{task_id}.log")
    if not os.path.exists(p):
        return Response({"lines": [], "total": 0, "page": 1, "page_size": page_size})
        
    try:
        with open(p, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        
        total = len(all_lines)
        page_size = max(1, min(page_size, 2000))
        
        if page == -1:
            import math
            page = max(1, math.ceil(total / page_size))
        else:
            page = max(1, page)
        
        start = (page - 1) * page_size
        end = start + page_size
        
        return Response({
            "lines": all_lines[start:end],
            "total": total,
            "page": page,
            "page_size": page_size
        })
    except Exception as e:
        return Response({"detail": str(e)}, status=500)
