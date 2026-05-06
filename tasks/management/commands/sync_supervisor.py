import os
import threading
import time

from django.core.management.base import BaseCommand

from core.logging import log
from tasks.models import SyncTask
from tasks.schemas import SyncTaskRequest
from tasks.sync.task_manager import task_manager
from tasks.sync.worker import SyncWorker


class Command(BaseCommand):
    help = (
        "Run normal SyncWorker threads in this single process when "
        "SHARK_SYNC_NORMAL_MODE=supervisor. Web workers must not start local sync threads."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-restore",
            action="store_true",
            help="Do not call restore_from_disk on startup (tests / manual recovery).",
        )

    def handle(self, *args, **options):
        os.environ["SHARK_SYNC_SUPERVISOR_PROCESS"] = "1"
        if not options.get("skip_restore"):
            try:
                task_manager.restore_from_disk()
            except Exception as e:
                log("supervisor", f"restore_from_disk failed: {e}")

        interval = float((os.environ.get("SHARK_SYNC_SUPERVISOR_POLL_SEC") or "2").strip() or "2")
        if interval < 0.25:
            interval = 0.25

        self.stdout.write(self.style.NOTICE(f"sync_supervisor polling every {interval}s"))
        while True:
            try:
                self._tick()
            except Exception as e:
                log("supervisor", f"tick error: {e}")
            time.sleep(interval)

    def _tick(self):
        for t in SyncTask.objects.filter(status="running").exclude(turbo_enabled=True):
            with task_manager._lock:
                if t.task_id in task_manager._tasks:
                    continue
            try:
                cfg = SyncTaskRequest(**(t.config or {}))
            except Exception as e:
                log(t.task_id, f"supervisor: invalid config, skip: {e}")
                continue
            w = SyncWorker(cfg)
            with task_manager._lock:
                if t.task_id in task_manager._tasks:
                    continue
                task_manager._tasks[t.task_id] = w
            threading.Thread(target=w.run, daemon=True).start()
            log(t.task_id, "supervisor: started worker")

        with task_manager._lock:
            snapshot = list(task_manager._tasks.items())
        for tid, w in snapshot:
            try:
                t = SyncTask.objects.get(task_id=tid)
                if t.status == "running":
                    continue
            except SyncTask.DoesNotExist:
                pass
            w.stop()
            with task_manager._lock:
                task_manager._tasks.pop(tid, None)
            log(tid, "supervisor: stopped worker (DB not running)")
