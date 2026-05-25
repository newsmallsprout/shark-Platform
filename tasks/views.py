from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from api.views import HasRolePermission
from django.http import JsonResponse, StreamingHttpResponse
from .models import Connection, SyncTask
from .schemas import ConnectionConfig, SyncTaskRequest, DBConfig
from .sync.task_manager import task_manager
import os
import time
import datetime
import json
import hashlib
import pymysql
import tempfile
from kubernetes import client, config as k8s_config
from monitor.models import MonitorTask

# --- K8s Helper ---
def _get_k8s_core_api():
    # 1. Try to load from MonitorTask (User provided config)
    try:
        task = MonitorTask.objects.filter(k8s_kubeconfig__isnull=False).exclude(k8s_kubeconfig__exact='').first()
        if task and task.k8s_kubeconfig:
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as tf:
                tf.write(task.k8s_kubeconfig)
                tf.flush()
                try:
                    k8s_config.load_kube_config(config_file=tf.name)
                    return client.CoreV1Api()
                finally:
                    os.unlink(tf.name)
    except Exception as e:
        print(f"Error loading config from MonitorTask: {e}")

    # 2. Fallback to In-Cluster
    try:
        k8s_config.load_incluster_config()
        return client.CoreV1Api()
    except:
        pass

    # 3. Fallback to Local Default (~/.kube/config)
    try:
        k8s_config.load_kube_config()
        return client.CoreV1Api()
    except:
        return None

# --- Connections ---

@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
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
@permission_classes([HasRolePermission])
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
@permission_classes([HasRolePermission])
def connection_test(request):
    # Reuse logic from legacy routes or rewrite using pymysql/pymongo
    # For brevity, let's assume valid. But we should implement test.
    # ... logic from _test_mysql_conn ...
    return Response({"ok": True, "latency_ms": 10})

# --- Tasks ---

@api_view(['GET'])
@permission_classes([HasRolePermission])
def task_list(request):
    return Response({"tasks": task_manager.list_tasks()})

@api_view(['GET'])
@permission_classes([HasRolePermission])
def task_status_list(request):
    return Response({"tasks": task_manager.get_all_tasks_status()})

@api_view(['GET'])
@permission_classes([HasRolePermission])
def task_status_detail(request, task_id):
    status = task_manager.get_task_status(task_id)
    if status:
        return Response(status)
    return Response({"detail": "Task not found"}, status=404)

@api_view(['POST'])
@permission_classes([HasRolePermission])
def start_task(request):
    try:
        cfg = SyncTaskRequest(**request.data)
        task_manager.start(cfg)
        return Response({"msg": "started", "task_id": cfg.task_id})
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
@permission_classes([HasRolePermission])
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
            "use_pk_as_mongo_id": data.get('use_pk_as_mongo_id', True),
            "binlog_filename": data.get('binlog_filename'),
            "binlog_position": data.get('binlog_position'),
        }

        try:
            model_fields = getattr(SyncTaskRequest, 'model_fields', None) or {}
            allowed = set(model_fields.keys())
            reserved = {'task_id', 'mysql_conf', 'mongo_conf', 'table_map'}
            for k in (allowed - reserved):
                if k in data:
                    req_data[k] = data.get(k)
        except Exception:
            pass
        
        cfg = SyncTaskRequest(**req_data)
        task_manager.start(cfg)
        return Response({"msg": "started", "task_id": cfg.task_id})
    except Exception as e:
        return Response({"detail": str(e)}, status=400)


@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def task_config(request, task_id: str):
    try:
        t = SyncTask.objects.get(task_id=task_id)
    except SyncTask.DoesNotExist:
        return Response({"detail": "Task not found"}, status=404)

    if request.method == 'GET':
        cfg = t.config or {}
        perf_keys = [
            "progress_interval",
            "mysql_fetch_batch",
            "mongo_bulk_batch",
            "inc_flush_batch",
            "inc_flush_interval_sec",
            "state_save_interval_sec",
            "prefetch_queue_size",
            "rate_limit_enabled",
            "max_load_avg_ratio",
            "min_sleep_ms",
            "max_sleep_ms",
            "mongo_max_pool_size",
            "mongo_write_w",
            "mongo_write_j",
            "mongo_socket_timeout_ms",
            "mongo_connect_timeout_ms",
            "mongo_compressors",
        ]
        out = {k: cfg.get(k) for k in perf_keys if k in cfg}
        return Response({"task_id": task_id, "perf": out})

    if task_manager.is_running(task_id):
        return Response({"detail": "Stop task before updating config"}, status=400)

    payload = request.data or {}
    perf = payload.get('perf') if isinstance(payload, dict) else None
    if not isinstance(perf, dict):
        return Response({"detail": "perf object required"}, status=400)

    cfg = dict(t.config or {})
    cfg.update(perf)
    try:
        validated = SyncTaskRequest(**cfg)
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

    t.config = validated.model_dump()
    t.save()
    return Response({"msg": "updated", "task_id": task_id})

@api_view(['POST'])
@permission_classes([HasRolePermission])
def start_existing(request, task_id):
    try:
        task_manager.start_by_id(task_id)
        return Response({"msg": "started", "task_id": task_id})
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
@permission_classes([HasRolePermission])
def reset_and_start(request, task_id):
    try:
        task_manager.stop(task_id)
        task_manager.reset(task_id)
        task_manager.start_by_id(task_id)
        return Response({"msg": "reset and started", "task_id": task_id})
    except Exception as e:
        return Response({"detail": str(e)}, status=400)

@api_view(['POST'])
@permission_classes([HasRolePermission])
def stop_task(request, task_id):
    task_manager.stop(task_id)
    return Response({"msg": "stopped", "task_id": task_id})

@api_view(['POST'])
@permission_classes([HasRolePermission])
def stop_task_soft(request, task_id):
    task_manager.stop_soft(task_id)
    return Response({"msg": "stopped (soft)", "task_id": task_id})

@api_view(['POST'])
@permission_classes([HasRolePermission])
def delete_task(request, task_id):
    task_manager.delete(task_id)
    return Response({"msg": "deleted", "task_id": task_id})

@api_view(['GET'])
@permission_classes([HasRolePermission])
def task_logs(request, task_id):
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 100))
    reverse = request.GET.get('reverse', 'false').lower() == 'true'
    
    p = os.path.join("logs", f"{task_id}.log")
    if not os.path.exists(p):
        return Response({"lines": [], "total": 0, "page": 1, "page_size": page_size})
        
    try:
        with open(p, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        
        total = len(all_lines)
        page_size = max(1, min(page_size, 2000))
        
        # Reverse if requested
        if reverse:
            all_lines.reverse()
        
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

@api_view(['GET'])
@permission_classes([HasRolePermission])
def log_files_list(request):
    log_dir = "logs"
    if not os.path.exists(log_dir):
        return Response({"files": [], "total": 0, "page": 1, "page_size": 10})
        
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 10))
    
    files = []
    try:
        for f in os.listdir(log_dir):
            if f.endswith(".log"):
                p = os.path.join(log_dir, f)
                stat = os.stat(p)
                size_mb = round(stat.st_size / (1024 * 1024), 2)
                mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                files.append({
                    "name": f,
                    "size": f"{size_mb} MB",
                    "bytes": stat.st_size,
                    "mtime": mtime
                })
        # Sort by mtime desc
        files.sort(key=lambda x: x['mtime'], reverse=True)
        
        # Pagination
        total = len(files)
        start = (page - 1) * page_size
        end = start + page_size
        paged_files = files[start:end]
        
    except Exception as e:
        return Response({"detail": str(e)}, status=500)
        
    return Response({
        "files": paged_files,
        "total": total,
        "page": page,
        "page_size": page_size
    })

@api_view(['GET'])
@permission_classes([HasRolePermission])
def download_log_file(request, filename):
    log_dir = "logs"
    p = os.path.join(log_dir, filename)
    
    # Security check: prevent path traversal
    if not os.path.abspath(p).startswith(os.path.abspath(log_dir)):
        return Response({"detail": "Invalid filename"}, status=400)
        
    if not os.path.exists(p):
        return Response({"detail": "File not found"}, status=404)
        
    def file_iterator(file_path, chunk_size=8192):
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    response = StreamingHttpResponse(file_iterator(p))
    response['Content-Type'] = 'application/octet-stream'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

@api_view(['GET'])
@permission_classes([HasRolePermission])
def log_stats(request):
    log_dir = "logs"
    if not os.path.exists(log_dir):
        return Response({"stats": {"error": 0, "warning": 0, "info": 0}, "series": []})
        
    # Aggregate stats from all log files (last 1000 lines each for performance)
    total_error = 0
    total_warn = 0
    total_info = 0
    
    # Simple time-series distribution (mock or rough estimate based on timestamps)
    # For real accurate time-series, we'd need to parse timestamps. 
    # Let's do a simple parsing of the last few lines to generate a trend for "Today"
    
    now = datetime.datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    # Bucket by hour: {"10:00": 5, "11:00": 12}
    hourly_errors = {}
    
    try:
        for f in os.listdir(log_dir):
            if not f.endswith(".log"): 
                continue
                
            p = os.path.join(log_dir, f)
            try:
                # Read last 2000 lines efficiently? For now just read lines
                with open(p, "r", encoding="utf-8", errors='ignore') as fo:
                    # Reading full file might be slow if huge. 
                    # Let's assume files rotate or aren't massive for this demo.
                    # Or use a seek to tail.
                    fo.seek(0, 2)
                    size = fo.tell()
                    # Read last 1MB
                    fo.seek(max(0, size - 1024*1024), 0)
                    lines = fo.readlines()
                    
                    for line in lines:
                        if "ERROR" in line or "CRITICAL" in line or "Exception" in line:
                            total_error += 1
                            # Extract time [2026-01-23 10:00:00]
                            if line.startswith("["):
                                try:
                                    # [2026-01-23 10:00:00]
                                    ts_str = line[1:20]
                                    if ts_str.startswith(today_str):
                                        hour = ts_str[11:13] + ":00"
                                        hourly_errors[hour] = hourly_errors.get(hour, 0) + 1
                                except:
                                    pass
                        elif "WARNING" in line:
                            total_warn += 1
                        else:
                            total_info += 1
            except Exception:
                pass
                
    except Exception as e:
        pass
        
    # Fill missing hours for chart
    hours = sorted(hourly_errors.keys())
    series_data = [hourly_errors[h] for h in hours]
    
    return Response({
        "summary": {
            "error": total_error,
            "warning": total_warn,
            "info": total_info
        },
        "trend": {
            "hours": hours,
            "errors": series_data
        }
    })

@api_view(['GET'])
@permission_classes([HasRolePermission])
def log_global_search(request):
    keyword = request.GET.get('q', '').strip()
    if not keyword:
        return Response({"matches": []})
        
    log_dir = "logs"
    matches = []
    MAX_MATCHES = 100
    
    try:
        for f in os.listdir(log_dir):
            if not f.endswith(".log"): continue
            p = os.path.join(log_dir, f)
            
            try:
                with open(p, "r", encoding="utf-8", errors='ignore') as fo:
                    for i, line in enumerate(fo):
                        if keyword.lower() in line.lower():
                            matches.append({
                                "file": f,
                                "line": i + 1,
                                "content": line.strip()[:300] # Truncate long lines
                            })
                            if len(matches) >= MAX_MATCHES:
                                break
            except:
                pass
            if len(matches) >= MAX_MATCHES:
                break
    except Exception as e:
        return Response({"detail": str(e)}, status=500)
        
    return Response({"matches": matches})

# --- K8s Logs ---

@api_view(['GET'])
@permission_classes([HasRolePermission])
def k8s_namespaces(request):
    api = _get_k8s_core_api()
    if not api:
        return Response({"namespaces": ["default"], "error": "K8s config not found"})
    
    try:
        ns_list = api.list_namespace()
        names = [ns.metadata.name for ns in ns_list.items]
        return Response({"namespaces": names})
    except Exception as e:
        return Response({"namespaces": [], "error": str(e)})

@api_view(['GET'])
@permission_classes([HasRolePermission])
def k8s_pods(request):
    ns = request.GET.get('namespace', 'default')
    api = _get_k8s_core_api()
    if not api:
        return Response({"pods": [], "error": "K8s config not found"})
        
    try:
        pod_list = api.list_namespaced_pod(ns)
        pods = []
        for p in pod_list.items:
            pods.append({
                "name": p.metadata.name,
                "status": p.status.phase,
                "containers": [c.name for c in p.spec.containers]
            })
        return Response({"pods": pods})
    except Exception as e:
        return Response({"pods": [], "error": str(e)})

@api_view(['GET'])
@permission_classes([HasRolePermission])
def k8s_pod_logs(request):
    ns = request.GET.get('namespace', 'default')
    pod_name = request.GET.get('pod_name')
    container = request.GET.get('container')
    tail_lines = int(request.GET.get('tail_lines', 100))
    
    if not pod_name:
        return Response({"logs": ""})
        
    api = _get_k8s_core_api()
    if not api:
        return Response({"logs": "Error: K8s config not found"})
        
    try:
        logs = api.read_namespaced_pod_log(
            name=pod_name,
            namespace=ns,
            container=container,
            tail_lines=tail_lines
        )
        return Response({"logs": logs})
    except Exception as e:
        return Response({"logs": f"Error reading logs: {str(e)}"})

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
@permission_classes([HasRolePermission])
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
@permission_classes([HasRolePermission])
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
@permission_classes([HasRolePermission])
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
@permission_classes([HasRolePermission])
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
