"""
Build Traffic Dashboard snapshot JSON from persisted TrafficMinuteRollup rows (custom time range).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone as dj_timezone

from ..models import TrafficDashboardConfig, TrafficMinuteRollup
from .blackbox import fetch_blackbox_summary
from .geo_centroids import centroid_for_country
from .log_sources import log_source_configured
from .redis_log_buffer import is_configured as redis_buffer_configured


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _norm_bt_key(bt: Any) -> datetime:
    if bt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if getattr(bt, "tzinfo", None):
        return bt.astimezone(timezone.utc)
    return bt.replace(tzinfo=timezone.utc)


def _rollup_row_key(r: Any) -> Tuple[datetime, str]:
    bt = _norm_bt_key(getattr(r, "bucket_start", None))
    sid = str(getattr(r, "source_id", "") or "")
    return (bt, sid)


def fetch_rollups_for_range(start: datetime, end: datetime, source_id: str) -> List[Any]:
    """
    Postgres：近期与回退；ClickHouse：长期。合并时同一 (bucket_start, source_id) 以 CH 为准。
    """
    from .clickhouse_rollups import query_minute_rollups_clickhouse

    pg_rows = query_rollups(start, end, source_id)
    ch_rows = query_minute_rollups_clickhouse(start, end, source_id)
    if ch_rows is None:
        return pg_rows
    merged: Dict[Tuple[datetime, str], Any] = {}
    for r in pg_rows:
        merged[_rollup_row_key(r)] = r
    for r in ch_rows:
        merged[_rollup_row_key(r)] = r
    return sorted(merged.values(), key=_rollup_row_key)


def query_rollups(start: datetime, end: datetime, source_id: str) -> List[TrafficMinuteRollup]:
    start = _utc(start)
    end = _utc(end)
    if end <= start:
        return []
    qs = TrafficMinuteRollup.objects.filter(bucket_start__gte=start, bucket_start__lt=end).order_by(
        "bucket_start", "source_id"
    )
    sid = (source_id or "").strip()
    if sid and sid != "all":
        qs = qs.filter(source_id=sid)
    return list(qs)


def _merge_by_minute(rows: List[Any]) -> List[Dict[str, Any]]:
    by: Dict[datetime, Dict[str, Any]] = {}
    for r in rows:
        k = getattr(r, "bucket_start", None)
        if k is None:
            continue
        if k not in by:
            by[k] = {
                "bucket_start": k,
                "requests": 0,
                "sum_latency_ms": 0,
                "count_latency": 0,
                "status_2xx": 0,
                "status_4xx": 0,
                "status_5xx": 0,
                "p50_w": [],
                "p95_w": [],
                "p99_w": [],
                "geo_counts": defaultdict(int),
                "top_paths": defaultdict(int),
            }
        b = by[k]
        b["requests"] += int(getattr(r, "requests", 0) or 0)
        b["sum_latency_ms"] += int(getattr(r, "sum_latency_ms", 0) or 0)
        b["count_latency"] += int(getattr(r, "count_latency", 0) or 0)
        b["status_2xx"] += int(getattr(r, "status_2xx", 0) or 0)
        b["status_4xx"] += int(getattr(r, "status_4xx", 0) or 0)
        b["status_5xx"] += int(getattr(r, "status_5xx", 0) or 0)
        n = int(getattr(r, "requests", 0) or 0)
        if n > 0:
            p50 = getattr(r, "p50_ms", None)
            p95 = getattr(r, "p95_ms", None)
            p99 = getattr(r, "p99_ms", None)
            if p50 is not None:
                b["p50_w"].append((float(p50), n))
            if p95 is not None:
                b["p95_w"].append((float(p95), n))
            if p99 is not None:
                b["p99_w"].append((float(p99), n))
        for cc, nv in (getattr(r, "geo_counts", None) or {}).items():
            b["geo_counts"][cc] += int(nv)
        for item in getattr(r, "top_paths", None) or []:
            p = item.get("path") or ""
            b["top_paths"][p] += int(item.get("requests") or 0)

    def wavg(pairs: List[Tuple[float, int]]) -> float:
        tot = sum(n for _, n in pairs)
        if not tot:
            return 0.0
        return sum(p * n for p, n in pairs) / tot

    out = []
    for k in sorted(by.keys()):
        b = by[k]
        pairs50, pairs95, pairs99 = b["p50_w"], b["p95_w"], b["p99_w"]
        out.append(
            {
                "bucket_start": k,
                "requests": b["requests"],
                "sum_latency_ms": b["sum_latency_ms"],
                "count_latency": b["count_latency"],
                "status_2xx": b["status_2xx"],
                "status_4xx": b["status_4xx"],
                "status_5xx": b["status_5xx"],
                "p50_ms": wavg(pairs50) if pairs50 else 0.0,
                "p95_ms": wavg(pairs95) if pairs95 else 0.0,
                "p99_ms": wavg(pairs99) if pairs99 else 0.0,
                "geo_counts": dict(b["geo_counts"]),
                "top_paths": dict(b["top_paths"]),
            }
        )
    return out


def _timeseries_from_merged(merged: List[Dict[str, Any]], range_label: str) -> Dict[str, Any]:
    bs = 60
    qps, reqs, p50, p95, p99 = [], [], [], [], []
    s2, s4, s5 = [], [], []
    for b in merged:
        t = int(b["bucket_start"].timestamp())
        ms = int(t * 1000)
        n = b["requests"]
        qps.append([ms, round(n / bs, 4)])
        reqs.append([ms, n])
        p50.append([ms, round(float(b["p50_ms"]), 3)])
        p95.append([ms, round(float(b["p95_ms"]), 3)])
        p99.append([ms, round(float(b["p99_ms"]), 3)])
        dur = float(bs)
        s2.append([ms, round(b["status_2xx"] / dur, 4)])
        s4.append([ms, round(b["status_4xx"] / dur, 4)])
        s5.append([ms, round(b["status_5xx"] / dur, 4)])
    return {
        "bucket_sec": bs,
        "range": range_label,
        "qps": qps,
        "requests": reqs,
        "latency": {"p50": p50, "p95": p95, "p99": p99},
        "status_stack": {"2xx": s2, "4xx": s4, "5xx": s5},
    }


def _overview_from_merged(
    merged: List[Dict[str, Any]], range_label: str, ts: Dict[str, Any]
) -> Dict[str, Any]:
    total = sum(b["requests"] for b in merged)
    s2 = sum(b["status_2xx"] for b in merged)
    s4 = sum(b["status_4xx"] for b in merged)
    s5 = sum(b["status_5xx"] for b in merged)
    err = s4 + s5
    err_rate = (err / total * 100) if total else 0.0
    sum_lat = sum(b["sum_latency_ms"] for b in merged)
    n_lat = sum(b["count_latency"] for b in merged)
    avg_lat = (sum_lat / n_lat) if n_lat else 0.0
    spark_qps = ts["qps"][-40:]
    spark_err = []
    recs_by_bucket = {int(b["bucket_start"].timestamp()): b for b in merged}
    for row in ts["requests"]:
        t_ms, n = row[0], row[1]
        t = t_ms // 1000
        bk = int(t // 60) * 60
        b = recs_by_bucket.get(bk)
        if not b or not n:
            spark_err.append([t_ms, 0.0])
        else:
            e = b["status_4xx"] + b["status_5xx"]
            spark_err.append([t_ms, round(e / n * 100, 3) if n else 0.0])
    qps_now = 0.0
    if merged:
        qps_now = round(float(merged[-1]["requests"]) / 60.0, 4)
    return {
        "range": range_label,
        "refreshed_at": dj_timezone.now().isoformat().replace("+00:00", "Z"),
        "total_requests": total,
        "total_requests_delta_pct": 0.0,
        "qps": qps_now,
        "latency_avg_ms": round(avg_lat, 2),
        "error_rate_pct": round(err_rate, 3),
        "availability_pct": round(100.0 - min(err_rate, 100.0), 3),
        "series": {"qps": spark_qps, "error_rate": spark_err[-len(spark_qps) :]},
        "error_detail": {
            "n_2xx": s2,
            "n_4xx": s4,
            "n_5xx": s5,
            "n_err": err,
            "pct_4xx": round(s4 / total * 100, 3) if total else 0.0,
            "pct_5xx": round(s5 / total * 100, 3) if total else 0.0,
            "top_error_paths": [],
            "rollup": True,
            "rollup_no_path_errors": True,
        },
    }


def _geo_from_merged(merged: List[Dict[str, Any]], range_label: str) -> Dict[str, Any]:
    counts: Dict[str, int] = defaultdict(int)
    for b in merged:
        for code, n in (b.get("geo_counts") or {}).items():
            counts[code or "??"] += int(n)
    items = []
    for code, n in sorted(counts.items(), key=lambda x: -x[1])[:200]:
        lat_lng = centroid_for_country(code) if code not in ("LAN", "??") else None
        lat, lng = (lat_lng[0], lat_lng[1]) if lat_lng else (0.0, 0.0)
        items.append(
            {
                "code": code,
                "name": code,
                "lat": lat,
                "lng": lng,
                "requests": n,
            }
        )
    return {"range": range_label, "granularity": "country", "items": items}


def _top_paths_from_merged(merged: List[Dict[str, Any]], range_label: str, limit: int) -> Dict[str, Any]:
    acc: Dict[str, int] = defaultdict(int)
    for b in merged:
        for p, n in (b.get("top_paths") or {}).items():
            acc[p] += int(n)
    total = sum(acc.values()) or 1
    rows = []
    for path, n in sorted(acc.items(), key=lambda x: -x[1])[:limit]:
        rows.append(
            {
                "path": path,
                "requests": n,
                "p95_ms": 0.0,
                "errors_5xx": 0,
                "share_pct": round(n / total * 100, 2),
            }
        )
    return {"type": "paths", "range": range_label, "items": rows}


def _top_status_from_merged(merged: List[Dict[str, Any]], range_label: str) -> Dict[str, Any]:
    s2 = sum(b["status_2xx"] for b in merged)
    s4 = sum(b["status_4xx"] for b in merged)
    s5 = sum(b["status_5xx"] for b in merged)
    items = [
        {"name": "2xx", "value": s2},
        {"name": "4xx", "value": s4},
        {"name": "5xx", "value": s5},
    ]
    return {"type": "status", "range": range_label, "items": items}


def build_rollups_snapshot(
    start: datetime,
    end: datetime,
    source_id: str,
    cfg: TrafficDashboardConfig,
    inspection,
    *,
    preset_range: Optional[str] = None,
) -> Dict[str, Any]:
    from .aggregator import _empty_ts

    rows = fetch_rollups_for_range(start, end, source_id)
    merged = _merge_by_minute(rows)
    span = end - start if end > start else timedelta(0)
    range_label = (preset_range or "").strip() or f"custom:{int(span.total_seconds())}s"
    if not merged:
        ts = _empty_ts(start.timestamp(), end.timestamp(), 60)
        ts["range"] = range_label
        ov = {
            "range": range_label,
            "refreshed_at": dj_timezone.now().isoformat().replace("+00:00", "Z"),
            "total_requests": 0,
            "total_requests_delta_pct": 0.0,
            "qps": 0.0,
            "latency_avg_ms": 0.0,
            "error_rate_pct": 0.0,
            "availability_pct": 100.0,
            "series": {"qps": [], "error_rate": []},
            "error_detail": {
                "n_2xx": 0,
                "n_4xx": 0,
                "n_5xx": 0,
                "n_err": 0,
                "pct_4xx": 0.0,
                "pct_5xx": 0.0,
                "top_error_paths": [],
                "rollup": True,
                "rollup_no_path_errors": True,
            },
        }
    else:
        ts = _timeseries_from_merged(merged, range_label)
        ov = _overview_from_merged(merged, range_label, ts)
    bb = fetch_blackbox_summary(cfg, inspection)
    ov["blackbox"] = bb
    if bb.get("availability_pct") is not None:
        ov["availability_pct"] = bb["availability_pct"]
    ov["log_configured"] = log_source_configured(cfg, redis_buffer_configured())
    ov["access_log_mode"] = (cfg.access_log_mode or "file").strip()
    ov["rollup"] = True
    ov["rollup_rows"] = len(rows)
    return {
        "overview": ov,
        "timeseries": ts,
        "geo": _geo_from_merged(merged, range_label),
        "top_paths": _top_paths_from_merged(merged, range_label, 10),
        "top_slow": {"type": "slow", "range": range_label, "items": []},
        "top_ip": {"type": "ip", "range": range_label, "items": []},
        "top_status": _top_status_from_merged(merged, range_label),
    }
