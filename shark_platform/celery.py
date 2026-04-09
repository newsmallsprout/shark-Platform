import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shark_platform.settings")

try:
    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    CeleryInstrumentor().instrument()
except Exception:
    pass

app = Celery("shark_platform")
broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", broker_url)
app.conf.update(
    broker_url=broker_url,
    result_backend=result_backend,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=os.environ.get("CELERY_TIMEZONE", "Asia/Shanghai"),
    enable_utc=True,
)
app.autodiscover_tasks()
