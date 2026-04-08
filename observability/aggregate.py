"""
时间窗聚合：QPS、错误率、延迟分位数、按 host/path 的 TopN。
PostgreSQL / SQLite：ORM 查询；OBSERVABILITY_OLAP_MODE=analytics 时优先 ClickHouse。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .models import LogEvent

logger = logging.getLogger(__name__)


@dataclass
class StreamSummary:
    stream_key: str
    window_minutes: int
    window_start: datetime
    window_end: datetime
    total: int
    errors: int
    error_rate: float
    qps: float
    p50_rt: Optional[float]
    p95_rt: Optional[float]
    p99_rt: Optional[float]
    top_hosts: list[dict[str, Any]]
    top_paths_5xx: list[dict[str, Any]]
    top_paths_slow: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_key": self.stream_key,
            "window_minutes": self.window_minutes,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "total": self.total,
            "errors": self.errors,
            "error_rate": round(self.error_rate, 4),
            "qps": round(self.qps, 4),
            "latency_ms": {
                "p50": _ms(self.p50_rt),
                "p95": _ms(self.p95_rt),
                "p99": _ms(self.p99_rt),
            },
            "top_hosts": self.top_hosts,
            "top_paths_5xx": self.top_paths_5xx,
            "top_paths_slow": self.top_paths_slow,
        }


def _ms(sec: Optional[float]) -> Optional[float]:
    if sec is None:
        return None
    return round(sec * 1000, 2)


def _percentile(sorted_vals: list[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def summarize_stream(stream_key: str, window_minutes: int = 60) -> StreamSummary:
    window_end = timezone.now()
    window_start = window_end - timedelta(minutes=max(1, window_minutes))

    if getattr(settings, "OBSERVABILITY_OLAP_MODE", "off") == "analytics":
        try:
            from .clickhouse_store import _ch_enabled, summarize_stream_clickhouse

            if _ch_enabled():
                d = summarize_stream_clickhouse(
                    stream_key, window_start, window_end, window_minutes
                )
                return StreamSummary(
                    stream_key=d["stream_key"],
                    window_minutes=d["window_minutes"],
                    window_start=d["window_start"],
                    window_end=d["window_end"],
                    total=d["total"],
                    errors=d["errors"],
                    error_rate=d["error_rate"],
                    qps=d["qps"],
                    p50_rt=d["p50_rt"],
                    p95_rt=d["p95_rt"],
                    p99_rt=d["p99_rt"],
                    top_hosts=d["top_hosts"],
                    top_paths_5xx=d["top_paths_5xx"],
                    top_paths_slow=d["top_paths_slow"],
                )
        except Exception as e:
            logger.warning("observability CH summarize fallback ORM: %s", e)

    return _summarize_stream_postgres(
        stream_key, window_minutes, window_start, window_end
    )


def _summarize_stream_postgres(
    stream_key: str,
    window_minutes: int,
    window_start: datetime,
    window_end: datetime,
) -> StreamSummary:
    base = LogEvent.objects.filter(
        stream_key=stream_key,
        event_time__gte=window_start,
        event_time__lte=window_end,
    )
    total = base.count()
    errors = base.filter(status_code__gte=400).count()
    err_rate = (errors / total) if total else 0.0
    secs = max(window_minutes * 60, 1)
    qps = total / secs

    # 分位数：最多采样 30k 条 request_time，降低 SQLite 压力
    rts = list(
        base.exclude(request_time__isnull=True)
        .order_by("-event_time")
        .values_list("request_time", flat=True)[:30000]
    )
    rts.sort()
    p50 = _percentile(rts, 50)
    p95 = _percentile(rts, 95)
    p99 = _percentile(rts, 99)

    # Top hosts
    host_rows = (
        base.values("host")
        .annotate(n=Count("id"))
        .order_by("-n")[:8]
    )
    top_hosts = [{"host": r["host"] or "—", "count": r["n"]} for r in host_rows]

    # 5xx paths
    p5 = (
        base.filter(status_code__gte=500)
        .values("path")
        .annotate(n=Count("id"))
        .order_by("-n")[:8]
    )
    top_paths_5xx = [
        {"path": (r["path"] or "")[:200], "count": r["n"]} for r in p5
    ]

    # Slow paths (avg rt)
    slow: dict[str, list[float]] = {}
    for row in (
        base.exclude(request_time__isnull=True)
        .order_by("-event_time")
        .values("path", "request_time")[:8000]
    ):
        pth = (row["path"] or "")[:200]
        if not pth:
            continue
        slow.setdefault(pth, []).append(float(row["request_time"]))
    slow_avg = [
        (p, sum(v) / len(v), max(v)) for p, v in slow.items() if v
    ]
    slow_avg.sort(key=lambda x: -x[1])
    top_paths_slow = [
        {"path": p, "avg_rt_ms": round(avg * 1000, 2), "max_rt_ms": round(mx * 1000, 2)}
        for p, avg, mx in slow_avg[:8]
    ]

    return StreamSummary(
        stream_key=stream_key,
        window_minutes=window_minutes,
        window_start=window_start,
        window_end=window_end,
        total=total,
        errors=errors,
        error_rate=err_rate,
        qps=qps,
        p50_rt=p50,
        p95_rt=p95,
        p99_rt=p99,
        top_hosts=top_hosts,
        top_paths_5xx=top_paths_5xx,
        top_paths_slow=top_paths_slow,
    )


def compare_windows(
    stream_key: str, recent_m: int = 15, baseline_m: int = 15
) -> dict[str, Any]:
    """用于「流量突降」类 detector：近 recent 与之前 baseline 两段请求量对比。"""
    if getattr(settings, "OBSERVABILITY_OLAP_MODE", "off") == "analytics":
        try:
            from .clickhouse_store import _ch_enabled, compare_windows_clickhouse

            if _ch_enabled():
                return compare_windows_clickhouse(stream_key, recent_m, baseline_m)
        except Exception as e:
            logger.warning("observability CH compare_windows fallback ORM: %s", e)

    end = timezone.now()
    r0 = end - timedelta(minutes=recent_m)
    b0 = r0 - timedelta(minutes=baseline_m)
    recent = LogEvent.objects.filter(
        stream_key=stream_key, event_time__gte=r0, event_time__lte=end
    ).count()
    baseline = LogEvent.objects.filter(
        stream_key=stream_key, event_time__gte=b0, event_time__lt=r0
    ).count()
    ratio = (recent / baseline) if baseline else None
    return {
        "recent_count": recent,
        "baseline_count": baseline,
        "ratio": ratio,
        "recent_start": r0.isoformat(),
        "baseline_start": b0.isoformat(),
    }
