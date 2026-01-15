import time
import os
import threading
import datetime
import glob
import logging
import json
import requests
from django.conf import settings
from .models import MonitorTask
try:
    from kubernetes import client, config as k8s_config
    from kubernetes.client.rest import ApiException
except ImportError:
    client = None
    k8s_config = None

try:
    import boto3
    from botocore.exceptions import NoCredentialsError
except ImportError:
    boto3 = None

logger = logging.getLogger("monitor")

class MonitorEngine:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.LOG_DIR = os.path.join(settings.BASE_DIR, "logs", "monitor_logs")
        os.makedirs(self.LOG_DIR, exist_ok=True)

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info("Monitor engine started")

    def stop(self):
        self._stop_event.set()
        with self._lock:
            if self._thread:
                self._thread.join(timeout=5)
                self._thread = None
        logger.info("Monitor engine stopped")

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                # Iterate over all enabled tasks
                tasks = MonitorTask.objects.filter(enabled=True)
                if not tasks:
                    time.sleep(5)
                    continue

                for task in tasks:
                    if self._stop_event.is_set():
                        break
                        
                    # Basic scheduling: run if last_run is older than interval
                    # Or just run every loop and let loop sleep handle it?
                    # Better: Check timestamp.
                    now = datetime.datetime.now()
                    
                    # Convert last_run to offset-naive if needed, or handle timezone
                    # Simplified: if last_run is None or (now - last_run).total_seconds() > poll_interval
                    should_run = False
                    if not task.last_run:
                        should_run = True
                    else:
                        # Assuming naive or matching tz
                        try:
                            delta = now.timestamp() - task.last_run.timestamp()
                            if delta >= task.poll_interval_seconds:
                                should_run = True
                        except:
                            should_run = True # Fallback
                            
                    if should_run:
                        try:
                            self._process_task(task)
                            task.last_run = now
                            task.last_error = "" # clear error on success
                            task.save(update_fields=['last_run', 'last_error', 'alerts_sent_count'])
                        except Exception as e:
                            logger.error(f"Error processing task {task.name}: {e}")
                            task.last_error = str(e)
                            task.save(update_fields=['last_error'])
                
                # Global sleep - maybe shorter to check for new tasks/schedule
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                time.sleep(10)

    def _process_task(self, task):
        # 1. Fetch Logs
        self._fetch_k8s_logs(task)
        
        # 2. Rotate & Archive
        self._rotate_and_archive(task)

    def _get_k8s_client(self, task):
        if not client:
            raise ImportError("kubernetes package not installed")
            
        if task.k8s_kubeconfig:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as tf:
                tf.write(task.k8s_kubeconfig)
                tf.flush()
                k8s_config.load_kube_config(config_file=tf.name)
                os.unlink(tf.name)
        else:
            try:
                k8s_config.load_incluster_config()
            except:
                k8s_config.load_kube_config()
        
        return client.CoreV1Api()

    def _fetch_k8s_logs(self, task):
        api = self._get_k8s_client(task)
        namespace = task.k8s_namespace
        
        try:
            pods = api.list_namespaced_pod(namespace)
        except Exception as e:
            raise Exception(f"Failed to list pods: {e}")

        today_str = datetime.date.today().isoformat()
        
        # Task specific log dir
        task_log_dir = os.path.join(self.LOG_DIR, str(task.id))
        os.makedirs(task_log_dir, exist_ok=True)
        
        for pod in pods.items:
            pod_name = pod.metadata.name
            if not pod.spec.containers:
                continue
            container_name = pod.spec.containers[0].name
            
            log_file_path = os.path.join(task_log_dir, f"{pod_name}_{today_str}.log")
            
            since_seconds = task.poll_interval_seconds + 10
            
            try:
                logs = api.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    container=container_name,
                    since_seconds=since_seconds,
                    timestamps=True 
                )
                
                if logs:
                    with open(log_file_path, "a", encoding="utf-8") as f:
                        f.write(logs)
                        if not logs.endswith('\n'):
                            f.write('\n')
                    
                    self._analyze_logs(logs, task, pod_name)
                    
            except Exception as e:
                # logger.warning(f"Failed to read log for {pod_name}: {e}")
                pass

    def _analyze_logs(self, log_content, task, source_name):
        if not task.alert_keywords:
            return

        lines = log_content.splitlines()
        alerts = []
        
        for line in lines:
            if any(k in line for k in task.ignore_keywords):
                continue
            if any(k in line for k in task.alert_keywords):
                alerts.append(line)
        
        if alerts:
            self._send_slack_alert(alerts, task, source_name)

    def _send_slack_alert(self, alerts, task, source):
        if not task.slack_webhook_url:
            return
            
        msg = f"🚨 *Alert in {source} (Task: {task.name})*\n"
        snippet = "\n".join(alerts[:10])
        if len(alerts) > 10:
            snippet += f"\n... and {len(alerts)-10} more lines"
            
        payload = {
            "text": msg + "```" + snippet + "```"
        }
        
        try:
            requests.post(task.slack_webhook_url, json=payload, timeout=5)
            task.alerts_sent_count += 1
            # We don't save task here to avoid excessive DB writes, rely on loop update
        except Exception as e:
            logger.error(f"Failed to send slack alert: {e}")

    def _rotate_and_archive(self, task):
        retention = task.retention_days
        cutoff_date = datetime.date.today() - datetime.timedelta(days=retention)
        
        task_log_dir = os.path.join(self.LOG_DIR, str(task.id))
        if not os.path.exists(task_log_dir):
            return
            
        files = glob.glob(os.path.join(task_log_dir, "*.log"))
        
        s3 = None
        if task.s3_archive_enabled and task.s3_bucket and boto3:
            try:
                s3 = boto3.client(
                    's3',
                    region_name=task.s3_region,
                    aws_access_key_id=task.s3_access_key,
                    aws_secret_access_key=task.s3_secret_key,
                    endpoint_url=task.s3_endpoint
                )
            except Exception as e:
                logger.error(f"Failed to init S3: {e}")
                return

        for fp in files:
            fname = os.path.basename(fp)
            try:
                parts = fname.rsplit('_', 1)
                if len(parts) != 2:
                    continue
                date_part = parts[1].replace('.log', '')
                file_date = datetime.date.fromisoformat(date_part)
                
                if file_date <= cutoff_date:
                    if s3 and task.s3_archive_enabled:
                        s3_key = f"logs/{task.name}/{file_date.year}/{file_date.month}/{file_date.day}/{fname}"
                        try:
                            s3.upload_file(fp, task.s3_bucket, s3_key)
                            logger.info(f"Uploaded {fname} to S3")
                        except Exception as e:
                            logger.error(f"Failed to upload {fname}: {e}")
                            continue 
                    
                    try:
                        os.remove(fp)
                        logger.info(f"Deleted old log {fname}")
                    except Exception as e:
                        logger.error(f"Failed to delete {fname}: {e}")
                        
            except ValueError:
                continue


monitor_engine = MonitorEngine()
