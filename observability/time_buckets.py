"""时间窗等分桶标签（热力图），供 ORM 与 ClickHouse 共用。"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone


def heatmap_bucket_secs_and_labels(
    window_start: datetime,
    window_end: datetime,
    *,
    buckets: int = 24,
) -> tuple[float, list[str]]:
    buckets = max(4, min(buckets, 48))
    total_secs = max(1.0, (window_end - window_start).total_seconds())
    bucket_secs = total_secs / buckets
    labels: list[str] = []
    for i in range(buckets):
        mid = window_start + timedelta(seconds=i * bucket_secs + bucket_secs / 2)
        if timezone.is_naive(mid):
            mid = timezone.make_aware(mid)
        labels.append(mid.astimezone(timezone.get_current_timezone()).strftime("%H:%M"))
    return bucket_secs, labels
