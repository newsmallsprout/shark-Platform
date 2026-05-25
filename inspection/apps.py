from django.apps import AppConfig
import os
import logging
import sys

logger = logging.getLogger("inspection")

_scheduler_started = False

class InspectionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inspection'

    def ready(self):
        global _scheduler_started
        if _scheduler_started:
            return

        is_runserver = 'runserver' in sys.argv
        should_start = (os.environ.get('RUN_MAIN') == 'true') if is_runserver else True
        if not should_start:
            return
        
        try:
            from django.conf import settings
            try:
                from zoneinfo import ZoneInfo
            except Exception:
                from backports.zoneinfo import ZoneInfo
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            from .engine import inspection_engine
            
            def run_inspection_task():
                try:
                    logger.info("Starting daily inspection task...")
                    inspection_engine.run()
                    logger.info("Daily inspection task completed.")
                except Exception:
                    logger.exception("Daily inspection task failed")

            tz = ZoneInfo(getattr(settings, 'TIME_ZONE', 'UTC') or 'UTC')
            scheduler = BackgroundScheduler(timezone=tz)
            job = scheduler.add_job(
                run_inspection_task,
                trigger=CronTrigger(hour=8, minute=0, timezone=tz),
                id='daily_inspection',
                max_instances=1,
                coalesce=True,
                misfire_grace_time=6 * 60 * 60,
                replace_existing=True
            )
            scheduler.start()
            _scheduler_started = True
            logger.info("Inspection scheduler started: Daily at 08:00")
            try:
                logger.info(f"Inspection next run: {job.next_run_time}")
            except Exception:
                pass
            
        except ImportError as e:
            logger.warning(f"Daily inspection scheduler disabled due to ImportError: {e}")
        except Exception:
            logger.exception("Failed to start inspection scheduler")
