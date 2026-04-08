from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LogEvent, LogStream
from .parsers import parse_line

logger = logging.getLogger(__name__)


def infer_log_format(
    log_format: str,
    source_file: Optional[str] = None,
    sample_line: Optional[str] = None,
) -> str:
    """
    平台侧自动识别：*.json.log / access_*.json.log 类文件 -> nginx_json；
    首行以 { 开头亦按 JSON 行处理。
    """
    fmt = (log_format or "auto").strip().lower()
    if fmt and fmt != "auto":
        return fmt
    fn = (source_file or "").lower()
    if fn.endswith(".json.log") or ".json.log" in fn:
        return "nginx_json"
    s = (sample_line or "").lstrip()
    if s.startswith("{"):
        return "nginx_json"
    return "auto"


def _max_events() -> int:
    return int(getattr(settings, "OBSERVABILITY_MAX_EVENTS_PER_STREAM", 200_000))


def prune_stream(stream_key: str) -> int:
    """超出上限时按时间删除最旧事件。"""
    max_e = _max_events()
    qs = LogEvent.objects.filter(stream_key=stream_key)
    n = qs.count()
    if n <= max_e:
        return 0
    to_drop = n - max_e
    deleted = 0
    batch = 2000
    while deleted < to_drop:
        ids = list(
            qs.order_by("event_time").values_list("pk", flat=True)[:batch]
        )
        if not ids:
            break
        LogEvent.objects.filter(pk__in=ids).delete()
        deleted += len(ids)
    return deleted


def ingest_log_batch(
    lines: List[str],
    *,
    source_label: str = "edge",
    stream_key: str | None = None,
    log_format: str = "auto",
    source_file: str | None = None,
) -> Tuple[int, int, int]:
    """
    解析并落库。返回 (parsed_count, raw_line_count, pruned_approx)。
    stream_key 建议为域名或「环境+域名」slug；采集端可从 access_api.json.log 推导出 api。
    """
    sk = (stream_key or source_label or "default").strip()[:128]
    sample = next(
        (x.strip() for x in lines if isinstance(x, str) and x.strip()),
        None,
    )
    fmt = infer_log_format(log_format, source_file, sample)

    events: List[LogEvent] = []
    for raw in lines:
        if not isinstance(raw, str):
            continue
        line = raw.strip()
        if not line:
            continue
        data = parse_line(line, fmt)
        if not data:
            continue
        events.append(
            LogEvent(
                stream_key=sk,
                event_time=data["event_time"],
                host=data.get("host") or "",
                method=data.get("method") or "",
                path=data.get("path") or "",
                status_code=int(data.get("status_code") or 0),
                bytes_sent=int(data.get("bytes_sent") or 0),
                request_time=data.get("request_time"),
                upstream_time=data.get("upstream_time") or "",
                parser=data.get("parser") or "",
                raw_excerpt=line[:512],
            )
        )

    raw_count = len([x for x in lines if isinstance(x, str) and x.strip()])

    if not events:
        return 0, raw_count, 0

    display_name = sk
    if source_file:
        bn = os.path.basename(str(source_file))
        display_name = f"{sk} · {bn}"[:256]

    with transaction.atomic():
        LogStream.objects.update_or_create(
            stream_key=sk,
            defaults={
                "display_name": display_name,
                "last_event_at": timezone.now(),
            },
        )
        LogEvent.objects.bulk_create(events, batch_size=500)

    pruned = prune_stream(sk)

    if getattr(settings, "OBSERVABILITY_OLAP_MODE", "off") in ("mirror", "analytics"):
        try:
            from .clickhouse_store import insert_log_events_from_orm

            insert_log_events_from_orm(events)
        except Exception as e:
            logger.warning("observability clickhouse mirror failed: %s", e)

    logger.info(
        "observability ingest stream=%s parsed=%s raw=%s pruned=%s",
        sk,
        len(events),
        raw_count,
        pruned,
    )
    return len(events), raw_count, pruned
