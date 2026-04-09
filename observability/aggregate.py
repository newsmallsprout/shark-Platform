"""
时间窗聚合：QPS、错误率、延迟分位数、按 host/path 的 TopN。
PostgreSQL / SQLite：ORM 查询；OBSERVABILITY_OLAP_MODE=analytics 时优先 ClickHouse。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, List, Optional

from django.conf import settings
from django.db.models import Avg, Count
from django.utils import timezone

from .models import LogEvent
from .time_buckets import heatmap_bucket_secs_and_labels

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
                ch_total = int(d.get("total") or 0)
                # CH 未同步/表空时查询仍“成功”为 0，大屏会误显示无流量；PG 有数据则回退 ORM
                if ch_total == 0:
                    pg = _summarize_stream_postgres(
                        stream_key, window_minutes, window_start, window_end
                    )
                    if pg.total > 0:
                        logger.warning(
                            "observability stream=%s: ClickHouse 窗口内 0 条，PostgreSQL 有 %s 条，大屏改用 PG 聚合",
                            stream_key,
                            pg.total,
                        )
                        return pg
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


# 大屏可视化：按 Host 哈希到六大区（无 GeoIP 时的示意地域分布）
_REGION_NAMES = ("华北", "华东", "华南", "西南", "西北", "海外")


def _geo_flow_display_name(country: str, city: str) -> str:
    co = (country or "").strip()
    ci = (city or "").strip()
    if co and ci:
        return f"{co} · {ci}"[:160]
    if co:
        return co[:160]
    if ci:
        return ci[:160]
    return ""


def _host_to_region(host: str) -> str:
    s = (host or "").strip() or "—"
    i = int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16) % len(_REGION_NAMES)
    return _REGION_NAMES[i]


def _build_time_heatmap(
    stream_key: str,
    window_start: datetime,
    window_end: datetime,
    *,
    buckets: int = 24,
) -> dict[str, Any]:
    """时间轴等分桶请求量，供前端 ECharts 热力图。"""
    buckets = max(4, min(buckets, 48))
    bucket_secs, labels = heatmap_bucket_secs_and_labels(
        window_start, window_end, buckets=buckets
    )
    counts = [0] * buckets
    qs = LogEvent.objects.filter(
        stream_key=stream_key,
        event_time__gte=window_start,
        event_time__lte=window_end,
    ).values_list("event_time", flat=True)
    for et in qs.iterator(chunk_size=8000):
        if timezone.is_naive(et):
            et = timezone.make_aware(et, timezone.get_current_timezone())
        if et < window_start or et > window_end:
            continue
        rel = (et - window_start).total_seconds()
        idx = int(rel / bucket_secs)
        if idx >= buckets:
            idx = buckets - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1
    return {"labels": labels, "counts": counts}


def _build_region_flow_legacy_host(
    stream_key: str,
    window_start: datetime,
    window_end: datetime,
) -> List[dict[str, Any]]:
    rows = (
        LogEvent.objects.filter(
            stream_key=stream_key,
            event_time__gte=window_start,
            event_time__lte=window_end,
        )
        .values("host")
        .annotate(n=Count("id"))
    )
    acc: dict[str, int] = {}
    for r in rows:
        reg = _host_to_region(r["host"] or "")
        acc[reg] = acc.get(reg, 0) + int(r["n"] or 0)
    ordered = sorted(acc.items(), key=lambda x: -x[1])
    return [{"name": k, "value": v, "lat": None, "lon": None} for k, v in ordered]


def _top_client_ips(
    stream_key: str,
    window_start: datetime,
    window_end: datetime,
    *,
    limit: int = 8,
) -> List[dict[str, Any]]:
    """按请求量 Top 的访客 IP（GeoIP 依据）；与 Host 头 Top 对照用。"""
    rows = (
        LogEvent.objects.filter(
            stream_key=stream_key,
            event_time__gte=window_start,
            event_time__lte=window_end,
        )
        .exclude(client_ip="")
        .values("client_ip")
        .annotate(n=Count("id"))
        .order_by("-n")[: max(1, min(limit, 32))]
    )
    return [
        {"ip": (r["client_ip"] or "")[:64], "count": int(r["n"] or 0)} for r in rows
    ]


def _build_region_flow(
    stream_key: str,
    window_start: datetime,
    window_end: datetime,
) -> List[dict[str, Any]]:
    base = LogEvent.objects.filter(
        stream_key=stream_key,
        event_time__gte=window_start,
        event_time__lte=window_end,
    )
    geo_rows = list(
        base.exclude(geo_country="")
        .values("geo_country", "geo_city")
        .annotate(n=Count("id"), lat=Avg("geo_lat"), lon=Avg("geo_lon"))
        .order_by("-n")[:32]
    )
    out: List[dict[str, Any]] = []
    for r in geo_rows:
        co = (r.get("geo_country") or "").strip()
        ci = (r.get("geo_city") or "").strip()
        name = _geo_flow_display_name(co, ci) or "未知区域"
        lat, lon = r.get("lat"), r.get("lon")
        out.append(
            {
                "name": name[:160],
                "value": int(r["n"] or 0),
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
            }
        )
    n_no_geo = base.filter(geo_country="").count()
    n_empty_ip = base.filter(geo_country="", client_ip="").count()
    n_has_ip_no_geo = base.filter(geo_country="").exclude(client_ip="").count()
    if geo_rows and n_no_geo > 0:
        # 拆成两点，避免与真实 Geo 气泡叠在同一坐标；Host 头里的海外 IP ≠ 访客 IP
        if n_empty_ip > 0:
            out.append(
                {
                    "name": "无 client_ip（未解析出 IP：缺 remote_addr、为 “-”、非 JSON 行混入等）",
                    "value": n_empty_ip,
                    "lat": 26.0,
                    "lon": 101.0,
                }
            )
        if n_has_ip_no_geo > 0:
            out.append(
                {
                    "name": "有 IP · 仍无国家（内网/保留地址/缺 mmdb）",
                    "value": n_has_ip_no_geo,
                    "lat": 44.0,
                    "lon": 122.0,
                }
            )
    if geo_rows:
        return out
    if base.count() == 0:
        return []
    return _build_region_flow_legacy_host(stream_key, window_start, window_end)


def traffic_visual_extras(stream_key: str, window_minutes: int) -> dict[str, Any]:
    window_end = timezone.now()
    window_start = window_end - timedelta(minutes=max(1, window_minutes))
    if getattr(settings, "OBSERVABILITY_OLAP_MODE", "off") == "analytics":
        try:
            from .clickhouse_store import (
                _ch_enabled,
                count_events_window_clickhouse,
                traffic_visual_extras_clickhouse,
            )

            if _ch_enabled():
                n_ch = count_events_window_clickhouse(
                    stream_key, window_start, window_end
                )
                if n_ch > 0:
                    return traffic_visual_extras_clickhouse(
                        stream_key, window_start, window_end, window_minutes
                    )
        except Exception as e:
            logger.warning("observability CH traffic_visual_extras fallback ORM: %s", e)

    return {
        "time_heatmap": _build_time_heatmap(
            stream_key, window_start, window_end, buckets=24
        ),
        "region_flow": _build_region_flow(stream_key, window_start, window_end),
        "top_client_ips": _top_client_ips(stream_key, window_start, window_end),
    }
