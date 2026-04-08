"""
ClickHouse OLAP：按月分区 MergeTree，摄取双写 + 聚合查询（与 Django ORM 解耦）。
依赖 clickhouse-connect（requirements 已声明）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import TYPE_CHECKING, Any, List

from django.conf import settings
from django.utils import timezone as dj_tz

if TYPE_CHECKING:
    from .models import LogEvent

logger = logging.getLogger(__name__)

_client = None
_schema_ready = False


def _ch_enabled() -> bool:
    mode = getattr(settings, "OBSERVABILITY_OLAP_MODE", "off")
    if mode not in ("mirror", "analytics"):
        return False
    return bool(getattr(settings, "CLICKHOUSE_HOST", "").strip())


def _utc_naive(dt: datetime) -> datetime:
    if dj_tz.is_naive(dt):
        return dt
    return dt.astimezone(dt_timezone.utc).replace(tzinfo=None)


def get_client():
    global _client
    if _client is not None:
        return _client
    import clickhouse_connect

    # 先连 default，确保库不存在时仍能执行 CREATE DATABASE
    _client = clickhouse_connect.get_client(
        host=settings.CLICKHOUSE_HOST,
        port=int(settings.CLICKHOUSE_PORT),
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD or None,
        database="default",
    )
    return _client


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready or not _ch_enabled():
        return
    try:
        c = get_client()
        db = settings.CLICKHOUSE_DATABASE
        c.command(f"CREATE DATABASE IF NOT EXISTS {db}")
        c.command(
            """
CREATE TABLE IF NOT EXISTS log_events (
    stream_key LowCardinality(String),
    event_time DateTime64(3, 'UTC'),
    host String,
    method LowCardinality(String),
    path String,
    status_code UInt16,
    bytes_sent UInt32,
    request_time Nullable(Float64),
    upstream_time String,
    parser LowCardinality(String),
    raw_excerpt String
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(toDate(event_time))
ORDER BY (stream_key, event_time, status_code, cityHash64(path))
TTL toDateTime(event_time) + INTERVAL 180 DAY
SETTINGS index_granularity = 8192
"""
        )
        _schema_ready = True
        logger.info("clickhouse schema ensured db=%s", db)
    except Exception as e:
        logger.warning("clickhouse ensure_schema failed: %s", e)
        raise


def insert_log_events_from_orm(events: List[LogEvent]) -> None:
    if not events or not _ch_enabled():
        return
    ensure_schema()
    c = get_client()
    db = settings.CLICKHOUSE_DATABASE
    rows = []
    for e in events:
        rt = e.request_time
        rows.append(
            [
                e.stream_key[:128],
                _utc_naive(e.event_time),
                (e.host or "")[:255],
                (e.method or "")[:16],
                (e.path or "")[:8000],
                int(e.status_code or 0),
                int(e.bytes_sent or 0),
                float(rt) if rt is not None else None,
                (e.upstream_time or "")[:64],
                (e.parser or "")[:32],
                (e.raw_excerpt or "")[:512]
                if getattr(settings, "CLICKHOUSE_STORE_RAW_EXCERPT", False)
                else "",
            ]
        )
    c.insert(
        f"{db}.log_events",
        rows,
        column_names=[
            "stream_key",
            "event_time",
            "host",
            "method",
            "path",
            "status_code",
            "bytes_sent",
            "request_time",
            "upstream_time",
            "parser",
            "raw_excerpt",
        ],
    )


def summarize_stream_clickhouse(
    stream_key: str,
    window_start: datetime,
    window_end: datetime,
    window_minutes: int,
) -> dict[str, Any]:
    """返回构建 StreamSummary 的字段（caller 负责组装 dataclass）。"""
    if not _ch_enabled():
        raise RuntimeError("clickhouse disabled")
    ensure_schema()
    c = get_client()
    db = settings.CLICKHOUSE_DATABASE
    wstart = _utc_naive(window_start)
    wend = _utc_naive(window_end)
    sk = stream_key[:128]

    r1 = c.query(
        f"""
        SELECT
            count() AS total,
            countIf(status_code >= 400) AS errors,
            quantile(0.5)(request_time) AS p50,
            quantile(0.95)(request_time) AS p95,
            quantile(0.99)(request_time) AS p99
        FROM {db}.log_events
        WHERE stream_key = {{sk:String}}
          AND event_time >= {{t0:DateTime64(3, 'UTC')}}
          AND event_time <= {{t1:DateTime64(3, 'UTC')}}
        """,
        parameters={"sk": sk, "t0": wstart, "t1": wend},
    )
    row = r1.result_rows[0] if r1.result_rows else (0, 0, None, None, None)
    total, errors, p50, p95, p99 = row[0], row[1], row[2], row[3], row[4]
    total = int(total or 0)
    errors = int(errors or 0)
    err_rate = (errors / total) if total else 0.0
    secs = max(window_minutes * 60, 1)
    qps = total / secs

    def _f(x) -> float | None:
        if x is None:
            return None
        try:
            v = float(x)
            if v != v:  # nan
                return None
            return v
        except (TypeError, ValueError):
            return None

    hosts = c.query(
        f"""
        SELECT host, count() AS n
        FROM {db}.log_events
        WHERE stream_key = {{sk:String}}
          AND event_time >= {{t0:DateTime64(3, 'UTC')}}
          AND event_time <= {{t1:DateTime64(3, 'UTC')}}
        GROUP BY host
        ORDER BY n DESC
        LIMIT 8
        """,
        parameters={"sk": sk, "t0": wstart, "t1": wend},
    )
    top_hosts = [
        {"host": (h or "—"), "count": int(n)} for h, n in hosts.result_rows
    ]

    p5xx = c.query(
        f"""
        SELECT path, count() AS n
        FROM {db}.log_events
        WHERE stream_key = {{sk:String}}
          AND event_time >= {{t0:DateTime64(3, 'UTC')}}
          AND event_time <= {{t1:DateTime64(3, 'UTC')}}
          AND status_code >= 500
        GROUP BY path
        ORDER BY n DESC
        LIMIT 8
        """,
        parameters={"sk": sk, "t0": wstart, "t1": wend},
    )
    top_paths_5xx = [
        {"path": (p or "")[:200], "count": int(n)} for p, n in p5xx.result_rows
    ]

    slow = c.query(
        f"""
        SELECT path, avg(request_time) AS avg_rt, max(request_time) AS max_rt
        FROM {db}.log_events
        WHERE stream_key = {{sk:String}}
          AND event_time >= {{t0:DateTime64(3, 'UTC')}}
          AND event_time <= {{t1:DateTime64(3, 'UTC')}}
          AND request_time IS NOT NULL
        GROUP BY path
        ORDER BY avg_rt DESC
        LIMIT 8
        """,
        parameters={"sk": sk, "t0": wstart, "t1": wend},
    )
    top_paths_slow = [
        {
            "path": (p or "")[:200],
            "avg_rt_ms": round(float(avg or 0) * 1000, 2),
            "max_rt_ms": round(float(mx or 0) * 1000, 2),
        }
        for p, avg, mx in slow.result_rows
    ]

    return {
        "stream_key": stream_key,
        "window_minutes": window_minutes,
        "window_start": window_start,
        "window_end": window_end,
        "total": total,
        "errors": errors,
        "error_rate": err_rate,
        "qps": qps,
        "p50_rt": _f(p50),
        "p95_rt": _f(p95),
        "p99_rt": _f(p99),
        "top_hosts": top_hosts,
        "top_paths_5xx": top_paths_5xx,
        "top_paths_slow": top_paths_slow,
    }


def compare_windows_clickhouse(
    stream_key: str, recent_m: int = 15, baseline_m: int = 15
) -> dict[str, Any]:
    if not _ch_enabled():
        raise RuntimeError("clickhouse disabled")
    ensure_schema()
    c = get_client()
    db = settings.CLICKHOUSE_DATABASE
    end = dj_tz.now()
    r0 = end - timedelta(minutes=recent_m)
    b0 = r0 - timedelta(minutes=baseline_m)
    sk = stream_key[:128]
    e_na, r_na, b_na = _utc_naive(end), _utc_naive(r0), _utc_naive(b0)

    r_recent = c.query(
        f"""
        SELECT count()
        FROM {db}.log_events
        WHERE stream_key = {{sk:String}}
          AND event_time >= {{r0:DateTime64(3, 'UTC')}}
          AND event_time <= {{end:DateTime64(3, 'UTC')}}
        """,
        parameters={"sk": sk, "r0": r_na, "end": e_na},
    )
    r_base = c.query(
        f"""
        SELECT count()
        FROM {db}.log_events
        WHERE stream_key = {{sk:String}}
          AND event_time >= {{b0:DateTime64(3, 'UTC')}}
          AND event_time < {{r0:DateTime64(3, 'UTC')}}
        """,
        parameters={"sk": sk, "b0": b_na, "r0": r_na},
    )
    recent_c = int(r_recent.result_rows[0][0] if r_recent.result_rows else 0)
    base_c = int(r_base.result_rows[0][0] if r_base.result_rows else 0)
    ratio = (recent_c / base_c) if base_c else None
    return {
        "recent_count": recent_c,
        "baseline_count": base_c,
        "ratio": ratio,
        "recent_start": r0.isoformat(),
        "baseline_start": b0.isoformat(),
    }
