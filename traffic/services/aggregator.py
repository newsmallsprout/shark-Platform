from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import numpy as np

RANGE_MAP = {
    "10m": timedelta(minutes=10),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def parse_range(range_key: str) -> timedelta:
    return RANGE_MAP.get(range_key, timedelta(hours=24))


def window_bounds(range_key: str) -> Tuple[float, float]:
    end = datetime.now(timezone.utc).timestamp()
    start = end - parse_range(range_key).total_seconds()
    return start, end


def bucket_seconds(range_key: str) -> int:
    if range_key == "10m":
        return 10
    if range_key == "1h":
        return 10
    if range_key == "6h":
        return 60
    if range_key == "24h":
        return 60
    if range_key == "7d":
        return 3600
    if range_key == "30d":
        return 86400
    return 60


def filter_records(
    records: List[Dict[str, Any]], start: float, end: float
) -> List[Dict[str, Any]]:
    return [r for r in records if start <= r["ts"] <= end]


def aggregate_timeseries(
    records: List[Dict[str, Any]], range_key: str
) -> Dict[str, Any]:
    start, end = window_bounds(range_key)
    recs = filter_records(records, start, end)
    bs = bucket_seconds(range_key)
    if not recs:
        return _empty_ts(start, end, bs)

    buckets: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in recs:
        b = int(r["ts"] // bs) * bs
        buckets[b].append(r)

    times = sorted(buckets.keys())
    qps = []
    reqs = []
    p50, p95, p99 = [], [], []
    s2, s4, s5 = [], [], []

    for t in times:
        group = buckets[t]
        n = len(group)
        dur = max(bs, 1)
        qps.append([int(t * 1000), round(n / dur, 4)])
        reqs.append([int(t * 1000), n])
        lat = [x["request_time_ms"] for x in group if x.get("request_time_ms") is not None]
        if lat:
            arr = np.array(lat, dtype=float)
            p50.append([int(t * 1000), float(np.percentile(arr, 50))])
            p95.append([int(t * 1000), float(np.percentile(arr, 95))])
            p99.append([int(t * 1000), float(np.percentile(arr, 99))])
        else:
            p50.append([int(t * 1000), 0.0])
            p95.append([int(t * 1000), 0.0])
            p99.append([int(t * 1000), 0.0])
        c2 = sum(1 for x in group if 200 <= x["status"] < 400)
        c4 = sum(1 for x in group if 400 <= x["status"] < 500)
        c5 = sum(1 for x in group if x["status"] >= 500)
        s2.append([int(t * 1000), round(c2 / dur, 4)])
        s4.append([int(t * 1000), round(c4 / dur, 4)])
        s5.append([int(t * 1000), round(c5 / dur, 4)])

    return {
        "bucket_sec": bs,
        "range": range_key,
        "qps": qps,
        "requests": reqs,
        "latency": {"p50": p50, "p95": p95, "p99": p99},
        "status_stack": {"2xx": s2, "4xx": s4, "5xx": s5},
    }


def _empty_ts(start: float, end: float, bs: int) -> Dict[str, Any]:
    times = []
    t = int(start // bs) * bs
    end_ts = int(end)
    while t <= end_ts:
        times.append(t)
        t += bs
    if len(times) > 200:
        times = times[-200:]
    def z():
        return [[int(x * 1000), 0] for x in times]
    return {
        "bucket_sec": bs,
        "range": "",
        "qps": z(),
        "requests": z(),
        "latency": {"p50": z(), "p95": z(), "p99": z()},
        "status_stack": {"2xx": z(), "4xx": z(), "5xx": z()},
    }


def error_detail_from_records(recs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """4xx/5xx 汇总 + 按路径拆分各状态码（仅原始记录可用）。"""
    n2 = n4 = n5 = 0
    path_codes: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for r in recs:
        try:
            st = int(r.get("status") or 0)
        except (TypeError, ValueError):
            st = 0
        uri = str(r.get("request_uri") or "/")
        if 200 <= st < 400:
            n2 += 1
        elif 400 <= st < 500:
            n4 += 1
            path_codes[uri][st] += 1
        elif st >= 500:
            n5 += 1
            path_codes[uri][st] += 1
    n_err = n4 + n5
    total = len(recs) or 1

    path_items: List[Dict[str, Any]] = []
    for path, cmap in path_codes.items():
        tot_path = sum(cmap.values())
        codes = [
            {
                "code": c,
                "count": n,
                "pct_path": round(n / tot_path * 100, 1) if tot_path else 0.0,
            }
            for c, n in sorted(cmap.items(), key=lambda x: x[0])
        ]
        path_items.append(
            {"path": path, "total_errors": tot_path, "codes": codes}
        )
    path_items.sort(key=lambda x: -x["total_errors"])
    path_code_breakdown = path_items[:50]

    return {
        "n_2xx": n2,
        "n_4xx": n4,
        "n_5xx": n5,
        "n_err": n_err,
        "pct_4xx": round(n4 / total * 100, 3),
        "pct_5xx": round(n5 / total * 100, 3),
        "path_code_breakdown": path_code_breakdown,
        "rollup": False,
        "rollup_no_status_breakdown": False,
        "rollup_no_path_errors": False,
    }


def overview_kpis(records: List[Dict[str, Any]], range_key: str) -> Dict[str, Any]:
    start, end = window_bounds(range_key)
    recs = filter_records(records, start, end)
    now = datetime.now(timezone.utc).timestamp()
    window_60 = [r for r in recs if r["ts"] >= now - 60]
    qps = len(window_60) / 60.0 if window_60 else 0.0

    total = len(recs)
    err = sum(1 for r in recs if r["status"] >= 400)
    err_rate = (err / total * 100) if total else 0.0
    lats = [r["request_time_ms"] for r in recs if r.get("request_time_ms")]
    avg_lat = float(np.mean(lats)) if lats else 0.0

    # Mini series: last 30 points of qps from aggregate
    ts_data = aggregate_timeseries(records, range_key)
    spark_qps = ts_data["qps"][-40:]
    spark_err = []
    for row in ts_data["requests"]:
        t = row[0]
        # approximate error slice — re-bucket not worth it; use status_stack
        spark_err.append([t, 0.0])
    # simple error spark from same buckets
    b = ts_data["bucket_sec"]
    recs_by_bucket: Dict[int, List] = defaultdict(list)
    for r in recs:
        bt = int(r["ts"] // b) * b
        recs_by_bucket[bt].append(r)
    err_spark = []
    for t in sorted(recs_by_bucket.keys())[-40:]:
        g = recs_by_bucket[t]
        n = len(g)
        e = sum(1 for x in g if x["status"] >= 400)
        err_spark.append([int(t * 1000), round(e / n * 100, 3) if n else 0.0])

    return {
        "range": range_key,
        "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_requests": total,
        "total_requests_delta_pct": 0.0,
        "qps": round(qps, 4),
        "latency_avg_ms": round(avg_lat, 2),
        "error_rate_pct": round(err_rate, 3),
        "availability_pct": round(100.0 - min(err_rate, 100.0), 3),
        "series": {"qps": spark_qps, "error_rate": err_spark[-len(spark_qps) :]},
        "error_detail": error_detail_from_records(recs),
    }


def geo_aggregate(
    records: List[Dict[str, Any]],
    range_key: str,
    granularity: str,
    country_filter: str,
) -> Dict[str, Any]:
    from .geo_centroids import centroid_for_country

    start, end = window_bounds(range_key)
    recs = filter_records(records, start, end)

    if granularity == "province" and (country_filter or "").upper() == "CN":
        counts: Dict[str, int] = defaultdict(int)
        for r in recs:
            if (r.get("country_code") or "").upper() != "CN":
                continue
            key = r.get("subdivision") or "Unknown"
            counts[key] += 1
        items = []
        for name, n in sorted(counts.items(), key=lambda x: -x[1])[:80]:
            items.append(
                {
                    "code": name,
                    "name": name,
                    "lat": 35.0,
                    "lng": 105.0,
                    "requests": n,
                }
            )
        return {"range": range_key, "granularity": "province", "items": items}

    counts = defaultdict(int)
    names: Dict[str, str] = {}
    for r in recs:
        code = r.get("country_code") or "??"
        counts[code] += 1
        names[code] = r.get("country_name") or code

    items = []
    for code, n in sorted(counts.items(), key=lambda x: -x[1])[:200]:
        lat_lng = centroid_for_country(code) if code not in ("LAN", "??") else None
        sample = next((x for x in recs if x.get("country_code") == code), None)
        lat, lng = 0.0, 0.0
        if sample and sample.get("lat") is not None:
            lat = float(sample["lat"])
            lng = float(sample.get("lng") or 0.0)
        elif lat_lng:
            lat, lng = lat_lng[0], lat_lng[1]
        items.append(
            {
                "code": code,
                "name": names.get(code, code),
                "lat": lat,
                "lng": lng,
                "requests": n,
            }
        )
    return {"range": range_key, "granularity": "country", "items": items}


def top_lists(
    records: List[Dict[str, Any]], range_key: str, top_type: str, limit: int
) -> Dict[str, Any]:
    start, end = window_bounds(range_key)
    recs = filter_records(records, start, end)
    limit = max(1, min(limit, 100))

    if top_type == "paths":
        by_uri: Dict[str, List] = defaultdict(list)
        for r in recs:
            by_uri[r["request_uri"]].append(r)
        rows = []
        for uri, group in by_uri.items():
            n = len(group)
            lats = [x["request_time_ms"] for x in group]
            p95 = float(np.percentile(lats, 95)) if lats else 0.0
            e5 = sum(1 for x in group if x["status"] >= 500)
            rows.append(
                {
                    "path": uri,
                    "requests": n,
                    "p95_ms": round(p95, 2),
                    "errors_5xx": e5,
                    "share_pct": 0.0,
                }
            )
        rows.sort(key=lambda x: -x["requests"])
        total = len(recs) or 1
        for r in rows:
            r["share_pct"] = round(r["requests"] / total * 100, 2)
        return {"type": "paths", "range": range_key, "items": rows[:limit]}

    if top_type == "slow":
        by_uri: Dict[str, List] = defaultdict(list)
        for r in recs:
            by_uri[r["request_uri"]].append(r)
        rows = []
        for uri, group in by_uri.items():
            lats = [x["request_time_ms"] for x in group]
            if not lats:
                continue
            rows.append(
                {
                    "path": uri,
                    "requests": len(group),
                    "p95_ms": round(float(np.percentile(lats, 95)), 2),
                    "p99_ms": round(float(np.percentile(lats, 99)), 2),
                    "max_ms": round(float(max(lats)), 2),
                }
            )
        rows.sort(key=lambda x: -x["p95_ms"])
        return {"type": "slow", "range": range_key, "items": rows[:limit]}

    if top_type == "status":
        buckets: Dict[str, int] = defaultdict(int)
        for r in recs:
            fam = f"{r['status'] // 100}xx" if r["status"] else "0xx"
            buckets[fam] += 1
        items = [{"name": k, "value": v} for k, v in sorted(buckets.items())]
        return {"type": "status", "range": range_key, "items": items}

    if top_type == "ip":
        by_ip: Dict[str, int] = defaultdict(int)
        for r in recs:
            by_ip[r.get("remote_addr") or "-"] += 1
        rows = [
            {"ip": ip, "requests": n, "country": ""}
            for ip, n in sorted(by_ip.items(), key=lambda x: -x[1])[:limit]
        ]
        for row in rows:
            sample = next(
                (x for x in recs if x.get("remote_addr") == row["ip"]), None
            )
            row["country"] = (sample or {}).get("country_name") or ""
        return {"type": "ip", "range": range_key, "items": rows}

    return {"type": top_type, "range": range_key, "items": []}
