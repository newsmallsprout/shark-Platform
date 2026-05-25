from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from api.views import HasRolePermission
from django.http import FileResponse, HttpResponseNotFound, StreamingHttpResponse
import os
import datetime
import codecs
import json
from django.utils import timezone
from .models import MonitorTask
from .engine import monitor_engine
from django.forms.models import model_to_dict
try:
    import boto3
except ImportError:
    boto3 = None

def _get_s3_client(task):
    if not boto3:
        return None
    if not getattr(task, 's3_archive_enabled', False):
        return None
    if not getattr(task, 's3_bucket', ''):
        return None
    try:
        # Check if s3_endpoint is something like https://s3.amazonaws.com
        # For region-specific buckets, passing a generic endpoint URL can force
        # botocore to ignore the region_name and send requests to the generic endpoint.
        # It's better to omit endpoint_url entirely if it's the standard AWS endpoint.
        endpoint = task.s3_endpoint
        if endpoint and ('s3.amazonaws.com' in endpoint or endpoint.strip() == ''):
            endpoint = None
            
        return boto3.client(
            's3',
            region_name=task.s3_region,
            aws_access_key_id=task.s3_access_key,
            aws_secret_access_key=task.s3_secret_key,
            endpoint_url=endpoint or None
        )
    except Exception:
        return None

def _task_s3_prefixes(task):
    prefixes = [f"logs/monitor/{task.id}/"]
    if getattr(task, 'name', None):
        prefixes.append(f"logs/{task.name}/")
    return prefixes

def _iter_s3_lines(body_stream):
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    buf = ""
    for chunk in iter(lambda: body_stream.read(64 * 1024), b''):
        buf += decoder.decode(chunk)
        while True:
            nl = buf.find('\n')
            if nl == -1:
                break
            line = buf[:nl + 1]
            buf = buf[nl + 1:]
            yield line
    buf += decoder.decode(b'', final=True)
    if buf:
        yield buf

def _latest_completed_4h_window_start(now):
    local_dt = timezone.localtime(now)
    hour = (local_dt.hour // 4) * 4
    ws = local_dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    return ws - datetime.timedelta(hours=4)

def _index_s3_key(task, log_type: str, window_start):
    ws = timezone.localtime(window_start)
    date_str = ws.date().isoformat()
    start_h = ws.hour
    end_h = (start_h + 3) % 24
    return f"logs/monitor/{task.id}/indexes/{log_type}/{date_str}/{start_h:02d}00-{end_h:02d}59.json"

def _redact_task_dict(d: dict) -> dict:
    if not isinstance(d, dict):
        return d
    out = dict(d)
    ak = out.get('s3_access_key') or ''
    sk = out.get('s3_secret_key') or ''
    if ak:
        out['s3_access_key'] = f"****{ak[-4:]}" if len(ak) >= 4 else "****"
    if sk:
        out['s3_secret_key'] = ""
        out['s3_secret_key_set'] = True
    else:
        out['s3_secret_key_set'] = False
    return out

@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def monitor_tasks(request):
    if request.method == 'GET':
        tasks = MonitorTask.objects.all()
        return Response([_redact_task_dict(model_to_dict(t)) for t in tasks])
    elif request.method == 'POST':
        data = request.data
        task = MonitorTask.objects.create(
            name=data.get('name', 'New Monitor'),
            enabled=data.get('enabled', False),
            k8s_namespace=data.get('k8s_namespace', 'default'),
            k8s_kubeconfig=data.get('k8s_kubeconfig', ''),
            s3_archive_enabled=data.get('s3_archive_enabled', False),
            s3_bucket=data.get('s3_bucket', ''),
            s3_region=data.get('s3_region', 'us-east-1'),
            s3_access_key=data.get('s3_access_key', ''),
            s3_secret_key=data.get('s3_secret_key', ''),
            s3_endpoint=data.get('s3_endpoint', ''),
            retention_days=data.get('retention_days', 3),
            alert_enabled=data.get('alert_enabled', True),
            slack_webhook_url=data.get('slack_webhook_url', ''),
            poll_interval_seconds=data.get('poll_interval_seconds', 60),
            alert_keywords=data.get('alert_keywords', []),
            ignore_keywords=data.get('ignore_keywords', []),
            record_only_keywords=data.get('record_only_keywords', []),
            # New fields
            immediate_keywords=data.get('immediate_keywords', []),
            alert_threshold_count=data.get('alert_threshold_count', 5),
            alert_threshold_window=data.get('alert_threshold_window', 60),
            alert_silence_minutes=data.get('alert_silence_minutes', 60)
        )
        return Response(_redact_task_dict(model_to_dict(task)))

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRolePermission])
def monitor_task_detail(request, pk):
    try:
        task = MonitorTask.objects.get(pk=pk)
    except MonitorTask.DoesNotExist:
        return Response({"error": "Task not found"}, status=404)
        
    if request.method == 'GET':
        return Response(_redact_task_dict(model_to_dict(task)))
        
    elif request.method == 'PUT':
        data = request.data
        if 's3_access_key' in data and (data.get('s3_access_key') == '' or data.get('s3_access_key') is None):
            data = dict(data)
            data.pop('s3_access_key', None)
        if 's3_secret_key' in data and (data.get('s3_secret_key') == '' or data.get('s3_secret_key') is None):
            data = dict(data)
            data.pop('s3_secret_key', None)
        for field in [
            "name", "enabled", "k8s_namespace", "k8s_kubeconfig", 
            "s3_archive_enabled", "s3_bucket", "s3_region", "s3_access_key", "s3_secret_key", "s3_endpoint",
            "retention_days", "alert_enabled", "slack_webhook_url", "poll_interval_seconds",
            "alert_keywords", "ignore_keywords", "record_only_keywords",
            "immediate_keywords", "alert_threshold_count", "alert_threshold_window", "alert_silence_minutes"
        ]:
            if field in data:
                setattr(task, field, data[field])
        task.save()
        
        # Trigger engine update if needed (engine loop should handle DB changes automatically)
        return Response(_redact_task_dict(model_to_dict(task)))
        
    elif request.method == 'DELETE':
        task.delete()
        return Response({"msg": "deleted"})

# Helper to handle S3 Region Redirect
def _handle_s3_error(e, task):
    try:
        import botocore
        if isinstance(e, botocore.exceptions.ClientError):
            err_code = e.response.get('Error', {}).get('Code')
            if err_code in ('301', 'PermanentRedirect'):
                correct_region = e.response.get('ResponseMetadata', {}).get('HTTPHeaders', {}).get('x-amz-bucket-region')
                if correct_region and correct_region != task.s3_region:
                    print(f"[monitor] S3 Redirect detected! Updating task {task.id} from {task.s3_region} to {correct_region}")
                    task.s3_region = correct_region
                    task.save(update_fields=['s3_region'])
                    return True
    except Exception:
        pass
    return False

@api_view(['GET'])
@permission_classes([HasRolePermission])
def monitor_logs(request):
    task_id = request.query_params.get('task_id')
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 10))
    search_query = request.query_params.get('search', '').lower()
    sort_by = request.query_params.get('sort_by', 'mtime') # name, size, mtime
    order = request.query_params.get('order', 'desc') # asc, desc
    log_type = (request.query_params.get('log_type') or 'all').lower()
    realtime = (request.query_params.get('realtime') or '').lower() in ('1', 'true', 'yes', 'y', 'on')
    
    base_dir = monitor_engine.LOG_DIR
    if not task_id:
        return Response({"files": [], "total": 0})

    try:
        task = MonitorTask.objects.get(pk=task_id)
    except MonitorTask.DoesNotExist:
        return Response({"files": [], "total": 0})

    s3_client = _get_s3_client(task)
    
    # Logic: 
    # 1. Fetch from S3 Index (History mode or S3 enabled).
    # 2. Fetch from Local (Error logs or S3 disabled).
    # 3. Combine and Deduplicate.
    
    s3_files = []
    local_files = []
    
    # 1. S3 Files
    # Logic: Use S3 Index ONLY if S3 is enabled.
    if s3_client:
        lt = log_type if log_type in ('raw', 'error') else 'raw'
        ws = _latest_completed_4h_window_start(timezone.now())
        
        payload = None
        if realtime:
             try:
                 payload = monitor_engine.get_realtime_index_payload(task, lt)
             except Exception:
                 pass
        
        if not payload:
            # Fallback to S3 latest completed window
            idx_key = _index_s3_key(task, lt, ws)
            try:
                obj = s3_client.get_object(Bucket=task.s3_bucket, Key=idx_key)
                raw = obj['Body'].read().decode('utf-8', errors='replace')
                payload = json.loads(raw)
            except Exception as e:
                # Handle Redirect
                if _handle_s3_error(e, task):
                    # Retry once with new client
                    s3_client = _get_s3_client(task)
                    try:
                        obj = s3_client.get_object(Bucket=task.s3_bucket, Key=idx_key)
                        raw = obj['Body'].read().decode('utf-8', errors='replace')
                        payload = json.loads(raw)
                    except Exception:
                        pass
                pass
        
        if payload and isinstance(payload.get('files'), list):
            s3_files = payload['files']
            
            # AGGREGATION LOGIC for "Too Many Files"
            # If we have many small chunks for the same pod/window, group them.
            # But the user wants "Latest 4 hours".
            # If we group them, we return one entry per Pod.
            # Name: "{pod_name}_aggregated_{window_start}.log"
            # But we need to know WHICH files belong to it.
            # We can't return a list of lists.
            # We can return "Virtual Files" and handle them in `monitor_log_view`.
            
            # Group by pod name (parsed from key)
            # Key format: .../raw/namespace/pod/date/stamp.log
            # Regex: .*/raw/([^/]+)/([^/]+)/.*
            
            aggregated = {}
            for f in s3_files:
                key = f.get('name') or ''
                # Try parse pod
                parts = key.split('/')
                # Expect: logs/monitor/{id}/raw/{ns}/{pod}/{date}/{stamp}.log
                # If path structure changes, this breaks.
                # Let's try to match loosely.
                if '/raw/' in key:
                    try:
                        idx = key.find('/raw/')
                        rest = key[idx+5:] # ns/pod/date/stamp.log
                        p = rest.split('/')
                        if len(p) >= 4:
                            ns, pod = p[0], p[1]
                            virtual_name = f"{ns}_{pod}_s3_recent.log" # Virtual Name
                            
                            if virtual_name not in aggregated:
                                aggregated[virtual_name] = {
                                    "name": virtual_name,
                                    "size": 0,
                                    "mtime": 0,
                                    "is_virtual": True,
                                    "s3_keys": []
                                }
                            aggregated[virtual_name]['size'] += int(f.get('size') or 0)
                            aggregated[virtual_name]['mtime'] = max(aggregated[virtual_name]['mtime'], float(f.get('mtime') or 0))
                            aggregated[virtual_name]['s3_keys'].append(key)
                    except:
                        pass
                else:
                    # Keep as is?
                    pass
            
            if aggregated:
                s3_files = list(aggregated.values())

    # 2. Local Files
    log_dir = os.path.join(base_dir, str(task_id))
    if os.path.exists(log_dir):
        def is_error_name(name: str) -> bool:
            n = (name or '').lower()
            return n.endswith('_error.log') or ('task_errors_' in n)

        for f in os.listdir(log_dir):
            if f.endswith(".log"):
                if search_query and search_query not in f.lower():
                    continue
                if log_type == 'error' and not is_error_name(f):
                    continue
                if log_type == 'raw' and is_error_name(f):
                    continue
                    
                full_path = os.path.join(log_dir, f)
                stat = os.stat(full_path)
                local_files.append({
                    "name": f,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime
                })

    # Combine
    files = s3_files + local_files
    
    # Filter by search
    if search_query:
        sq = search_query.lower()
        files = [f for f in files if sq in str((f.get('name') or '')).lower()]

    reverse = (order == 'desc')
    if sort_by == 'name':
        files.sort(key=lambda x: x.get('name') or '', reverse=reverse)
    elif sort_by == 'size':
        files.sort(key=lambda x: int(x.get('size') or 0), reverse=reverse)
    else:
        files.sort(key=lambda x: float(x.get('mtime') or 0), reverse=reverse)

    total = len(files)
    start_i = (page - 1) * page_size
    end_i = start_i + page_size
    paged_files = files[start_i:end_i]
    
    # We need to store 's3_keys' in the response so the frontend passes it back?
    # No, frontend just passes 'filename'. 
    # If filename is virtual, `monitor_log_view` must reconstruct or find the keys.
    # But `monitor_log_view` is stateless. It doesn't know the keys unless we pass them or query index again.
    # Querying index again is fine.
    
    return Response({
        "files": paged_files,
        "total": total,
        "page": page,
        "page_size": page_size,
        "source": "hybrid",
        "realtime": realtime
    })



@api_view(['GET'])
@permission_classes([HasRolePermission])
def monitor_logs_history(request):
    task_id = request.query_params.get('task_id')
    log_type = (request.query_params.get('log_type') or 'raw').lower()
    start_str = request.query_params.get('start')
    end_str = request.query_params.get('end')
    keyword = (request.query_params.get('keyword') or '').lower()
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 50))

    if not task_id:
        return Response({"items": [], "total": 0})
    try:
        task = MonitorTask.objects.get(pk=task_id)
    except MonitorTask.DoesNotExist:
        return Response({"items": [], "total": 0})

    s3_client = _get_s3_client(task)
    if not s3_client:
        return Response({"items": [], "total": 0})
    
    # Debug: Print current config
    print(f"[monitor] Fetching history for task {task.id}: Bucket={task.s3_bucket}, Region={task.s3_region}, Endpoint={task.s3_endpoint}")

    lt = log_type if log_type in ('raw', 'error') else 'raw'
    now = timezone.now()
    try:
        start_dt = datetime.datetime.fromisoformat(start_str) if start_str else (now - datetime.timedelta(days=7))
    except Exception:
        start_dt = now - datetime.timedelta(days=7)
    try:
        end_dt = datetime.datetime.fromisoformat(end_str) if end_str else now
    except Exception:
        end_dt = now
    if timezone.is_naive(start_dt):
        start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
    if timezone.is_naive(end_dt):
        end_dt = timezone.make_aware(end_dt, timezone.get_current_timezone())

    prefix = f"logs/monitor/{task.id}/indexes/{lt}/"
    items = []
    
    # Helper to process pagination so we can retry if needed
    def fetch_items(client):
        fetched = []
        paginator = client.get_paginator('list_objects_v2')
        for p in paginator.paginate(Bucket=task.s3_bucket, Prefix=prefix):
            for obj in p.get('Contents', []) or []:
                key = obj.get('Key') or ''
                if not key.endswith('.json'):
                    continue
                if keyword and keyword not in key.lower():
                    continue
                try:
                    parts = key.split('/')
                    date_str = parts[-2]
                    range_str = parts[-1].replace('.json', '')
                    start_h = int(range_str[:2])
                    ws_dt = datetime.datetime.fromisoformat(date_str).replace(hour=start_h, minute=0, second=0, microsecond=0)
                    ws_dt = timezone.make_aware(ws_dt, timezone.get_current_timezone())
                    we_dt = ws_dt + datetime.timedelta(hours=4) - datetime.timedelta(seconds=1)
                except Exception:
                    continue
                if we_dt < start_dt or ws_dt > end_dt:
                    continue
                lm = obj.get('LastModified')
                mtime = lm.timestamp() if lm else 0
                fetched.append({
                    "key": key,
                    "window_start": ws_dt.isoformat(),
                    "window_end": we_dt.isoformat(),
                    "mtime": mtime,
                    "size": int(obj.get('Size') or 0),
                })
        return fetched

    try:
        items = fetch_items(s3_client)
    except Exception as e:
        # Check for Region mismatch (PermanentRedirect)
        is_redirect = False
        correct_region = None
        try:
            import botocore
            if isinstance(e, botocore.exceptions.ClientError):
                err_code = e.response.get('Error', {}).get('Code')
                if err_code in ('301', 'PermanentRedirect'):
                    is_redirect = True
                    correct_region = e.response.get('ResponseMetadata', {}).get('HTTPHeaders', {}).get('x-amz-bucket-region')
        except Exception:
            pass
            
        if is_redirect and correct_region and correct_region != task.s3_region:
            # Auto-fix region and retry
            print(f"[monitor] S3 Redirect detected! Updating task {task.id} from {task.s3_region} to {correct_region}")
            task.s3_region = correct_region
            task.save(update_fields=['s3_region'])
            s3_client = _get_s3_client(task)
            try:
                items = fetch_items(s3_client)
            except Exception as retry_e:
                return Response({"error": f"Auto-fixed region to {correct_region}, but retry failed: {str(retry_e)}"}, status=500)
        else:
            if is_redirect:
                msg = f"S3 Region mismatch (PermanentRedirect). "
                if correct_region:
                    msg += f"Bucket '{task.s3_bucket}' is in '{correct_region}', but task configured for '{task.s3_region}'. Please update config."
                else:
                    msg += f"Please verify your Region setting matches the Bucket '{task.s3_bucket}'."
                print(f"[monitor] S3 Redirect Error: {msg}")
                return Response({"error": msg}, status=400)
            return Response({"error": str(e)}, status=500)

    items.sort(key=lambda x: x.get('window_start') or '', reverse=True)
    total = len(items)
    start_i = (page - 1) * page_size
    end_i = start_i + page_size
    return Response({"items": items[start_i:end_i], "total": total, "page": page, "page_size": page_size})


@api_view(['GET'])
@permission_classes([HasRolePermission])
def monitor_index_detail(request):
    task_id = request.query_params.get('task_id')
    key = request.query_params.get('key')
    if not task_id or not key:
        return Response({"error": "task_id and key required"}, status=400)
    try:
        task = MonitorTask.objects.get(pk=task_id)
    except MonitorTask.DoesNotExist:
        return Response({"error": "Task not found"}, status=404)

    s3_client = _get_s3_client(task)
    if not s3_client:
        return Response({"error": "S3 not enabled"}, status=400)
    prefix = f"logs/monitor/{task.id}/indexes/"
    if not str(key).startswith(prefix):
        return Response({"error": "invalid parameters"}, status=400)
    try:
        obj = s3_client.get_object(Bucket=task.s3_bucket, Key=key)
        raw = obj['Body'].read().decode('utf-8', errors='replace')
        data = json.loads(raw)
        return Response(data)
    except Exception as e:
        # Handle Redirect
        if _handle_s3_error(e, task):
            s3_client = _get_s3_client(task)
            try:
                obj = s3_client.get_object(Bucket=task.s3_bucket, Key=key)
                raw = obj['Body'].read().decode('utf-8', errors='replace')
                data = json.loads(raw)
                return Response(data)
            except Exception:
                pass
        return Response({"error": "Index not found"}, status=404)

@api_view(['GET'])
@permission_classes([HasRolePermission])
def monitor_log_view(request):
    filename = request.query_params.get('filename')
    task_id = request.query_params.get('task_id')
    keyword = request.query_params.get('keyword')
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 1000))
    reverse = request.query_params.get('reverse', 'false').lower() == 'true'
    
    if not filename or not task_id:
        return Response({"error": "filename and task_id required"}, status=400)

    try:
        task = MonitorTask.objects.get(pk=task_id)
    except MonitorTask.DoesNotExist:
        return Response({"error": "Task not found"}, status=404)

    # Helper for serving local file
    def serve_local_file(fpath):
        try:
            # If keyword provided, we search
            if keyword:
                results = []
                keywords = keyword.lower().split()
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    for i, line in enumerate(f, 1):
                        line_lower = line.lower()
                        if all(k in line_lower for k in keywords):
                            results.append(line.rstrip())
                            if len(results) > 2000: 
                                    results.append(f"... (Matches truncated, found > 2000 lines) ...")
                                    break
                return Response({"content": "\n".join(results), "is_search_result": True, "total": len(results)})

            file_size = os.path.getsize(fpath)
            MAX_SIZE_MB = 50
            
            if file_size > MAX_SIZE_MB * 1024 * 1024 and not keyword:
                if reverse and page == 1:
                    from collections import deque
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        all_lines = list(deque(f, page_size))
                        all_lines.reverse()
                        total = page_size + 1
                        content = "".join(all_lines)
                        return Response({
                            "content": content,
                            "total": total,
                            "page": 1,
                            "page_size": page_size,
                            "warning": "File too large, showing last lines only."
                        })
            
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
                
            total = len(all_lines)
            if reverse:
                all_lines.reverse()
            
            p = page
            if p == -1:
                import math
                p = max(1, math.ceil(total / page_size))
                
            start = (p - 1) * page_size
            end = start + page_size
            
            content = "".join(all_lines[start:end])
            
            return Response({
                "content": content, 
                "total": total,
                "page": p,
                "page_size": page_size
            })
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    # Helper for Virtual S3 File (Aggregated)
    # Filename format: {ns}_{pod}_s3_recent.log
    if filename.endswith('_s3_recent.log'):
        # Reconstruct the logic to find matching keys
        # We need to query the Index again to find the chunks.
        # This is slightly inefficient but stateless.
        s3_client = _get_s3_client(task)
        if s3_client:
            # Parse namespace and pod from filename
            # Format: {ns}_{pod}_s3_recent.log
            # Caveat: pod name might contain underscores.
            # But we constructed it as `f"{ns}_{pod}_s3_recent.log"`.
            # And `ns` usually doesn't have underscores (K8s convention), but might.
            # Let's assume the suffix is constant.
            base_name = filename[:-14] # strip "_s3_recent.log"
            # Split by first underscore? No, ns and pod are separated by _.
            # We need to match the S3 keys that contain `/raw/{ns}/{pod}/`.
            # We can just search the index for keys containing `{ns}/{pod}`?
            # Or iterate all keys in current window index and check if they match the "Virtual Name" logic.
            
            lt = 'raw' # Virtual files are only for raw logs
            ws = _latest_completed_4h_window_start(timezone.now())
            payload = None
            
            # Check realtime index first
            try:
                payload = monitor_engine.get_realtime_index_payload(task, lt)
            except:
                pass
            
            if not payload:
                # Check S3 index
                idx_key = _index_s3_key(task, lt, ws)
                try:
                    obj = s3_client.get_object(Bucket=task.s3_bucket, Key=idx_key)
                    raw = obj['Body'].read().decode('utf-8', errors='replace')
                    payload = json.loads(raw)
                except:
                    pass
            
            target_keys = []
            if payload and isinstance(payload.get('files'), list):
                for f in payload['files']:
                    key = f.get('name') or ''
                    # Check if this key maps to our requested filename
                    if '/raw/' in key:
                        try:
                            idx = key.find('/raw/')
                            rest = key[idx+5:] 
                            p = rest.split('/')
                            if len(p) >= 4:
                                ns, pod = p[0], p[1]
                                virtual_name = f"{ns}_{pod}_s3_recent.log"
                                if virtual_name == filename:
                                    target_keys.append(key)
                        except:
                            pass
            
            # Now fetch and concat all target_keys
            # Sort by key (contains timestamp)
            target_keys.sort()
            
            all_content = []
            # Limitation: If total size is huge, we might OOM.
            # But "recent" chunks shouldn't be massive for 4 hours unless verbose.
            # We enforce a limit?
            
            # If search keyword, stream and search
            if keyword:
                results = []
                keywords = keyword.lower().split()
                line_idx = 1
                for key in target_keys:
                    try:
                        obj = s3_client.get_object(Bucket=task.s3_bucket, Key=key)
                        for line in _iter_s3_lines(obj['Body']):
                            ll = line.lower()
                            if all(k in ll for k in keywords):
                                results.append(line.rstrip('\n'))
                                if len(results) > 2000:
                                    break
                        if len(results) > 2000:
                            results.append("... (Matches truncated) ...")
                            break
                    except:
                        pass
                return Response({"content": "\n".join(results), "is_search_result": True, "total": len(results)})

            # Full content fetch (with pagination?)
            # Pagination across multiple S3 files is hard.
            # We will fetch ALL and then paginate in memory (inefficient but works for text logs).
            
            full_text = ""
            for key in target_keys:
                try:
                    obj = s3_client.get_object(Bucket=task.s3_bucket, Key=key)
                    chunk = obj['Body'].read().decode('utf-8', errors='replace')
                    full_text += chunk
                except:
                    pass
            
            # Apply pagination on full_text
            all_lines = full_text.splitlines(True)
            total = len(all_lines)
            if reverse:
                all_lines.reverse()
            
            p = page
            if p == -1:
                import math
                p = max(1, math.ceil(total / page_size))
            
            start = (p - 1) * page_size
            end = start + page_size
            
            content = "".join(all_lines[start:end])
            
            return Response({
                "content": content, 
                "total": total,
                "page": p,
                "page_size": page_size
            })

    # Check Local First
    log_dir = os.path.join(monitor_engine.LOG_DIR, str(task_id))
    local_path = os.path.join(log_dir, filename)
    is_safe_local = not (os.path.sep in filename or '..' in filename)
    
    if is_safe_local and os.path.exists(local_path):
        return serve_local_file(local_path)

    # Try S3 Second (for non-virtual raw logs, e.g. history or direct key access)
    s3_client = _get_s3_client(task)
    if s3_client:
        key = filename
        prefixes = _task_s3_prefixes(task)
        if not any(key.startswith(p) for p in prefixes):
             pass
        else:
            try:
                head = s3_client.head_object(Bucket=task.s3_bucket, Key=key)
                size = int(head.get('ContentLength') or 0)
            except Exception as e:
                # Retry if redirect
                if _handle_s3_error(e, task):
                    s3_client = _get_s3_client(task)
                    try:
                        head = s3_client.head_object(Bucket=task.s3_bucket, Key=key)
                        size = int(head.get('ContentLength') or 0)
                    except Exception:
                        return Response({"error": "File not found after region retry"}, status=404)
                else:
                    return Response({"error": "File not found"}, status=404)

            try:
                if keyword:
                    results = []
                    keywords = keyword.lower().split()
                    obj = s3_client.get_object(Bucket=task.s3_bucket, Key=key)
                    for i, line in enumerate(_iter_s3_lines(obj['Body']), 1):
                        ll = line.lower()
                        if all(k in ll for k in keywords):
                            results.append(line.rstrip('\n'))
                            if len(results) > 2000:
                                results.append("... (Matches truncated, found > 2000 lines) ...")
                                break
                    return Response({"content": "\n".join(results), "is_search_result": True, "total": len(results)})

                MAX_SIZE_MB = 50
                if size > MAX_SIZE_MB * 1024 * 1024:
                    if reverse and page == 1:
                        tail_bytes = min(size, 1024 * 1024)
                        start = max(0, size - tail_bytes)
                        obj = s3_client.get_object(Bucket=task.s3_bucket, Key=key, Range=f"bytes={start}-{size-1}")
                        text = obj['Body'].read().decode('utf-8', errors='replace')
                        lines = text.splitlines(True)
                        lines = lines[-page_size:]
                        lines.reverse()
                        return Response({
                            "content": "".join(lines),
                            "total": page_size + 1,
                            "page": 1,
                            "page_size": page_size,
                            "warning": "File too large, showing last lines only."
                        })
                    return Response({"error": "File too large"}, status=413)

                obj = s3_client.get_object(Bucket=task.s3_bucket, Key=key)
                text = obj['Body'].read().decode('utf-8', errors='replace')
                all_lines = text.splitlines(True)
                total = len(all_lines)
                if reverse:
                    all_lines.reverse()
                
                p = page
                if p == -1:
                    import math
                    p = max(1, math.ceil(total / page_size))
                start = (p - 1) * page_size
                end = start + page_size
                return Response({"content": "".join(all_lines[start:end]), "total": total, "page": p, "page_size": page_size})
            except Exception as e:
                # Handle Redirect for get_object
                if _handle_s3_error(e, task):
                    return Response({"error": "Region fixed, please retry"}, status=503) # 503 Service Unavailable (Retry) or simple error
                return Response({"error": str(e)}, status=500)

    return Response({"error": "File not found"}, status=404)


@api_view(['GET'])
@permission_classes([HasRolePermission])
def monitor_log_download(request):
    filename = request.query_params.get('filename')
    task_id = request.query_params.get('task_id')
    
    if not filename or not task_id:
        return Response({"error": "filename and task_id required"}, status=400)

    try:
        task = MonitorTask.objects.get(pk=task_id)
    except MonitorTask.DoesNotExist:
        return HttpResponseNotFound("File not found")

    # Try Local First
    log_dir = os.path.join(monitor_engine.LOG_DIR, str(task_id))
    local_path = os.path.join(log_dir, filename)
    is_safe_local = not (os.path.sep in filename or '..' in filename)

    if is_safe_local and os.path.exists(local_path):
        return FileResponse(open(local_path, 'rb'), as_attachment=True, filename=filename)

    # Try S3 Second
    s3_client = _get_s3_client(task)
    if s3_client:
        key = filename
        prefixes = _task_s3_prefixes(task)
        if any(key.startswith(p) for p in prefixes):
            try:
                obj = s3_client.get_object(Bucket=task.s3_bucket, Key=key)
                resp = StreamingHttpResponse(obj['Body'], content_type='text/plain; charset=utf-8')
                out_name = os.path.basename(key) or "log.log"
                resp['Content-Disposition'] = f'attachment; filename="{out_name}"'
                return resp
            except Exception:
                pass

    return HttpResponseNotFound("File not found")


@api_view(['GET'])
@permission_classes([HasRolePermission])
def monitor_log_merge_download(request):
    """按时间范围+服务名合并S3日志分片为单文件下载
    
    Query params:
        task_id    - 监控任务ID (必填)
        start      - 起始时间 ISO格式 (必填)
        end        - 结束时间 ISO格式 (必填)
        log_type   - raw/error (默认 raw)
        namespace  - K8s命名空间 (可选，过滤)
        pod_name   - Pod名 (可选，过滤)
    """
    task_id = request.query_params.get('task_id')
    start_str = request.query_params.get('start')
    end_str = request.query_params.get('end')
    log_type = (request.query_params.get('log_type') or 'raw').lower()
    namespace_filter = (request.query_params.get('namespace') or '').strip()
    pod_filter = (request.query_params.get('pod_name') or '').strip()

    if not task_id or not start_str or not end_str:
        return Response({"error": "task_id, start, end required"}, status=400)
    if log_type not in ('raw', 'error'):
        return Response({"error": "log_type must be raw or error"}, status=400)

    try:
        task = MonitorTask.objects.get(pk=task_id)
    except MonitorTask.DoesNotExist:
        return Response({"error": "Task not found"}, status=404)

    s3_client = _get_s3_client(task)
    if not s3_client:
        return Response({"error": "S3 archive not enabled for this task"}, status=400)

    # 解析时间
    now = timezone.now()
    try:
        start_dt = datetime.datetime.fromisoformat(start_str)
    except Exception:
        return Response({"error": "Invalid start format, use ISO 8601"}, status=400)
    try:
        end_dt = datetime.datetime.fromisoformat(end_str)
    except Exception:
        return Response({"error": "Invalid end format, use ISO 8601"}, status=400)
    
    if timezone.is_naive(start_dt):
        start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())
    if timezone.is_naive(end_dt):
        end_dt = timezone.make_aware(end_dt, timezone.get_current_timezone())

    # 扫描 S3 日志文件
    prefix = f"logs/monitor/{task_id}/{log_type}/"
    matched_keys = []
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=task.s3_bucket, Prefix=prefix):
            for obj in page.get('Contents', []) or []:
                key = obj.get('Key') or ''
                # Key格式: logs/monitor/{id}/{log_type}/{ns}/{pod}/{date}/{stamp}.log
                parts = key.split('/')
                if len(parts) < 8:
                    continue
                
                ns = parts[4]
                pod = parts[5]
                date_str = parts[6]
                
                # namespace/pod 过滤
                if namespace_filter and ns != namespace_filter:
                    continue
                if pod_filter and pod != pod_filter:
                    continue
                
                # 日期范围过滤
                try:
                    file_date = datetime.date.fromisoformat(date_str)
                    file_dt = datetime.datetime.combine(file_date, datetime.time.min)
                    if timezone.is_naive(file_dt):
                        file_dt = timezone.make_aware(file_dt, timezone.get_current_timezone())
                except Exception:
                    continue
                
                if not (start_dt <= file_dt <= end_dt):
                    continue
                
                lm = obj.get('LastModified')
                matched_keys.append({
                    'key': key,
                    'mtime': lm.timestamp() if lm else 0,
                    'size': int(obj.get('Size') or 0),
                })
    except Exception as e:
        return Response({"error": f"S3 list failed: {str(e)}"}, status=500)

    if not matched_keys:
        return Response({"error": "No log files found in the specified range"}, status=404)

    # 按 key 排序（key 中包含时间戳，自然排序即可）
    matched_keys.sort(key=lambda x: x['key'])

    # 生成下载文件名
    date_tag = f"{start_dt.strftime('%Y%m%d')}-{end_dt.strftime('%Y%m%d')}"
    filter_tag = ""
    if namespace_filter:
        filter_tag += f"_{namespace_filter}"
    if pod_filter:
        filter_tag += f"_{pod_filter}"
    download_name = f"{log_type}_logs_{date_tag}{filter_tag}.log"

    # 流式合并下载
    def merged_stream():
        buffer = bytearray()
        for item in matched_keys:
            try:
                obj = s3_client.get_object(Bucket=task.s3_bucket, Key=item['key'])
                yield f"\n# === {item['key']} ===\n".encode('utf-8')
                for chunk in iter(lambda: obj['Body'].read(64 * 1024), b''):
                    yield chunk
            except Exception:
                yield f"\n# === ERROR reading {item['key']} ===\n".encode('utf-8')

    resp = StreamingHttpResponse(merged_stream(), content_type='text/plain; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="{download_name}"'
    resp['X-Total-Files'] = str(len(matched_keys))
    return resp


@api_view(['POST'])
@permission_classes([HasRolePermission])
def monitor_log_batch_search(request):
    data = request.data
    task_id = data.get('task_id')
    filenames = data.get('filenames', [])
    keyword = data.get('keyword', '')
    
    if not task_id or not filenames or not keyword:
        return Response({"error": "Missing parameters"}, status=400)

    try:
        task = MonitorTask.objects.get(pk=task_id)
    except MonitorTask.DoesNotExist:
        return Response({"results": []})

    s3_client = _get_s3_client(task)
    results = []
    MAX_TOTAL_RESULTS = 2000
    keywords = keyword.lower().split()
    log_dir = os.path.join(monitor_engine.LOG_DIR, str(task_id))
    prefixes = _task_s3_prefixes(task)

    for fname in filenames:
        if len(results) >= MAX_TOTAL_RESULTS:
            break
            
        # Decide if S3 or Local
        is_s3 = False
        if s3_client and any(str(fname).startswith(p) for p in prefixes):
            is_s3 = True
        
        if is_s3:
            try:
                obj = s3_client.get_object(Bucket=task.s3_bucket, Key=fname)
                for i, line in enumerate(_iter_s3_lines(obj['Body']), 1):
                    ll = line.lower()
                    if all(k in ll for k in keywords):
                        results.append({"file": fname, "line": i, "content": line.strip()})
                        if len(results) >= MAX_TOTAL_RESULTS:
                            break
            except Exception:
                pass
        else:
            # Local
            if os.path.sep in fname or '..' in fname:
                continue
            fpath = os.path.join(log_dir, fname)
            if not os.path.exists(fpath):
                continue
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    for i, line in enumerate(f, 1):
                        line_lower = line.lower()
                        if all(k in ll for k in keywords):
                            results.append({"file": fname, "line": i, "content": line.strip()})
                            if len(results) >= MAX_TOTAL_RESULTS:
                                break
            except Exception:
                pass

    return Response({"results": results})
