from django.apps import AppConfig


class MonitorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'monitor'

    def ready(self):
        import os
        import sys
        
        # Determine if we are running in the main process (Gunicorn) 
        # or the inner process of runserver.
        # Gunicorn does not set RUN_MAIN, but runserver does for the inner reloader.
        # We want to avoid running in the outer runserver process.
        
        is_runserver = 'runserver' in sys.argv
        should_start = False
        
        if is_runserver:
            # Only start in the inner process of runserver
            if os.environ.get('RUN_MAIN') == 'true':
                should_start = True
        else:
            # Assume Gunicorn or other production WSGI server -> always start
            # (Assuming single worker as per entrypoint.sh)
            should_start = True
            
        if should_start:
            from .engine import monitor_engine
            monitor_engine.start()
