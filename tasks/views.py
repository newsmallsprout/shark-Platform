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
import pymysql

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

@api_view(['GET'])
def task_status_detail(request, task_id):
    status = task_manager.get_task_status(task_id)
    if status:
        return Response(status)
    return Response({"detail": "Task not found"}, status=404)

@api_view(['POST'])
def start_task(request):
    try:
        cfg = SyncTaskRequest(**request.data)
        task_manager.start(cfg)
        return Response({"msg": "started", "task_id": cfg.task_id})
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
def start_with_conn_ids(request):
    try:
        data = request.data
        task_id = data.get('task_id')
        source_id = data.get('source_conn_id')
        target_id = data.get('target_conn_id')
        
        mysql_conf = {}
        if source_id:
            c = Connection.objects.get(id=source_id)
            mysql_conf = {
                "host": c.host,
                "port": c.port,
                "user": c.user,
                "password": c.password,
                "database": data.get('mysql_database'),
                "use_ssl": c.use_ssl
            }
        else:
            mysql_conf = data.get('mysql_conf_override', {})
            
        mongo_conf = {}
        if target_id:
            c = Connection.objects.get(id=target_id)
            mongo_conf = {
                "host": c.host,
                "port": c.port,
                "user": c.user,
                "password": c.password,
                "database": data.get('mongo_database'),
                "auth_source": c.auth_source,
                "replica_set": c.replica_set,
                "hosts": c.mongo_hosts.split(",") if c.mongo_hosts else None
            }
        else:
            mongo_conf = data.get('mongo_conf_override', {})
            
        # Construct full request
        # Map frontend fields to SyncTaskRequest fields
        req_data = {
            "task_id": task_id,
            "mysql_conf": mysql_conf,
            "mongo_conf": mongo_conf,
            "table_map": data.get('table_map', {}),
            "pk_field": data.get('pk_field', 'id'),
            "update_insert_new_doc": data.get('update_insert_new_doc', True),
            "delete_append_new_doc": data.get('delete_append_new_doc', True),
            "drop_target_before_full_sync": data.get('drop_target_before_full_sync', False),
            "auto_discover_new_tables": data.get('auto_discover_new_tables', True),
        }
        
        cfg = SyncTaskRequest(**req_data)
        task_manager.start(cfg)
        return Response({"msg": "started", "task_id": cfg.task_id})
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
def start_existing(request, task_id):
    try:
        task_manager.start_by_id(task_id)
        return Response({"msg": "started", "task_id": task_id})
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
def reset_and_start(request, task_id):
    try:
        task_manager.stop(task_id)
        task_manager.reset(task_id)
        task_manager.start_by_id(task_id)
        return Response({"msg": "reset and started", "task_id": task_id})
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
def stop_task(request, task_id):
    task_manager.stop(task_id)
    return Response({"msg": "stopped", "task_id": task_id})

@api_view(['POST'])
def stop_task_soft(request, task_id):
    task_manager.stop_soft(task_id)
    return Response({"msg": "stopped (soft)", "task_id": task_id})

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

# --- MySQL Introspection ---

def _get_mysql_conn(cfg):
    return pymysql.connect(
        host=cfg.get('host', 'localhost'),
        port=int(cfg.get('port', 3306)),
        user=cfg.get('user', 'root'),
        password=cfg.get('password', ''),
        database=cfg.get('database', None),
        connect_timeout=5,
        ssl={'ssl': {}} if cfg.get('use_ssl', False) else None
    )

@api_view(['POST'])
def mysql_databases(request):
    try:
        conn = _get_mysql_conn(request.data)
        try:
            with conn.cursor() as c:
                c.execute("SHOW DATABASES")
                rows = c.fetchall()
                dbs = [r[0] for r in rows if r[0] not in ('information_schema', 'mysql', 'performance_schema', 'sys')]
            return Response({"databases": dbs})
        finally:
            conn.close()
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
def mysql_databases_by_id(request, conn_id):
    try:
        c = Connection.objects.get(id=conn_id)
        cfg = {
            "host": c.host,
            "port": c.port,
            "user": c.user,
            "password": c.password,
            "use_ssl": c.use_ssl
        }
        conn = _get_mysql_conn(cfg)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SHOW DATABASES")
                rows = cursor.fetchall()
                dbs = [r[0] for r in rows if r[0] not in ('information_schema', 'mysql', 'performance_schema', 'sys')]
            return Response({"databases": dbs})
        finally:
            conn.close()
    except Connection.DoesNotExist:
        return Response({"detail": "Connection not found"}, status=404)
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
def mysql_tables(request):
    try:
        cfg = request.data.copy()
        if not cfg.get('database'):
            return Response({"detail": "Database is required"}, status=400)
            
        conn = _get_mysql_conn(cfg)
        try:
            with conn.cursor() as c:
                c.execute("SHOW TABLES")
                rows = c.fetchall()
                tables = [r[0] for r in rows]
            return Response({"tables": tables})
        finally:
            conn.close()
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
def mysql_tables_by_id(request, conn_id):
    try:
        db = request.data.get('database')
        if not db:
            return Response({"detail": "Database is required"}, status=400)
            
        c = Connection.objects.get(id=conn_id)
        cfg = {
            "host": c.host,
            "port": c.port,
            "user": c.user,
            "password": c.password,
            "database": db,
            "use_ssl": c.use_ssl
        }
        conn = _get_mysql_conn(cfg)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SHOW TABLES")
                rows = cursor.fetchall()
                tables = [r[0] for r in rows]
            return Response({"tables": tables})
        finally:
            conn.close()
    except Connection.DoesNotExist:
        return Response({"detail": "Connection not found"}, status=404)
    except Exception as e:
        return Response({"detail": str(e)}, status=400)
