from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import FileResponse, HttpResponseNotFound
import os
from .models import MonitorTask
from .engine import monitor_engine
from django.forms.models import model_to_dict

@api_view(['GET', 'POST'])
def monitor_tasks(request):
    if request.method == 'GET':
        tasks = MonitorTask.objects.all()
        return Response([model_to_dict(t) for t in tasks])
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
            slack_webhook_url=data.get('slack_webhook_url', ''),
            poll_interval_seconds=data.get('poll_interval_seconds', 60),
            alert_keywords=data.get('alert_keywords', []),
            ignore_keywords=data.get('ignore_keywords', []),
            record_only_keywords=data.get('record_only_keywords', [])
        )
        return Response(model_to_dict(task))

@api_view(['GET', 'PUT', 'DELETE'])
def monitor_task_detail(request, pk):
    try:
        task = MonitorTask.objects.get(pk=pk)
    except MonitorTask.DoesNotExist:
        return Response({"error": "Task not found"}, status=404)
        
    if request.method == 'GET':
        return Response(model_to_dict(task))
        
    elif request.method == 'PUT':
        data = request.data
        for field in [
            "name", "enabled", "k8s_namespace", "k8s_kubeconfig", 
            "s3_archive_enabled", "s3_bucket", "s3_region", "s3_access_key", "s3_secret_key", "s3_endpoint",
            "retention_days", "slack_webhook_url", "poll_interval_seconds",
            "alert_keywords", "ignore_keywords", "record_only_keywords"
        ]:
            if field in data:
                setattr(task, field, data[field])
        task.save()
        
        # Trigger engine update if needed (engine loop should handle DB changes automatically)
        return Response(model_to_dict(task))
        
    elif request.method == 'DELETE':
        task.delete()
        return Response({"msg": "deleted"})

@api_view(['GET'])
def monitor_logs(request):
    # Optional task_id filter
    task_id = request.query_params.get('task_id')
    
    base_dir = monitor_engine.LOG_DIR
    if task_id:
        # Check if task log dir exists
        log_dir = os.path.join(base_dir, str(task_id))
    else:
        # If no task_id, maybe list all logs recursively? 
        # For now let's return empty or require task_id. 
        # Actually user wants "Click into task -> show logs". So task_id is expected.
        return Response([])

    if not os.path.exists(log_dir):
        return Response([])
    
    files = []
    try:
        for f in os.listdir(log_dir):
            if f.endswith(".log"):
                full_path = os.path.join(log_dir, f)
                stat = os.stat(full_path)
                files.append({
                    "name": f,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime
                })
        # Sort by mtime desc
        files.sort(key=lambda x: x['mtime'], reverse=True)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
        
    return Response(files)

@api_view(['GET'])
def monitor_log_download(request):
    filename = request.query_params.get('filename')
    task_id = request.query_params.get('task_id')
    
    if not filename or not task_id:
        return Response({"error": "filename and task_id required"}, status=400)
    
    # Security check
    if os.path.sep in filename or '..' in filename or os.path.sep in task_id or '..' in task_id:
         return Response({"error": "invalid parameters"}, status=400)
         
    log_dir = os.path.join(monitor_engine.LOG_DIR, str(task_id))
    file_path = os.path.join(log_dir, filename)
    
    if not os.path.exists(file_path):
        return HttpResponseNotFound("File not found")
        
    return FileResponse(open(file_path, 'rb'), as_attachment=True, filename=filename)

