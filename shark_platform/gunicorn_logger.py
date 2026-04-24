"""
Gunicorn: disable per-request access logging (use nginx/gunicorn error at warn if needed for ops).
Re-enable in entrypoint: pass a standard Logger and --access-logfile - for debugging.
"""
from gunicorn.glogging import Logger


class FilteredAccessLogger(Logger):
    def access(self, resp, req, environ, request_time):
        return
