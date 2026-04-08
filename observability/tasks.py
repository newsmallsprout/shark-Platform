from __future__ import annotations

import logging

from celery import shared_task

from .ingest import prune_stream
from .models import LogEvent
from .pipeline import run_observability_pipeline_impl

logger = logging.getLogger(__name__)


@shared_task(name="observability.run_pipeline")
def run_observability_pipeline(stream_key: str, window_minutes: int = 60) -> dict:
    return run_observability_pipeline_impl(stream_key, window_minutes=window_minutes)


@shared_task(name="observability.prune_all")
def prune_all_streams_task() -> dict:
    from django.db.models import Count

    keys = LogEvent.objects.values("stream_key").annotate(n=Count("id"))
    total = 0
    for row in keys:
        total += prune_stream(row["stream_key"])
    return {"pruned_rows": total}
