import threading
from typing import Dict, List, Any
import os

from tasks.schemas import SyncTaskRequest
from tasks.models import SyncTask
from tasks.utils import save_task_config, delete_task_config
from core.logging import log
from .worker import SyncWorker

class TaskManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: Dict[str, SyncWorker] = {}

    def is_running(self, task_id: str) -> bool:
        with self._lock:
            w = self._tasks.get(task_id)
            return bool(w and getattr(w, "_status", None) == "running")

    def start(self, cfg: SyncTaskRequest):
        save_task_config(cfg)
        
        # Update status in DB
        try:
            t = SyncTask.objects.get(task_id=cfg.task_id)
            t.status = "running"
            t.save()
        except SyncTask.DoesNotExist:
            pass

        w = SyncWorker(cfg)
        with self._lock:
            self._tasks[cfg.task_id] = w
        threading.Thread(target=w.run, daemon=True).start()

    def start_by_id(self, task_id: str):
        try:
            t = SyncTask.objects.get(task_id=task_id)
            cfg = SyncTaskRequest(**t.config)
            
            t.status = "running"
            t.save()
            
            w = SyncWorker(cfg)
            with self._lock:
                self._tasks[task_id] = w
            threading.Thread(target=w.run, daemon=True).start()
        except SyncTask.DoesNotExist:
            raise FileNotFoundError("Task config not found")

    def stop(self, task_id: str):
        with self._lock:
            w = self._tasks.get(task_id)
            if w is not None:
                w.stop()
                del self._tasks[task_id]
        
        try:
            t = SyncTask.objects.get(task_id=task_id)
            t.status = "stopped"
            t.save()
        except SyncTask.DoesNotExist:
            pass
            
        log(task_id, "Task stopped")

    def stop_soft(self, task_id: str):
        with self._lock:
            w = self._tasks.get(task_id)
            if w is not None:
                w.stop()
                try:
                    w._status = "stopped"
                except Exception:
                    pass
        
        try:
            t = SyncTask.objects.get(task_id=task_id)
            t.status = "stopped"
            t.save()
        except SyncTask.DoesNotExist:
            pass

        log(task_id, "Task stopped (soft)")

    def delete(self, task_id: str):
        self.stop(task_id)
        delete_task_config(task_id)
        # delete logs?
        lp = os.path.join("logs", f"{task_id}.log")
        if os.path.exists(lp):
            os.remove(lp)
        log(task_id, "Task deleted")

    def reset(self, task_id: str):
        try:
            t = SyncTask.objects.get(task_id=task_id)
            t.state = {}
            t.save()
        except SyncTask.DoesNotExist:
            pass
        log(task_id, "Task reset (state cleared)")

    def list_tasks(self) -> List[str]:
        # Return all tasks from DB
        return list(SyncTask.objects.values_list('task_id', flat=True))

    def get_all_tasks_status(self) -> List[Dict]:
        res = []
        # Get status from running workers
        with self._lock:
            for tid, w in self._tasks.items():
                res.append(w.get_status())
        
        # Merge with DB tasks that are not running
        running_ids = set(t['task_id'] for t in res)
        db_tasks = SyncTask.objects.all()
        for t in db_tasks:
            if t.task_id not in running_ids:
                res.append({
                    "task_id": t.task_id,
                    "status": "stopped",
                    "metrics": t.state.get("metrics", {}),
                    "config": {} # Populate if needed
                })
        return res

    def get_task_status(self, task_id: str) -> Dict:
        # Check running tasks first
        with self._lock:
            w = self._tasks.get(task_id)
            if w:
                return w.get_status()
        
        # Check DB
        try:
            t = SyncTask.objects.get(task_id=task_id)
            return {
                "task_id": t.task_id,
                "status": "stopped",
                "metrics": t.state.get("metrics", {}),
                "config": {} 
            }
        except SyncTask.DoesNotExist:
            return None

    def restore_from_disk(self):
        # Restore from DB
        tasks = SyncTask.objects.filter(status="running")
        for t in tasks:
            try:
                cfg = SyncTaskRequest(**t.config)
                self.start(cfg)
            except Exception as e:
                log("startup", f"restore failed {t.task_id}: {e}")

task_manager = TaskManager()
