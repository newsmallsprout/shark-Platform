"""把 inspect-prd.sh 的检查清单落到 Prometheus 即时查询。

PVC 用量优先用已在 PRD 部署的 pvc-stats-exporter（pvc_stats_*），
没有时再退回 kubelet_volume_stats_*。
K8s 对象状态依赖 kube-state-metrics；没有对应指标时检查项为 skip，不假装正常。
中间件先扫 Prom 指标名，对上前缀才检查，不写死实例。
"""

import time

from .catalog import (
    HIDE_NAMESPACES,
    JOB_FAIL_LOOKBACK_SEC,
    POD_FAIL_LOOKBACK_SEC,
    KNOWN_NORMALS,
    METRIC_FAMILY_RECIPES,
    PVC_CRIT_PCT,
    PVC_WARN_PCT,
    RESOURCE_DELTA_WARN_PT,
    STALE_HOSTDOWN_NAMES,
    UP_METRIC_DENY,
    display_name,
    hidden_namespace,
    recipe_covers_metric,
    resolve_service,
)

PVC_USED_QUERIES = [
    "pvc_stats_used_bytes",
    "kubelet_volume_stats_used_bytes",
]
PVC_CAP_QUERIES = [
    "pvc_stats_capacity_bytes",
    "kubelet_volume_stats_capacity_bytes",
]


def _metric(series):
    return (series or {}).get("metric") or {}


def _num(series):
    try:
        return float((series.get("value") or [None, "0"])[1])
    except (TypeError, ValueError, IndexError):
        return 0.0


def _label(series, *keys):
    m = _metric(series)
    for k in keys:
        v = m.get(k)
        if v:
            return str(v)
    return ""


def _pvc_key(series):
    m = _metric(series)
    ns = m.get("namespace") or "-"
    pvc = m.get("persistentvolumeclaim") or ""
    if pvc:
        return f"{ns}/{pvc}", ns, pvc
    inst = m.get("instance") or "series"
    mp = m.get("mountpoint") or ""
    if mp:
        return f"{inst} {mp}", "", inst
    return inst, "", inst


def _join_used_cap(used_rows, cap_rows):
    cap_map = {}
    for row in cap_rows:
        key, ns, name = _pvc_key(row)
        cap_map[key] = (_num(row), ns, name)
    items = []
    seen = set()
    for row in used_rows:
        key, ns, name = _pvc_key(row)
        if key in seen:
            continue
        seen.add(key)
        used = _num(row)
        cap, cap_ns, cap_name = cap_map.get(key, (0.0, ns, name))
        ns = ns or cap_ns
        name = name or cap_name
        pct = int(round(used / cap * 100)) if cap > 0 else -1
        alias = resolve_service(namespace=ns, name=name)
        items.append({
            "key": key,
            "namespace": ns,
            "pvc": name,
            "service": display_name(namespace=ns, name=name),
            "used_bytes": int(used),
            "capacity_bytes": int(cap),
            "pct": pct,
            "baseline": (alias or {}).get("baseline") or "",
            "usage_alert": True if not alias else bool(alias.get("usage_alert", True)),
            "source": "prometheus",
        })
    items.sort(key=lambda x: (x["pct"] if x["pct"] is not None else -1), reverse=True)
    return items


def collect_pvc_usage(query_fn):
    pairs = list(zip(PVC_USED_QUERIES, PVC_CAP_QUERIES))
    chosen = None
    for used_q, cap_q in pairs:
        used_rows = query_fn(used_q) or []
        cap_rows = query_fn(cap_q) or []
        items = _join_used_cap(used_rows, cap_rows)
        readable = [x for x in items if isinstance(x.get("pct"), (int, float)) and x["pct"] >= 0]
        if readable:
            chosen = (used_q, cap_q, items)
            break
        if items and chosen is None:
            chosen = (used_q, cap_q, items)
    if not chosen:
        used_q, cap_q, items = PVC_USED_QUERIES[0], PVC_CAP_QUERIES[0], []
    else:
        used_q, cap_q, items = chosen
    source = "pvc_stats_*" if used_q.startswith("pvc_stats") else used_q
    readable = [x for x in items if isinstance(x.get("pct"), (int, float)) and x["pct"] >= 0]
    _attach_pvc_delta_24h(query_fn, used_q, cap_q, readable)
    return {
        "available": bool(readable),
        "source": source,
        "used_query": used_q,
        "capacity_query": cap_q,
        "items": readable,
        "top": readable,
    }


def _attach_pvc_delta_24h(query_fn, used_q, cap_q, items):
    if not items:
        return
    past = _join_used_cap(
        query_fn(f"{used_q} offset 24h") or [],
        query_fn(f"{cap_q} offset 24h") or [],
    )
    by_key = {x["key"]: x for x in past}
    for item in items:
        old = by_key.get(item["key"])
        if not old:
            continue
        old_pct, now_pct = old.get("pct"), item.get("pct")
        if not isinstance(old_pct, (int, float)) or old_pct < 0:
            continue
        if not isinstance(now_pct, (int, float)) or now_pct < 0:
            continue
        item["pct_24h"] = int(old_pct)
        item["delta_24h"] = round(float(now_pct) - float(old_pct), 1)


def _pct_by_instance(rows):
    out = {}
    for row in rows or []:
        inst = (_metric(row).get("instance") or "").strip()
        if not inst:
            continue
        try:
            out[inst] = round(_num(row), 2)
        except Exception:
            pass
    return out


def attach_server_deltas(servers, mem_24h_rows=None, disk_24h_rows=None):
    """当前占比减去 24h 前，单位是百分点。没有 24h 样本就空着。"""
    mem_map = _pct_by_instance(mem_24h_rows)
    disk_map = _pct_by_instance(disk_24h_rows)
    for s in servers or []:
        inst = s.get("instance") or ""
        now_mem, now_disk = s.get("mem_pct"), s.get("disk_pct")
        if inst in mem_map and isinstance(now_mem, (int, float)):
            s["mem_pct_24h"] = mem_map[inst]
            s["mem_delta_24h"] = round(float(now_mem) - mem_map[inst], 1)
        if inst in disk_map and isinstance(now_disk, (int, float)):
            s["disk_pct_24h"] = disk_map[inst]
            s["disk_delta_24h"] = round(float(now_disk) - disk_map[inst], 1)
    return servers


def _trend_label(name, kind, now_pct, delta):
    return f"{name} {kind} {now_pct:.0f}%（24h {delta:+.1f}pt）"


def collect_resource_trend_items(servers, pvc_items):
    items = []
    sampled = False
    for s in servers or []:
        name = s.get("node_name") or s.get("service") or s.get("instance") or "node"
        inst = s.get("instance") or name
        disk_d, mem_d = s.get("disk_delta_24h"), s.get("mem_delta_24h")
        if disk_d is not None or mem_d is not None:
            sampled = True
        if isinstance(disk_d, (int, float)) and disk_d >= RESOURCE_DELTA_WARN_PT:
            items.append({
                "key": f"trend:disk:{inst}",
                "label": _trend_label(name, "磁盘", float(s.get("disk_pct") or 0), disk_d),
            })
        if isinstance(mem_d, (int, float)) and mem_d >= RESOURCE_DELTA_WARN_PT:
            items.append({
                "key": f"trend:mem:{inst}",
                "label": _trend_label(name, "内存", float(s.get("mem_pct") or 0), mem_d),
            })
    for x in pvc_items or []:
        delta = x.get("delta_24h")
        if delta is not None:
            sampled = True
        if not x.get("usage_alert"):
            continue
        if not isinstance(delta, (int, float)) or delta < RESOURCE_DELTA_WARN_PT:
            continue
        name = x.get("service") or x.get("key") or "pvc"
        key = x.get("key") or ""
        extra = f" {key}" if key and key != name else ""
        items.append({
            "key": f"trend:pvc:{key or name}",
            "label": f"PVC {name}{extra} {float(x.get('pct') or 0):.0f}%（24h {delta:+.1f}pt）",
        })
    return sampled, items


def _series_names(rows, limit=40):
    names = []
    for row in rows[:limit]:
        m = _metric(row)
        ns = m.get("namespace") or ""
        name = (
            m.get("persistentvolumeclaim")
            or m.get("pod")
            or m.get("deployment")
            or m.get("job_name")
            or m.get("horizontalpodautoscaler")
            or m.get("name")
            or m.get("node")
            or m.get("instance")
            or m.get("job")
            or m.get("alertname")
            or ""
        )
        svc = display_name(namespace=ns, name=name, instance=m.get("instance") or "")
        label = svc if svc != "-" else (f"{ns}/{name}" if ns and name else name or str(m))
        phase = m.get("phase") or ""
        if phase:
            label = f"{label} {phase}"
        names.append(label)
    return names


def _active_series(rows):
    """kube-state 每个 phase 都有一条 0/1，只保留值为 1 的当前态。"""
    return [r for r in (rows or []) if _num(r) == 1]


def _check(cid, name, level, result, detail=None, source="", items=None):
    if items is None:
        items = [{"key": f"{cid}:{x}", "label": str(x)} for x in (detail or [])]
    else:
        items = [dict(i) if isinstance(i, dict) else {"key": f"{cid}:{i}", "label": str(i)} for i in items]
        for it in items:
            it.setdefault("label", "")
            if not it.get("key"):
                it["key"] = f"{cid}:{it['label']}"
    return {
        "id": cid,
        "name": name,
        "level": level,
        "result": result,
        "detail": [i.get("label") for i in items],
        "items": items,
        "source": source,
    }


def _strip_ignored(checks, ignore_keys):
    keys = {str(k) for k in (ignore_keys or []) if k}
    if not keys:
        return checks
    out = []
    for c in checks:
        cid = c.get("id") or ""
        if f"check:{cid}" in keys and c.get("level") in ("warning", "critical", "info"):
            c = dict(c)
            c["level"] = "ok"
            c["result"] = "已忽略"
            c["items"] = []
            c["detail"] = []
            out.append(c)
            continue
        items = c.get("items") or []
        kept = [i for i in items if i.get("key") not in keys]
        if len(kept) == len(items):
            out.append(c)
            continue
        c = dict(c)
        c["items"] = kept
        c["detail"] = [i.get("label") for i in kept]
        if not kept and c.get("level") in ("warning", "critical"):
            c["level"] = "ok"
            c["result"] = "已忽略"
        out.append(c)
    return out


def _fold_uncovered(checks, middleware=None, metric_names=None):
    """skip 项收到最后一条「未覆盖」，避免和正常/告警混在一起。"""
    kept = [c for c in checks if c.get("level") != "skip"]
    skipped = [c for c in checks if c.get("level") == "skip"]
    names = [c.get("name") or c.get("id") for c in skipped]
    details = [f"{c.get('name')}：{c.get('result')}" for c in skipped]
    found_ids = {x.get("id") for x in (middleware or {}).get("items") or []}
    mw_already = any(c.get("id") == "middleware" for c in skipped)
    if metric_names and not mw_already:
        for spec in METRIC_FAMILY_RECIPES:
            if spec["id"] in found_ids:
                continue
            label = spec["name"]
            if label in names:
                continue
            prefixes = " / ".join(spec.get("prefixes") or []) or spec.get("up") or spec["id"]
            names.append(label)
            details.append(f"{label}：未扫到 {prefixes} 指标")
    if not names:
        return kept
    kept.append(_check(
        "uncovered",
        "未覆盖",
        "skip",
        "、".join(names),
        details,
        "prometheus",
    ))
    return kept


def _es_cluster_key(metric):
    m = metric or {}
    # elasticsearch-exporter 的 name 是节点名，不能当集群名
    return m.get("cluster") or m.get("cluster_name") or "elasticsearch"


def _es_node_key(metric):
    m = metric or {}
    return (
        m.get("name")
        or m.get("node")
        or m.get("es_node_name")
        or m.get("instance")
        or "node"
    )


def collect_elasticsearch(query_fn):
    """elasticsearch-exporter（monitor 里已有）。不调 _cluster/health HTTP。"""
    status_rows = query_fn("elasticsearch_cluster_health_status") or []
    if not status_rows:
        status_rows = query_fn("elasticsearch_clusterhealth_status") or []

    clusters = {}
    if status_rows:
        colored = [r for r in status_rows if _metric(r).get("color")]
        if colored:
            for row in colored:
                key = _es_cluster_key(_metric(row))
                entry = clusters.setdefault(key, {"cluster": key, "status": "unknown"})
                if _num(row) >= 1:
                    color = str(_metric(row).get("color") or "").lower()
                    if color in ("green", "yellow", "red"):
                        entry["status"] = color
        else:
            for row in status_rows:
                key = _es_cluster_key(_metric(row))
                val = int(round(_num(row)))
                status = {0: "green", 1: "yellow", 2: "red"}.get(val, "unknown")
                clusters[key] = {"cluster": key, "status": status}

    def _set_gauge(query, field):
        for row in query_fn(query) or []:
            key = _es_cluster_key(_metric(row))
            entry = clusters.setdefault(key, {"cluster": key, "status": "unknown"})
            entry[field] = int(_num(row))

    _set_gauge("elasticsearch_cluster_health_number_of_nodes", "nodes")
    _set_gauge("elasticsearch_cluster_health_number_of_data_nodes", "data_nodes")
    _set_gauge("elasticsearch_cluster_health_unassigned_shards", "unassigned_shards")
    _set_gauge("elasticsearch_cluster_health_active_shards", "active_shards")
    _set_gauge("elasticsearch_cluster_health_relocating_shards", "relocating_shards")

    heap_used = query_fn('elasticsearch_jvm_memory_used_bytes{area="heap"}') or query_fn("elasticsearch_jvm_memory_used_bytes") or []
    heap_max = query_fn('elasticsearch_jvm_memory_max_bytes{area="heap"}') or query_fn("elasticsearch_jvm_memory_max_bytes") or []
    max_map = {}
    for row in heap_max:
        m = _metric(row)
        max_map[(_es_cluster_key(m), _es_node_key(m))] = _num(row)
    heap_nodes = []
    for row in heap_used:
        m = _metric(row)
        ck, nk = _es_cluster_key(m), _es_node_key(m)
        cap = max_map.get((ck, nk)) or 0
        used = _num(row)
        pct = int(round(used / cap * 100)) if cap > 0 else -1
        heap_nodes.append({
            "cluster": ck,
            "node": nk,
            "used_bytes": int(used),
            "max_bytes": int(cap),
            "heap_pct": pct,
        })
        clusters.setdefault(ck, {"cluster": ck, "status": "unknown"})
    heap_nodes.sort(key=lambda x: x.get("heap_pct") if isinstance(x.get("heap_pct"), (int, float)) else -1, reverse=True)
    for node in heap_nodes:
        entry = clusters[node["cluster"]]
        entry.setdefault("heap_nodes", []).append(node)

    items = list(clusters.values())
    items.sort(key=lambda x: x.get("cluster") or "")
    return {
        "available": bool(status_rows or items),
        "clusters": items,
        "heap_nodes": heap_nodes,
    }


def _mw_instance(row):
    m = _metric(row)
    return (
        m.get("addr")
        or m.get("instance")
        or m.get("dimension_DBInstanceIdentifier")
        or m.get("dbinstance_identifier")
        or m.get("cluster_id")
        or m.get("service")
        or m.get("job")
        or ""
    )


def _metric_in(name_set, metric):
    if not metric:
        return False
    if not name_set:
        return True
    return metric in name_set


def _max_gauge(query_fn, metric):
    if not metric:
        return None, []
    rows = query_fn(metric) or []
    if not rows:
        return None, []
    return round(max(_num(r) for r in rows), 1), rows


def _fmt_bytes(n):
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "-"
    for unit, size in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if abs(n) >= size:
            val = n / size
            return f"{val:.1f}{unit}" if val < 10 else f"{val:.0f}{unit}"
    return f"{int(n)}B"


def _resource_specs(spec, name_set):
    specs = list(spec.get("resources") or [])
    if not specs:
        if spec.get("mem_pct_metric"):
            specs.append({
                "kind": "mem", "mode": "gauge_pct",
                "metric": spec["mem_pct_metric"], "label": "内存",
            })
        if spec.get("mem_used") and spec.get("mem_max"):
            specs.append({
                "kind": "mem", "mode": "ratio",
                "used": spec["mem_used"], "max": spec["mem_max"], "label": "内存",
            })
    picked = []
    for item in specs:
        mode = item.get("mode") or "ratio"
        if mode == "gauge_pct":
            if not _metric_in(name_set, item.get("metric")):
                continue
        elif mode == "used":
            if not _metric_in(name_set, item.get("used")):
                continue
        elif mode == "free":
            if not _metric_in(name_set, item.get("used")):
                continue
        else:
            if not (_metric_in(name_set, item.get("used")) and _metric_in(name_set, item.get("max"))):
                continue
        picked.append(item)
    return picked


def _infer_leftover_resources(up_metric, name_set):
    """未登记的 *_up：只认同前缀下非常明确的 used/max 字节对。"""
    if not up_metric or not up_metric.endswith("_up"):
        return []
    prefix = up_metric[:-3] + "_"
    pairs = [
        ("memory_used_bytes", "memory_max_bytes", "mem", "内存"),
        ("mem_used_bytes", "mem_limit_bytes", "mem", "内存"),
        ("current_bytes", "limit_bytes", "mem", "内存"),
        ("disk_used_bytes", "disk_total_bytes", "disk", "磁盘"),
        ("storage_used_bytes", "storage_total_bytes", "disk", "磁盘"),
    ]
    out = []
    seen = set()
    for used_s, max_s, kind, label in pairs:
        if kind in seen:
            continue
        used_m, max_m = prefix + used_s, prefix + max_s
        if used_m in name_set and max_m in name_set:
            out.append({"kind": kind, "mode": "ratio", "used": used_m, "max": max_m, "label": label})
            seen.add(kind)
    return out


def _ratio_stats(query_fn, used_m, max_m):
    used_rows = query_fn(used_m) or []
    cap_map = {}
    for row in query_fn(max_m) or []:
        cap_map[_mw_instance(row) or "x"] = _num(row)
    pcts, used_vals, max_vals, labels = [], [], [], []
    unlimited = False
    for row in used_rows:
        key = _mw_instance(row) or "x"
        used = _num(row)
        cap = cap_map.get(key)
        if cap is None and len(cap_map) == 1:
            cap = next(iter(cap_map.values()))
        cap = cap if cap is not None else 0
        used_vals.append(used)
        max_vals.append(cap)
        if key and key not in labels:
            labels.append(key)
        if cap > 0:
            pcts.append(used / cap * 100)
        elif used > 0:
            unlimited = True
    return {
        "pct": round(max(pcts), 1) if pcts else None,
        "used": max(used_vals) if used_vals else 0,
        "max": max(max_vals) if max_vals else 0,
        "unlimited": unlimited and not pcts,
        "instances": labels,
    }


def _evaluate_resources(query_fn, spec, name_set):
    """只读该 exporter 自己的 used/max 或水位。没有就不编百分比。"""
    bits = []
    metrics = []
    mem_pct = disk_pct = None
    mem_text = disk_text = ""
    warn = False
    mem_warn = float(spec.get("mem_warn") or 85)
    disk_warn = float(spec.get("disk_warn") or 85)
    seen_kind = set()
    for item in _resource_specs(spec, name_set):
        kind = item.get("kind") or "mem"
        if kind in seen_kind:
            continue
        mode = item.get("mode") or "ratio"
        label = item.get("label") or ("磁盘" if kind == "disk" else "内存")
        text = ""
        pct = None
        if mode == "gauge_pct":
            metric = item.get("metric")
            pct, rows = _max_gauge(query_fn, metric)
            metrics.append(metric)
            if pct is None:
                continue
            text = f"{label} {pct}%"
        elif mode == "used":
            metric = item.get("used")
            value, rows = _max_gauge(query_fn, metric)
            metrics.append(metric)
            if value is None:
                continue
            unit = (item.get("unit") or "bytes").lower()
            if unit in ("mb", "mib"):
                value = value * (1024 * 1024 if unit == "mib" else 1e6)
            text = f"{label} {_fmt_bytes(value)}"
        elif mode == "free":
            avail_m, limit_m = item.get("used"), item.get("max")
            avail, rows = _max_gauge(query_fn, avail_m)
            metrics.append(avail_m)
            if avail is None:
                continue
            text = f"{label} {_fmt_bytes(avail)}"
            if _metric_in(name_set, limit_m):
                limit, _ = _max_gauge(query_fn, limit_m)
                metrics.append(limit_m)
                if limit and limit > 0:
                    text += f"（水位 {_fmt_bytes(limit)}）"
                    if avail < limit:
                        warn = True
        else:
            used_m, max_m = item.get("used"), item.get("max")
            stats = _ratio_stats(query_fn, used_m, max_m)
            metrics.extend([used_m, max_m])
            if stats["pct"] is not None:
                pct = stats["pct"]
                text = f"{label} {pct}%"
            elif stats["unlimited"]:
                text = f"{label} {_fmt_bytes(stats['used'])}（无上限）"
            elif stats["used"]:
                text = f"{label} {_fmt_bytes(stats['used'])}"
            else:
                continue
        bits.append(text)
        seen_kind.add(kind)
        if kind == "disk":
            disk_pct = pct
            disk_text = text
            if pct is not None and pct >= disk_warn:
                warn = True
        else:
            mem_pct = pct
            mem_text = text
            if pct is not None and pct >= mem_warn:
                warn = True
    return {
        "bits": bits,
        "metrics": [m for m in metrics if m],
        "mem_pct": mem_pct,
        "disk_pct": disk_pct,
        "mem_text": mem_text,
        "disk_text": disk_text,
        "warn": warn,
    }


def _evaluate_family(query_fn, spec, name_set):
    up_metric = spec.get("up") or ""
    cpu_metric = spec.get("cpu") or ""
    lag_metric = spec.get("lag") or ""
    up_n = 0
    down_n = 0
    instances = []
    if up_metric and _metric_in(name_set, up_metric):
        for row in query_fn(up_metric) or []:
            label = _mw_instance(row) or up_metric
            if _num(row) == 0:
                down_n += 1
                instances.append(label)
            else:
                up_n += 1
                if label and label not in instances:
                    instances.append(label)
    bits = []
    if up_n or down_n:
        bits.append(f"up {up_n}/{up_n + down_n}")
    cpu_max, cpu_rows = (None, [])
    if cpu_metric and _metric_in(name_set, cpu_metric):
        cpu_max, cpu_rows = _max_gauge(query_fn, cpu_metric)
        if cpu_max is not None:
            bits.append(f"cpu {cpu_max}%")
            for row in cpu_rows[:8]:
                label = _mw_instance(row)
                if label and label not in instances:
                    instances.append(label)
    lag_max = None
    if lag_metric and _metric_in(name_set, lag_metric):
        lag_max, lag_rows = _max_gauge(query_fn, lag_metric)
        if lag_max is not None:
            bits.append(f"replica_lag {lag_max}s")
            for row in lag_rows[:6]:
                label = _mw_instance(row)
                if label and label not in instances:
                    instances.append(label)
    resources = _evaluate_resources(query_fn, spec, name_set)
    bits.extend(resources["bits"])
    if not bits:
        return None
    level = "ok"
    if down_n:
        level = "critical"
    elif cpu_max is not None and cpu_max >= float(spec.get("cpu_warn") or 80):
        level = "warning"
    elif lag_max is not None and lag_max >= float(spec.get("lag_warn") or 30):
        level = "warning"
    elif resources["warn"]:
        level = "warning"
    used_metrics = [up_metric, cpu_metric, lag_metric] + resources["metrics"]
    return {
        "id": spec["id"],
        "name": spec["name"],
        "source": spec.get("source") or "prometheus",
        "level": level,
        "result": "，".join(bits),
        "up": up_n,
        "down": down_n,
        "cpu_pct": cpu_max,
        "mem_pct": resources["mem_pct"],
        "disk_pct": resources["disk_pct"],
        "mem_text": resources["mem_text"],
        "disk_text": resources["disk_text"],
        "instances": instances[:12],
        "metrics": [x for x in used_metrics if x and _metric_in(name_set, x)],
    }


def collect_middleware(query_fn, metric_names=None):
    """先看 Prom 里有哪些指标名，再套食谱；没扫到的族不列出。"""
    names = [str(n) for n in (metric_names or []) if n]
    name_set = set(names)
    items = []
    seen = set()
    if name_set:
        for spec in METRIC_FAMILY_RECIPES:
            if spec["id"] in seen:
                continue
            if not any(recipe_covers_metric(spec, n) for n in names):
                continue
            row = _evaluate_family(query_fn, spec, name_set)
            if row:
                seen.add(spec["id"])
                items.append(row)
        covered = set()
        for spec in METRIC_FAMILY_RECIPES:
            for prefix in spec.get("prefixes") or []:
                covered.add(prefix.lower())
        for n in names:
            if not n.endswith("_up") or n in UP_METRIC_DENY:
                continue
            low = n.lower()
            if low.startswith("node_") or low.startswith("kube_") or low.startswith("elasticsearch_"):
                continue
            if any(low.startswith(p) for p in covered):
                continue
            spec = {
                "id": n,
                "name": n[:-3].replace("_", " ").strip().title() or n,
                "source": "prometheus",
                "up": n,
                "resources": _infer_leftover_resources(n, name_set),
            }
            row = _evaluate_family(query_fn, spec, name_set)
            if row:
                items.append(row)
    else:
        for spec in METRIC_FAMILY_RECIPES:
            row = _evaluate_family(query_fn, spec, set())
            if row:
                items.append(row)
    return {
        "available": bool(items),
        "items": items,
        "discovered_names": len(names),
    }


def _pod_key(metric):
    m = metric or {}
    ns = m.get("namespace") or ""
    pod = m.get("pod") or ""
    return f"{ns}/{pod}", ns, pod


def _pod_created_map(query_fn):
    out = {}
    for row in query_fn("kube_pod_created") or []:
        key, _, pod = _pod_key(_metric(row))
        if pod:
            out[key] = _num(row)
    return out


def _pod_too_old(key, created_map, now, lookback, missing="drop"):
    created = created_map.get(key) or 0
    if created <= 0:
        return missing == "drop"
    return (now - created) > lookback


def _job_key(row):
    m = _metric(row)
    return (m.get("namespace") or "", m.get("job_name") or m.get("job") or "")


def _job_start_map(rows):
    out = {}
    for row in rows or []:
        key = _job_key(row)
        if key[1]:
            out[key] = _num(row)
    return out


def _job_owner_kind_map(rows):
    out = {}
    for row in rows or []:
        key = _job_key(row)
        if key[1]:
            out[key] = (_metric(row).get("owner_kind") or "").strip()
    return out


def _fmt_when(ts):
    if not ts:
        return ""
    try:
        val = float(ts)
        if val > 1e12:
            val = val / 1000.0
        if val > 0:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(val))
    except (TypeError, ValueError):
        pass
    text = str(ts).strip()
    if not text:
        return ""
    text = text.replace("Z", "+00:00")
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]


def _host_from_instance(instance):
    inst = (instance or "").strip()
    if "://" in inst:
        inst = inst.split("://", 1)[-1]
    host = inst.split("/")[0]
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
    else:
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host.strip()


def _is_ipv4(host):
    parts = (host or "").split(".")
    if len(parts) != 4:
        return False
    try:
        return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
    except Exception:
        return False


def _looks_k8s_name(name):
    n = (name or "").lower()
    if ".ec2.internal" in n or ".compute.internal" in n:
        return True
    return "k8s" in n


def _role_from_k8s_name(name, cloud=""):
    n = (name or "").lower()
    if cloud == "aws" or ".ec2.internal" in n or ".compute.internal" in n:
        return "EKS 节点"
    if "control-plane" in n or "-master-" in n or n.endswith("-master") or n.startswith("master-"):
        return "K8s 控制面"
    if "-worker-" in n or n.endswith("-worker") or n.startswith("worker-"):
        return "K8s worker"
    return "K8s 节点"


def _cluster_hosts(query_fn):
    hosts = set()
    for row in query_fn("kube_node_status_addresses") or []:
        m = _metric(row)
        addr = m.get("address") or ""
        if addr:
            hosts.add(addr)
        node = m.get("node") or ""
        if node:
            hosts.add(node)
    for row in query_fn("kube_node_info") or []:
        m = _metric(row)
        if m.get("node"):
            hosts.add(m["node"])
        if m.get("internal_ip"):
            hosts.add(m["internal_ip"])
    return {h for h in hosts if h}


def _parse_provider_id(pid):
    text = (pid or "").strip()
    low = text.lower()
    cloud, zone, instance_id = "", "", ""
    if low.startswith("aws://"):
        cloud = "aws"
        rest = text.split("://", 1)[-1].strip("/")
        parts = [p for p in rest.split("/") if p]
        if len(parts) >= 2:
            zone, instance_id = parts[0], parts[-1]
        elif parts:
            instance_id = parts[-1]
    elif low.startswith("gce://"):
        cloud = "gcp"
    elif low.startswith("azure://"):
        cloud = "azure"
    return cloud, zone, instance_id


def _metric_label(m, *needles):
    m = m or {}
    for key, val in m.items():
        if not val:
            continue
        lk = (key or "").lower().replace("-", "_")
        for n in needles:
            if n in lk:
                return str(val)
    return ""


def enrich_servers(query_fn, servers):
    """机器名走 node_uname_info / kube 节点名；IP 单独成列。EKS 用 provider_id 和 nodegroup，不调 AWS API。"""
    nodes = {}

    def _node(name):
        name = (name or "").strip()
        if not name:
            return None
        if name not in nodes:
            nodes[name] = {
                "node_name": name,
                "ip": "",
                "hostname": "",
                "provider_id": "",
                "cloud": "",
                "zone": "",
                "instance_id": "",
                "nodegroup": "",
                "instance_type": "",
                "compute_type": "",
            }
        return nodes[name]

    for row in query_fn("kube_node_status_addresses") or []:
        m = _metric(row)
        info = _node(m.get("node"))
        if not info:
            continue
        kind = (m.get("address_type") or "").strip()
        addr = (m.get("address") or "").strip()
        if not addr:
            continue
        if kind == "InternalIP" or (not info["ip"] and _is_ipv4(addr)):
            info["ip"] = addr
        elif kind == "Hostname":
            info["hostname"] = addr

    for row in query_fn("kube_node_info") or []:
        m = _metric(row)
        info = _node(m.get("node"))
        if not info:
            continue
        pid = (m.get("provider_id") or "").strip()
        info["provider_id"] = pid
        cloud, zone, iid = _parse_provider_id(pid)
        if cloud:
            info["cloud"] = cloud
        if zone:
            info["zone"] = zone
        if iid:
            info["instance_id"] = iid

    for row in query_fn("kube_node_labels") or []:
        m = _metric(row)
        info = _node(m.get("node"))
        if not info:
            continue
        ng = _metric_label(m, "nodegroup", "nodepool")
        itype = _metric_label(m, "instance_type")
        zone = _metric_label(m, "topology_kubernetes_io_zone", "failure_domain")
        compute = _metric_label(m, "compute_type")
        if ng:
            info["nodegroup"] = ng
        if itype:
            info["instance_type"] = itype
        if zone and not info["zone"]:
            info["zone"] = zone
        if compute:
            info["compute_type"] = compute
        for key in m:
            if "eks_amazonaws" in (key or "").lower().replace("-", "_"):
                info["cloud"] = "aws"
                break

    for info in nodes.values():
        name = (info.get("node_name") or info.get("hostname") or "").lower()
        if not info.get("cloud") and (
            ".ec2.internal" in name or ".compute.internal" in name
        ):
            info["cloud"] = "aws"

    by_ip, by_host = {}, {}
    for info in nodes.values():
        if info.get("ip"):
            by_ip[info["ip"]] = info
        if info.get("node_name"):
            by_host[info["node_name"]] = info
        if info.get("hostname"):
            by_host[info["hostname"]] = info

    uname_by_instance, uname_by_host = {}, {}
    for row in query_fn("node_uname_info") or []:
        m = _metric(row)
        inst = (m.get("instance") or "").strip()
        nodename = (m.get("nodename") or "").strip()
        if not nodename:
            continue
        if inst:
            uname_by_instance[inst] = nodename
            uname_by_host[_host_from_instance(inst)] = nodename
        uname_by_host[nodename] = nodename

    for s in servers or []:
        inst = s.get("instance") or ""
        host = _host_from_instance(inst)
        nodename = uname_by_instance.get(inst) or uname_by_host.get(host) or ""
        info = (
            by_ip.get(host)
            or by_host.get(host)
            or by_host.get(nodename)
            or by_host.get(inst)
            or {}
        )
        alias = (
            resolve_service(name=nodename, instance=inst)
            or resolve_service(name=nodename, instance=nodename)
            or resolve_service(instance=inst)
        )
        ip = info.get("ip") or (host if _is_ipv4(host) else "")
        display = info.get("node_name") or info.get("hostname") or nodename
        if not display and host and not _is_ipv4(host):
            display = host
        kind = "k8s" if info else "host"
        cloud = info.get("cloud") or ""
        if not cloud and _looks_k8s_name(display) and (
            ".ec2.internal" in display.lower() or ".compute.internal" in display.lower()
        ):
            cloud = "aws"
        if kind != "k8s" and _looks_k8s_name(display):
            kind = "k8s"
        s["ip"] = ip
        s["hostname"] = nodename or info.get("hostname") or ""
        s["node_name"] = display
        s["kind"] = kind
        s["cloud"] = cloud
        s["zone"] = info.get("zone") or ""
        s["instance_id"] = info.get("instance_id") or ""
        s["nodegroup"] = info.get("nodegroup") or ""
        s["instance_type"] = info.get("instance_type") or ""
        s["compute_type"] = info.get("compute_type") or ""
        if alias:
            s["role"] = alias["service"]
            s["service"] = alias["service"]
        elif info.get("nodegroup"):
            s["role"] = info["nodegroup"]
            s["service"] = display or host
        elif (info.get("compute_type") or "").lower() == "fargate":
            s["role"] = "EKS Fargate"
            s["service"] = display or host
        elif kind == "k8s":
            s["role"] = _role_from_k8s_name(display, cloud)
            s["service"] = display or host
        else:
            s["role"] = "独立主机"
            s["service"] = s.get("service") or ""
            if not s["service"] or s["service"] == inst or s["service"] == host or _is_ipv4(s["service"]):
                s["service"] = display or ""
    return servers


def label_servers(query_fn, servers):
    """机器表：有别名用别名；否则用 kube 节点名。不要把 IP 再填进服务列。"""
    return enrich_servers(query_fn, servers)


CPU_WARN_PCT = 85
CPU_CRIT_PCT = 95
MEM_WARN_PCT = 85
MEM_CRIT_PCT = 95
NODE_DISK_WARN_PCT = 90
NODE_DISK_CRIT_PCT = 95


def mark_server_pressure(servers):
    """给每台机器打水位。检查清单只收偏高的，全量表另看。"""
    for s in servers or []:
        cpu = float(s.get("cpu_pct") or 0)
        mem = float(s.get("mem_pct") or 0)
        disk = float(s.get("disk_pct") or 0)
        alias = (
            resolve_service(name=s.get("node_name") or s.get("hostname") or "", instance=s.get("instance") or "")
            or resolve_service(instance=s.get("node_name") or s.get("hostname") or "")
        )
        mem_warn = float((alias or {}).get("mem_alert_threshold") or MEM_WARN_PCT)
        mem_crit = max(mem_warn, MEM_CRIT_PCT)
        bits = []
        level = "ok"
        if cpu >= CPU_CRIT_PCT:
            bits.append(f"CPU {cpu:.0f}%")
            level = "critical"
        elif cpu >= CPU_WARN_PCT:
            bits.append(f"CPU {cpu:.0f}%")
            level = "warning"
        if mem >= mem_crit:
            bits.append(f"内存 {mem:.0f}%")
            level = "critical"
        elif mem >= mem_warn:
            bits.append(f"内存 {mem:.0f}%")
            if level != "critical":
                level = "warning"
        if disk >= NODE_DISK_CRIT_PCT:
            bits.append(f"磁盘 {disk:.0f}%")
            level = "critical"
        elif disk >= NODE_DISK_WARN_PCT:
            bits.append(f"磁盘 {disk:.0f}%")
            if level != "critical":
                level = "warning"
        s["level"] = level
        s["pressure"] = bits
    return servers


def _is_stale_hostdown_name(name):
    n = (name or "").lower().replace("_", "").replace("-", "")
    return n in STALE_HOSTDOWN_NAMES or n.endswith("hostdown")


def _ipv4_slash24(host):
    parts = (host or "").split(".")
    if len(parts) != 4:
        return ""
    try:
        if all(0 <= int(p) <= 255 for p in parts):
            return ".".join(parts[:3])
    except ValueError:
        return ""
    return ""


def _host_on_node_subnet(host, hosts):
    prefix = _ipv4_slash24(host)
    if not prefix:
        return False
    return any(_ipv4_slash24(h) == prefix for h in (hosts or []))


def _is_node_exporter_job(job, empty_is_node=True):
    j = (job or "").lower().replace("_", "-")
    if not j:
        return empty_is_node
    if j in ("node", "nodes", "node-exporter"):
        return True
    if "node-exporter" in j:
        return True
    if j in ("kubernetes-nodes", "kube-nodes") or "kubernetes-nodes" in j:
        return True
    return False


def _is_known_non_cluster_instance(instance):
    """JumpServer 等有别名的机器不是 kube 节点，宕机仍算真故障。"""
    return bool(resolve_service(instance=instance or ""))


def _is_stale_host_alert(alert, hosts):
    if not hosts or not _is_stale_hostdown_name(alert.get("name")):
        return False
    inst = alert.get("instance") or ""
    if _is_known_non_cluster_instance(inst):
        return False
    if not _is_node_exporter_job(alert.get("job")):
        return False
    host = _host_from_instance(inst)
    return bool(host) and host not in hosts


def _is_stale_node_target(target, hosts, previous_keys=None):
    """关机机器上的 node / 同网段 exporter，进残留不进故障。"""
    inst = target.get("instance") or ""
    job = target.get("job") or ""
    previous_keys = previous_keys or set()
    if _is_known_non_cluster_instance(inst):
        return False
    host = _host_from_instance(inst)
    alt = f"{job}|{inst}"
    seen_before = alt in previous_keys or f"target:{job}:{inst}" in previous_keys
    if host and hosts and host in hosts:
        return False
    if seen_before:
        return True
    if not hosts:
        return False
    if not host:
        return _is_node_exporter_job(job, empty_is_node=False)
    if _is_node_exporter_job(job, empty_is_node=False) or _host_on_node_subnet(host, hosts):
        return True
    return False


def _decommissioned_item(kind, name, instance, job="", last_scrape="", last_error=""):
    when = _fmt_when(last_scrape)
    label = " ".join(x for x in (name or job, instance) if x)
    if when:
        label = f"{label}  {when}"
    return {
        "kind": kind,
        "name": name or "",
        "job": job or "",
        "instance": instance or "",
        "last_scrape": last_scrape or "",
        "last_error": last_error or "",
        "when": when,
        "label": label,
        "persistent": False,
        "key": f"target:{job or ''}:{instance or ''}" if kind == "target" else f"alert:{name or ''}|{instance or ''}",
    }


def _split_decommissioned(firing_alerts, down_targets, hosts, previous_keys=None, ignore_keys=None, previous_times=None):
    """能扫到、但不在当前 kube 节点上：单独列出，不进发现问题。"""
    previous_keys = set(previous_keys or [])
    ignore_keys = set(ignore_keys or [])
    previous_times = previous_times or {}
    kept_firing, kept_down, leftover = [], [], []
    for alert in firing_alerts or []:
        name = alert.get("name") or ""
        inst = alert.get("instance") or ""
        if f"alert:{name}|{inst}" in ignore_keys:
            continue
        if _is_stale_host_alert(alert, hosts):
            leftover.append(_decommissioned_item(
                "alert", name or "HostDown", inst,
                job=alert.get("job") or "",
            ))
        else:
            kept_firing.append(alert)
    for target in down_targets or []:
        job = target.get("job") or ""
        inst = target.get("instance") or ""
        if f"target:{job}:{inst}" in ignore_keys:
            continue
        if _is_stale_node_target(target, hosts, previous_keys=previous_keys):
            alt = f"{job}|{inst}"
            leftover.append(_decommissioned_item(
                "target",
                job or "node-exporter",
                inst,
                job=job,
                last_scrape=previous_times.get(alt) or target.get("last_scrape") or "",
                last_error=target.get("last_error") or "",
            ))
        else:
            kept_down.append(target)
    return kept_firing, kept_down, leftover


def _index_named(rows, *name_keys):
    out = {}
    for row in rows or []:
        m = _metric(row)
        ns = m.get("namespace") or ""
        name = ""
        for key in name_keys:
            if m.get(key):
                name = m.get(key)
                break
        if not name:
            continue
        out[(ns, name)] = int(_num(row))
    return out


def _strip_replicaset_hash(name):
    parts = (name or "").rsplit("-", 1)
    if len(parts) == 2 and 5 <= len(parts[1]) <= 16 and parts[1].isalnum():
        return parts[0]
    return name


def _clean_owner(kind, name):
    kind = (kind or "").strip()
    name = (name or "").strip()
    if kind.lower() in ("", "<none>", "none"):
        return "", ""
    return kind, name


def _workload_level(ready, desired, pods):
    if any(p.get("level") == "critical" for p in pods):
        return "critical"
    if desired is not None and ready is not None and desired > 0 and ready < desired:
        return "warning"
    if any(p.get("level") == "warning" for p in pods):
        return "warning"
    if desired is not None and desired > 0 and (ready or 0) == 0:
        return "critical"
    return "ok"


def collect_workloads(query_fn):
    """一眼：Deploy/STS Ready n/m；展开：Pod 名 + Pod IP + 节点 IP。不扫 kube-system。"""
    phase_rows = query_fn("kube_pod_status_phase == 1") or query_fn("kube_pod_status_phase") or []
    waiting_rows = query_fn(
        'kube_pod_container_status_waiting_reason{reason=~"CrashLoopBackOff|ImagePullBackOff|ErrImagePull|CreateContainerError"} == 1'
    ) or []
    ready_rows = query_fn('kube_pod_status_ready{condition="true"} == 1') or []
    info_rows = query_fn("kube_pod_info") or []
    owner_rows = query_fn("kube_pod_owner") or []
    rs_owner_rows = query_fn('kube_replicaset_owner{owner_kind="Deployment"}') or query_fn("kube_replicaset_owner") or []
    restart_rows = query_fn("kube_pod_container_status_restarts_total") or []

    waiting = {}
    for row in waiting_rows:
        if _num(row) != 1:
            continue
        key, _, _ = _pod_key(_metric(row))
        waiting[key] = _metric(row).get("reason") or "waiting"

    ready_set = set()
    for row in ready_rows:
        if _num(row) != 1:
            continue
        key, _, _ = _pod_key(_metric(row))
        if not key.endswith("/"):
            ready_set.add(key)

    info = {}
    for row in info_rows:
        m = _metric(row)
        key, _, _ = _pod_key(m)
        info[key] = {
            "pod_ip": m.get("pod_ip") or m.get("pod_ips") or "",
            "host_ip": m.get("host_ip") or "",
            "node": m.get("node") or m.get("node_name") or "",
            "created_by_kind": m.get("created_by_kind") or "",
            "created_by_name": m.get("created_by_name") or "",
        }

    owners = {}
    for row in owner_rows:
        m = _metric(row)
        key, _, _ = _pod_key(m)
        owners[key] = {
            "owner_kind": m.get("owner_kind") or m.get("created_by_kind") or "",
            "owner_name": m.get("owner_name") or m.get("created_by_name") or "",
        }

    rs_to_deploy = {}
    for row in rs_owner_rows:
        m = _metric(row)
        if (m.get("owner_kind") or "") != "Deployment" and "owner_kind" in m:
            continue
        ns = m.get("namespace") or ""
        rs = m.get("replicaset") or m.get("replicasetname") or ""
        deploy = m.get("owner_name") or ""
        if ns and rs and deploy:
            rs_to_deploy[(ns, rs)] = deploy

    restarts = {}
    for row in restart_rows:
        key, _, _ = _pod_key(_metric(row))
        restarts[key] = restarts.get(key, 0) + int(_num(row))

    items = []
    seen = set()
    for row in phase_rows:
        if _num(row) != 1:
            continue
        m = _metric(row)
        key, ns, pod = _pod_key(m)
        if not pod or key in seen:
            continue
        seen.add(key)
        phase = (m.get("phase") or "unknown").lower()
        alias = resolve_service(namespace=ns, name=pod, instance=pod)
        wait_reason = waiting.get(key) or ""
        abnormal = phase not in ("running", "succeeded") or bool(wait_reason)
        if phase == "succeeded" and not alias:
            continue
        if hidden_namespace(ns) and not abnormal:
            continue
        if phase in ("failed", "unknown") or wait_reason:
            level = "critical"
        elif phase == "pending":
            level = "warning"
        elif phase != "running":
            level = "info"
        else:
            level = "ok"
        meta = info.get(key) or {}
        own = owners.get(key) or {}
        owner_kind, owner_name = _clean_owner(own.get("owner_kind"), own.get("owner_name"))
        if not owner_kind:
            owner_kind, owner_name = _clean_owner(meta.get("created_by_kind"), meta.get("created_by_name"))
        items.append({
            "key": key,
            "namespace": ns,
            "pod": pod,
            "phase": phase,
            "ready": key in ready_set if ready_set else None,
            "waiting": wait_reason,
            "service": alias["service"] if alias else (f"{ns}/{pod}" if ns else pod),
            "aliased": bool(alias),
            "level": level,
            "pod_ip": meta.get("pod_ip") or "",
            "host_ip": meta.get("host_ip") or "",
            "node": meta.get("node") or "",
            "restarts": restarts.get(key, 0),
            "owner_kind": owner_kind,
            "owner_name": owner_name,
        })

    deploy_spec = _index_named(query_fn("kube_deployment_spec_replicas") or [], "deployment")
    deploy_ready = _index_named(query_fn("kube_deployment_status_replicas_ready") or [], "deployment")
    sts_spec = _index_named(query_fn("kube_statefulset_replicas") or [], "statefulset")
    sts_ready = _index_named(query_fn("kube_statefulset_status_replicas_ready") or [], "statefulset")
    ds_spec = _index_named(query_fn("kube_daemonset_status_desired_number_scheduled") or [], "daemonset")
    ds_ready = _index_named(query_fn("kube_daemonset_status_number_ready") or [], "daemonset")

    groups_map = {}

    def ensure_group(kind, ns, name, service=""):
        key = f"{kind}/{ns}/{name}"
        if key not in groups_map:
            alias = resolve_service(namespace=ns, name=name, instance=name)
            groups_map[key] = {
                "key": key,
                "kind": kind,
                "namespace": ns,
                "name": name,
                "service": (alias["service"] if alias else None) or service or f"{ns}/{name}",
                "desired": None,
                "ready": None,
                "pods": [],
            }
        elif service and groups_map[key]["service"].endswith(name):
            groups_map[key]["service"] = service
        return groups_map[key]

    def keep_ctrl(ns, name):
        return not hidden_namespace(ns)

    def find_controller(ns, pod_name):
        best = None
        best_len = -1
        for g in groups_map.values():
            if g.get("namespace") != ns:
                continue
            if g.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet"):
                continue
            name = g.get("name") or ""
            if not name:
                continue
            if pod_name == name or pod_name.startswith(name + "-"):
                if len(name) > best_len:
                    best = g
                    best_len = len(name)
        return best

    for (ns, name), desired in deploy_spec.items():
        if keep_ctrl(ns, name):
            g = ensure_group("Deployment", ns, name)
            g["desired"] = desired
            g["ready"] = deploy_ready.get((ns, name), 0)
    for (ns, name), desired in sts_spec.items():
        if keep_ctrl(ns, name):
            g = ensure_group("StatefulSet", ns, name)
            g["desired"] = desired
            g["ready"] = sts_ready.get((ns, name), 0)
    for (ns, name), desired in ds_spec.items():
        if keep_ctrl(ns, name):
            g = ensure_group("DaemonSet", ns, name)
            g["desired"] = desired
            g["ready"] = ds_ready.get((ns, name), 0)

    for pod in items:
        ns = pod["namespace"]
        kind = pod.get("owner_kind") or ""
        oname = pod.get("owner_name") or ""
        if kind == "ReplicaSet":
            deploy = rs_to_deploy.get((ns, oname)) or _strip_replicaset_hash(oname)
            g = ensure_group("Deployment", ns, deploy, pod.get("service"))
        elif kind in ("StatefulSet", "DaemonSet", "Job", "Deployment"):
            g = ensure_group(kind, ns, oname, pod.get("service"))
        else:
            g = find_controller(ns, pod["pod"]) or ensure_group("Pod", ns, pod["pod"], pod.get("service"))
        g["pods"].append(pod)
        if pod.get("aliased") and not resolve_service(namespace=g["namespace"], name=g["name"]):
            g["service"] = pod["service"]

    groups = []
    for g in groups_map.values():
        if hidden_namespace(g.get("namespace")) and not any(p.get("level") != "ok" for p in g["pods"]):
            continue
        pods = g["pods"]
        if not pods and not (g.get("namespace") or ""):
            continue
        if not pods and (g.get("desired") or 0) == 0:
            continue
        running = sum(1 for p in pods if p.get("phase") == "running" and not p.get("waiting"))
        if g["desired"] is None:
            g["desired"] = len(pods) if pods else 0
        if g["ready"] is None:
            g["ready"] = running
        g["level"] = _workload_level(g["ready"], g["desired"], pods)
        g["summary"] = f"{g['ready']}/{g['desired']}"
        pods.sort(key=lambda p: ({"critical": 0, "warning": 1, "info": 2, "ok": 3}.get(p.get("level"), 9), p.get("pod") or ""))
        groups.append(g)

    groups.sort(key=lambda g: (
        {"critical": 0, "warning": 1, "info": 2, "ok": 3}.get(g["level"], 9),
        g.get("service") or "",
        g.get("name") or "",
    ))
    items.sort(key=lambda x: (
        {"critical": 0, "warning": 1, "info": 2, "ok": 3}.get(x["level"], 9),
        x.get("service") or "",
        x.get("pod") or "",
    ))
    return {
        "available": bool(phase_rows or deploy_spec or sts_spec),
        "items": items,
        "groups": groups,
        "query": "kube_pod_status_phase / kube_deployment_status_replicas_ready",
    }


def collect_cluster_checks(
    query_fn, firing_alerts=None, down_targets=None, servers=None, metric_names=None,
    previous_leftover_keys=None, ignore_keys=None, previous_times=None,
):
    firing_alerts = firing_alerts or []
    down_targets = down_targets or []
    servers = servers or []
    metric_names = list(metric_names) if metric_names is not None else None
    name_set = set(metric_names or [])
    ignore_keys = {str(k) for k in (ignore_keys or []) if k}
    previous_times = previous_times or {}
    cluster_hosts = _cluster_hosts(query_fn)
    for s in servers:
        host = _host_from_instance(s.get("instance") or "")
        if host:
            cluster_hosts.add(host)
    firing_alerts, down_targets, decommissioned = _split_decommissioned(
        firing_alerts, down_targets, cluster_hosts,
        previous_keys=previous_leftover_keys,
        ignore_keys=ignore_keys,
        previous_times=previous_times,
    )
    if "check:prom_targets" in ignore_keys:
        down_targets = []
    if "check:prom_alerts" in ignore_keys:
        firing_alerts = []

    pvc = collect_pvc_usage(query_fn)
    es = collect_elasticsearch(query_fn)
    middleware = collect_middleware(query_fn, metric_names=metric_names)
    workloads = collect_workloads(query_fn)
    checks = []
    findings = []

    def presence(query):
        rows = query_fn(f"count({query})") or []
        if not rows:
            # some Prometheuses reject count() wrapping; try raw
            return bool(query_fn(query))
        return _num(rows[0]) > 0

    def discovered(metric):
        if not name_set:
            return presence(metric)
        return metric in name_set

    # --- kube-state-metrics style checks ---
    node_ready_q = 'kube_node_status_condition{condition="Ready",status="true"}'
    not_ready_rows = query_fn(f'{node_ready_q} == 0') or []
    if presence("kube_node_status_condition"):
        n_not = len(not_ready_rows)
        total_nodes = len(query_fn(node_ready_q) or [])
        level = "ok" if n_not == 0 else "critical"
        checks.append(_check(
            "nodes", "节点 Ready", level,
            f"{n_not} NotReady / {total_nodes} 总",
            _series_names(not_ready_rows),
            "kube-state-metrics",
        ))
        if n_not:
            findings.append(f"NotReady 节点 {n_not} 个")
    else:
        checks.append(_check("nodes", "节点 Ready", "skip", "无 kube-state-metrics 节点指标", source="kube-state-metrics"))

    rofs_rows = query_fn('kube_node_status_condition{condition="ReadonlyFilesystem",status="true"} == 1') or []
    if presence("kube_node_status_condition"):
        n = len(rofs_rows)
        level = "ok" if n == 0 else "critical"
        checks.append(_check("rofs", "ReadonlyFilesystem", level, f"{n} True", _series_names(rofs_rows), "kube-state-metrics"))
        if n:
            findings.append(f"ReadonlyFilesystem=True {n} 个")
    else:
        checks.append(_check("rofs", "ReadonlyFilesystem", "skip", "无 kube-state-metrics 节点指标", source="kube-state-metrics"))

    if presence("kube_node_status_condition"):
        press_rows = query_fn(
            'kube_node_status_condition{condition=~"MemoryPressure|DiskPressure|PIDPressure",status="true"} == 1'
        ) or []
        n = len(press_rows)
        checks.append(_check(
            "node_pressure", "节点 Pressure",
            "ok" if n == 0 else "critical",
            f"{n} True",
            _series_names(press_rows),
            "kube-state-metrics",
        ))
        if n:
            findings.append(f"节点 Memory/Disk/PID Pressure {n} 个")
    else:
        checks.append(_check("node_pressure", "节点 Pressure", "skip", "无 kube-state-metrics 节点指标", source="kube-state-metrics"))

    abn_q = 'kube_pod_status_phase{phase=~"Pending|Failed|Unknown"}'
    abn_rows = _active_series(query_fn(f"{abn_q} == 1") or query_fn(abn_q) or [])
    if presence("kube_pod_status_phase"):
        created_map = _pod_created_map(query_fn)
        now = time.time()
        current = []
        ignored_failed = 0
        for row in abn_rows:
            m = _metric(row)
            phase = (m.get("phase") or "").lower()
            key, _, _ = _pod_key(m)
            if phase == "failed" and _pod_too_old(
                key, created_map, now, POD_FAIL_LOOKBACK_SEC, missing="drop",
            ):
                ignored_failed += 1
                continue
            current.append(row)
        pod_items = []
        for row in current:
            m = _metric(row)
            key, _, _ = _pod_key(m)
            label = (_series_names([row], limit=1) or ["pod"])[0]
            when = _fmt_when(created_map.get(key) or 0)
            pod_items.append({
                "key": f"pod:{key}",
                "label": f"{label}  {when}".strip() if when else label,
                "when": when,
            })
        n = len(current)
        result = str(n)
        if ignored_failed:
            result = f"{n}（忽略 Failed 历史 {ignored_failed} 个）"
        level = "ok" if n == 0 else "warning"
        checks.append(_check(
            "pods", "异常 Pod", level, result,
            source="kube-state-metrics", items=pod_items,
        ))
        if n:
            findings.append(f"异常 Pod {n} 个")
    else:
        checks.append(_check("pods", "异常 Pod", "skip", "无 Pod 相位指标", source="kube-state-metrics"))

    oom_rows = query_fn('kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1') or []
    restart_rows = query_fn("kube_pod_container_status_restarts_total > 10") or []
    if presence("kube_pod_container_status_restarts_total") or presence(
        'kube_pod_container_status_last_terminated_reason'
    ):
        created_map = _pod_created_map(query_fn)
        now = time.time()
        current_oom = []
        ignored_oom = 0
        for row in oom_rows:
            key, _, _ = _pod_key(_metric(row))
            if created_map and _pod_too_old(
                key, created_map, now, POD_FAIL_LOOKBACK_SEC, missing="keep",
            ):
                ignored_oom += 1
                continue
            current_oom.append(row)
        n_oom = len(current_oom)
        n_re = len(restart_rows)
        if n_oom:
            level = "warning"
        elif n_re:
            level = "info"
        else:
            level = "ok"
        result = f"{n_oom} / {n_re}"
        if ignored_oom:
            result += f"（忽略历史 OOM {ignored_oom} 个）"
        if n_oom == 0 and n_re:
            result += "（累计重启，未当当天故障）"
        oom_items = []
        for row in current_oom:
            key, _, _ = _pod_key(_metric(row))
            label = (_series_names([row], limit=1) or ["pod"])[0]
            when = _fmt_when(created_map.get(key) or 0)
            oom_items.append({
                "key": f"oom:{key}",
                "label": f"{label}  {when}".strip() if when else label,
                "when": when,
            })
        for row in restart_rows:
            key, _, _ = _pod_key(_metric(row))
            label = (_series_names([row], limit=1) or ["pod"])[0]
            when = _fmt_when(created_map.get(key) or 0)
            oom_items.append({
                "key": f"restart:{key}",
                "label": f"{label}  {when}".strip() if when else label,
                "when": when,
            })
        checks.append(_check(
            "stability", "OOM / 重启>10",
            level, result,
            source="kube-state-metrics", items=oom_items,
        ))
        if n_oom:
            findings.append(f"OOMKilled {n_oom} 个")
    else:
        checks.append(_check("stability", "OOM / 重启>10", "skip", "无容器终止/重启指标", source="kube-state-metrics"))

    pvc_phase_rows = query_fn('kube_persistentvolumeclaim_status_phase{phase!="Bound"} == 1') or []
    if presence("kube_persistentvolumeclaim_status_phase"):
        n = len(pvc_phase_rows)
        level = "ok" if n == 0 else "warning"
        checks.append(_check("pvc_bound", "PVC 未绑定", level, str(n), _series_names(pvc_phase_rows), "kube-state-metrics"))
        if n:
            findings.append(f"未 Bound PVC {n} 个")
    else:
        checks.append(_check("pvc_bound", "PVC 未绑定", "skip", "无 PVC 相位指标", source="kube-state-metrics"))

    zero_rows = query_fn("kube_deployment_spec_replicas == 0") or []
    if presence("kube_deployment_spec_replicas"):
        n = len(zero_rows)
        level = "ok" if n == 0 else "info"
        checks.append(_check(
            "replicas", "零副本 Deployment", level, str(n),
            _series_names(zero_rows), "kube-state-metrics",
        ))
    else:
        checks.append(_check("replicas", "零副本 Deployment", "skip", "无 Deployment 副本指标", source="kube-state-metrics"))

    if discovered("kube_job_status_failed"):
        job_rows = [r for r in (query_fn("kube_job_status_failed") or []) if _num(r) > 0]
        start_map = _job_start_map(query_fn("kube_job_status_start_time") or [])
        owner_map = _job_owner_kind_map(query_fn("kube_job_owner") or [])
        now = time.time()
        current = []
        ignored_cron = 0
        job_items = []
        for row in job_rows:
            ns, name = _job_key(row)
            label = f"{ns}/{name}" if ns else name
            started = start_map.get((ns, name)) or 0
            owner = (owner_map.get((ns, name)) or "").lower()
            when = _fmt_when(started)
            if owner == "cronjob" and started > 0 and (now - started) > JOB_FAIL_LOOKBACK_SEC:
                ignored_cron += 1
                continue
            current.append(row)
            text = f"{label}" + (f" {when}" if when else "") + (f" ({owner})" if owner else "")
            job_items.append({"key": f"job:{label}", "label": text, "when": when})
        n = len(current)
        result = str(n)
        if ignored_cron:
            result = f"{n}（忽略 CronJob 历史 {ignored_cron} 个）"
        checks.append(_check(
            "jobs", "Job 失败",
            "ok" if n == 0 else "warning",
            result, source="kube-state-metrics", items=job_items[:20],
        ))
        if n:
            findings.append(f"失败 Job {n} 个")
    else:
        checks.append(_check("jobs", "Job 失败", "skip", "无 kube_job_status_failed", source="kube-state-metrics"))

    if discovered("kube_horizontalpodautoscaler_spec_max_replicas"):
        max_idx = _index_named(
            query_fn("kube_horizontalpodautoscaler_spec_max_replicas") or [],
            "horizontalpodautoscaler", "hpa",
        )
        des_idx = _index_named(
            query_fn("kube_horizontalpodautoscaler_status_desired_replicas") or [],
            "horizontalpodautoscaler", "hpa",
        )
        hot = []
        for key, mx in max_idx.items():
            des = des_idx.get(key, 0)
            if mx and des >= mx:
                ns, name = key
                hot.append(f"{ns}/{name} {des}/{mx}")
        checks.append(_check(
            "hpa", "HPA 打满",
            "ok" if not hot else "warning",
            f"{len(hot)} / {len(max_idx)}",
            hot[:20],
            "kube-state-metrics",
        ))
        if hot:
            findings.append(f"HPA 已到 max {len(hot)} 个")
    else:
        checks.append(_check("hpa", "HPA 打满", "skip", "无 kube_horizontalpodautoscaler_*", source="kube-state-metrics"))

    cert_m = "certmanager_certificate_expiration_timestamp_seconds"
    if discovered(cert_m):
        now = time.time()
        expired = []
        soon = []
        for row in query_fn(cert_m) or []:
            ts = _num(row)
            if ts <= 0:
                continue
            left = ts - now
            m = _metric(row)
            label = "/".join(x for x in (m.get("namespace"), m.get("name")) if x) or m.get("exported_namespace") or "cert"
            if left <= 0:
                expired.append(str(label))
            elif left < 14 * 86400:
                soon.append(str(label))
        if expired:
            level = "critical"
            result = f"过期 {len(expired)}，14 天内 {len(soon)}"
        elif soon:
            level = "warning"
            result = f"14 天内到期 {len(soon)}"
        else:
            level = "ok"
            result = "未见 14 天内到期"
        checks.append(_check("certs", "证书到期", level, result, (expired + soon)[:20], "cert-manager"))
        if expired:
            findings.append(f"证书已过期 {len(expired)} 张")
        if soon:
            findings.append(f"证书 14 天内到期 {len(soon)} 张")
    else:
        checks.append(_check("certs", "证书到期", "skip", "未发现 certmanager_certificate_expiration_timestamp_seconds", source="cert-manager"))

    argocd_rows = query_fn('argocd_app_info{sync_status!="Synced"}') or []
    if presence("argocd_app_info"):
        n = len(argocd_rows)
        level = "ok" if n == 0 else "warning"
        checks.append(_check("argocd", "ArgoCD 未同步", level, str(n), _series_names(argocd_rows), "argocd"))
        if n:
            findings.append(f"未 Synced Application {n} 个")
    else:
        checks.append(_check("argocd", "ArgoCD 未同步", "skip", "无 ArgoCD 指标", source="argocd"))

    # --- Prometheus native ---
    n_firing = len(firing_alerts)
    alert_items = []
    for a in firing_alerts[:40]:
        name = a.get("name") or "alert"
        inst = a.get("instance") or ""
        label = f"{name} {inst}".strip()
        alert_items.append({"key": f"alert:{name}|{inst}", "label": label})
    checks.append(_check(
        "prom_alerts", "Prometheus firing",
        "ok" if n_firing == 0 else "warning",
        f"{n_firing} 条",
        source="prometheus", items=alert_items,
    ))
    if n_firing:
        findings.append(f"Prometheus firing {n_firing} 条")

    n_down = len(down_targets)
    down_items = []
    for t in down_targets[:40]:
        job = t.get("job") or ""
        inst = t.get("instance") or ""
        when = _fmt_when(t.get("last_scrape"))
        down_items.append({
            "key": f"target:{job}:{inst}",
            "label": f"{job}:{inst}" + (f"  {when}" if when else ""),
            "when": when,
        })
    checks.append(_check(
        "prom_targets", "Prometheus targets down",
        "ok" if n_down == 0 else "critical",
        str(n_down),
        source="prometheus", items=down_items,
    ))
    if n_down:
        findings.append(f"Down Targets {n_down} 个")

    if decommissioned:
        n_alert = sum(1 for x in decommissioned if x.get("kind") == "alert")
        n_target = sum(1 for x in decommissioned if x.get("kind") == "target")
        bits = []
        if n_alert:
            bits.append(f"HostDown {n_alert} 个")
        if n_target:
            bits.append(f"抓取 {n_target} 个")
        decomm_items = []
        for x in decommissioned:
            job = x.get("job") or ""
            inst = x.get("instance") or ""
            kind = x.get("kind") or "target"
            key = f"target:{job}:{inst}" if kind == "target" else f"alert:{x.get('name') or ''}|{inst}"
            decomm_items.append({
                "key": key,
                "label": x.get("label") or f"{job} {inst}".strip(),
                "when": x.get("when") or "",
            })
        checks.append(_check(
            "decommissioned",
            "已下线残留",
            "info",
            "、".join(bits) + " 仍在被抓取",
            source="prometheus", items=decomm_items,
        ))

    probe_rows = query_fn("probe_success == 0") or []
    if presence("probe_success"):
        n = len(probe_rows)
        level = "ok" if n == 0 else "warning"
        checks.append(_check("blackbox", "Blackbox 失败", level, str(n), _series_names(probe_rows), "blackbox"))
        if n:
            findings.append(f"Blackbox 失败 {n} 个")
    else:
        checks.append(_check("blackbox", "Blackbox 失败", "skip", "无 probe_success 指标", source="blackbox"))

    if es.get("available"):
        for cluster in es.get("clusters") or []:
            status = (cluster.get("status") or "unknown").lower()
            name = cluster.get("cluster") or "elasticsearch"
            bits = [status]
            if cluster.get("nodes") is not None:
                bits.append(f"nodes={cluster.get('nodes')}")
            if cluster.get("unassigned_shards") is not None:
                bits.append(f"unassigned={cluster.get('unassigned_shards')}")
            heap = cluster.get("heap_nodes") or []
            if heap and heap[0].get("heap_pct", -1) >= 0:
                bits.append(f"heap_max={heap[0]['heap_pct']}%({heap[0]['node']})")
            if status == "red":
                level = "critical"
            elif status == "yellow":
                level = "warning"
            elif status == "green":
                level = "ok"
            else:
                level = "warning"
            checks.append(_check(
                "elasticsearch", "Elasticsearch",
                level, f"{name} " + " ".join(bits),
                [f"{h['node']} heap {h['heap_pct']}%" for h in heap[:8] if h.get("heap_pct", -1) >= 0],
                "elasticsearch-exporter",
            ))
            if status == "red":
                findings.append(f"Elasticsearch {name} 状态 red")
            elif status == "yellow":
                findings.append(f"Elasticsearch {name} 状态 yellow")
            elif status not in ("green",):
                findings.append(f"Elasticsearch {name} 状态 {status}")
        if not es.get("clusters"):
            checks.append(_check("elasticsearch", "Elasticsearch", "warning", "有指标但无法解析集群色", source="elasticsearch-exporter"))
    else:
        checks.append(_check("elasticsearch", "Elasticsearch", "skip", "无 elasticsearch_cluster_health_status，确认 elasticsearch-exporter 已被抓取", source="elasticsearch-exporter"))

    mw_items = middleware.get("items") or []
    if mw_items:
        for item in mw_items:
            checks.append(_check(
                f"mw_{item['id']}", item["name"], item["level"], item["result"],
                item.get("instances") or [], item.get("source") or "prometheus",
            ))
            if item["level"] == "critical":
                extra = "：" + ", ".join((item.get("instances") or [])[:6]) if item.get("instances") else ""
                findings.append(f"{item['name']} down {item.get('down')}{extra}")
            elif item["level"] == "warning":
                findings.append(f"{item['name']} {item['result']}")
    else:
        checks.append(_check(
            "middleware", "中间件 exporter", "skip",
            "未扫到中间件 exporter 指标。先让 redis/mysql/pg 等 *_up 或 aws_rds_* 被 Prometheus 抓取，不在 Shark 里调 AWS API",
            source="prometheus",
        ))

    if workloads.get("available"):
        groups = workloads.get("groups") or []
        witems = workloads.get("items") or []
        bad_g = [g for g in groups if g.get("level") in ("warning", "critical")]
        level = "ok"
        if any(g.get("level") == "critical" for g in bad_g):
            level = "critical"
        elif bad_g:
            level = "warning"
        checks.append(_check(
            "workloads", "工作负载",
            level,
            f"{len(groups)} 个负载，未就绪 {len(bad_g)} 个",
            [f"{g.get('service')} {g.get('ready')}/{g.get('desired')} {g.get('namespace')}/{g.get('name')}" for g in groups[:40]],
            "kube-state-metrics",
        ))
        covered = set()
        for g in bad_g:
            bad_pods = [p for p in (g.get("pods") or []) if p.get("level") in ("warning", "critical")]
            extra = ""
            if bad_pods:
                extra = "；" + ", ".join(
                    f"{p.get('pod')} {p.get('phase')}" + (f"/{p.get('waiting')}" if p.get("waiting") else "")
                    for p in bad_pods[:6]
                )
            findings.append(
                f"{g.get('service')} Ready {g.get('ready')}/{g.get('desired')}（{g.get('kind')} {g.get('namespace')}/{g.get('name')}）{extra}"
            )
            covered.update(p.get("key") for p in bad_pods if p.get("key"))
        for x in witems:
            if x.get("level") not in ("warning", "critical") or x.get("key") in covered:
                continue
            extra = f" {x['waiting']}" if x.get("waiting") else ""
            findings.append(f"Pod {x.get('phase')}{extra}：{x.get('service')} ({x.get('key')})")
    else:
        checks.append(_check("workloads", "工作负载", "skip", "无 kube_pod_status_phase / Deployment 副本指标", source="kube-state-metrics"))

    # PVC usage：列出全部，不合并成一张服务卡
    if pvc["available"]:
        hot = [x for x in pvc["items"] if x["pct"] >= PVC_WARN_PCT and x.get("usage_alert")]
        crit = [x for x in hot if x["pct"] >= PVC_CRIT_PCT]
        shown = (crit[0] if crit else hot[0] if hot else (pvc["items"][0] if pvc["items"] else None))
        n = len(pvc["items"])
        top_txt = f"{n} 块"
        if shown and shown["pct"] >= 0:
            top_txt = f"{n} 块，最高 {shown['pct']}% {shown['key']}"
        level = "ok"
        if crit:
            level = "critical"
        elif hot:
            level = "warning"
        checks.append(_check(
            "pvc_usage", "PVC 用量",
            level, top_txt,
            [f"{x['pct']}% {x['key']}" for x in pvc["items"][:30]],
            pvc["source"],
        ))
        for x in hot:
            findings.append(f"PVC 用量 {x['pct']}%：{x['service']} ({x['key']})")
        baseline_hot = [x for x in pvc["items"] if x["pct"] >= PVC_WARN_PCT and not x.get("usage_alert")]
        if baseline_hot and not hot:
            checks[-1]["result"] = f"{top_txt}（已知常态，不告警）"
    else:
        checks.append(_check(
            "pvc_usage", "PVC 用量", "skip",
            "无 pvc_stats_* / kubelet_volume_stats_*，确认 pvc-stats-exporter 已被 Prometheus 抓取",
            source="pvc-stats-exporter",
        ))

    if servers:
        servers = mark_server_pressure(servers)
        hot = [s for s in servers if s.get("level") in ("warning", "critical")]
        crit_n = sum(1 for s in hot if s.get("level") == "critical")
        items = []
        for s in hot[:40]:
            inst = s.get("instance") or ""
            name = s.get("service") or inst
            bits = s.get("pressure") or []
            items.append({
                "key": f"node:{inst}",
                "label": f"{name}  {'  '.join(bits)}  {inst}".strip(),
            })
        level = "ok"
        if crit_n:
            level = "critical"
        elif hot:
            level = "warning"
        checks.append(_check(
            "node_resources", "节点资源偏高",
            level,
            f"{len(hot)} / {len(servers)}",
            source="node-exporter", items=items,
        ))
        if hot:
            findings.append(f"节点资源偏高 {len(hot)} 台")
    else:
        checks.append(_check(
            "node_resources", "节点资源偏高", "skip",
            "无 node-exporter CPU/内存/磁盘用量",
            source="node-exporter",
        ))

    sampled, trend_items = collect_resource_trend_items(servers, pvc.get("items") or [])
    if sampled:
        checks.append(_check(
            "resource_trend", "24h 用量上升",
            "warning" if trend_items else "ok",
            f"{len(trend_items)} 项超过 {RESOURCE_DELTA_WARN_PT}pt" if trend_items else "未见磁盘/内存/PVC 24h 上升过阈值",
            source="prometheus", items=trend_items,
        ))
        for it in trend_items:
            findings.append(it.get("label") or "24h 用量上升")
    else:
        checks.append(_check(
            "resource_trend", "24h 用量上升", "skip",
            "无 24h 前样本（Prom 保留不够或新接入）",
            source="prometheus",
        ))

    checks = _strip_ignored(checks, ignore_keys)

    core_ids = {"nodes", "pods", "pvc_usage"}
    core_ok = [c for c in checks if c["id"] in core_ids and c["level"] != "skip"]
    data_insufficient = not core_ok and not servers

    if data_insufficient:
        verdict = "无法判定（节点/Pod/PVC 均无有效指标）"
        findings = ["核心检查未覆盖：请确认 Prometheus、kube-state-metrics、pvc-stats-exporter"] + findings
    elif not findings:
        verdict = "本次 Prom 巡检项未见明显异常"
    else:
        verdict = f"需关注（{len(findings)} 项）"

    services = []
    for item in pvc["items"]:
        level = "ok"
        if item["pct"] >= PVC_CRIT_PCT and item.get("usage_alert"):
            level = "critical"
        elif item["pct"] >= PVC_WARN_PCT and item.get("usage_alert"):
            level = "warning"
        elif item["pct"] >= PVC_WARN_PCT:
            level = "info"
        services.append({
            "service": item["service"],
            "status": level,
            "summary": f"{item['key']} 用量 {item['pct']}%",
            "baseline": item.get("baseline") or "",
            "key": item["key"],
            "pct": item["pct"],
        })

    prev_keys = {str(k) for k in (previous_leftover_keys or []) if k}
    extra_normals = []
    for item in decommissioned:
        key = f"{item.get('job') or ''}|{item.get('instance') or ''}"
        if key in prev_keys:
            item["persistent"] = True
            extra_normals.append(
                f"历史残留连续出现：{item.get('job') or item.get('name')} {item.get('instance')}（关机未摘 scrape，已忽略）"
            )

    checks = _fold_uncovered(checks, middleware=middleware, metric_names=metric_names)

    return {
        "verdict": verdict,
        "findings": findings,
        "checks": checks,
        "pvc": pvc,
        "services": services,
        "elasticsearch": es,
        "workloads": workloads,
        "middleware": middleware,
        "known_normals": list(KNOWN_NORMALS) + extra_normals,
        "data_insufficient": data_insufficient,
        "firing_alerts": firing_alerts,
        "down_targets": down_targets,
        "decommissioned": decommissioned,
        "discovery": {
            "scanned": metric_names is not None,
            "metric_name_count": len(metric_names or []),
            "middleware_families": len(mw_items),
        },
    }


def compute_health_score(down_targets, firing_alerts, servers, pvc_items=None, data_insufficient=False, elasticsearch=None, cluster=None):
    """健康分。data_insufficient 时分数为空，避免「全 skip 却 100 分」。"""
    if data_insufficient:
        return None, "unknown", ["核心检查未覆盖，分数无效"]

    cluster = cluster or {}
    if elasticsearch is None:
        elasticsearch = cluster.get("elasticsearch")

    score = 100.0
    reasons = []

    # 按类目封顶，避免「7 个 down target × 20」直接打到 0 分。
    if down_targets:
        n = len(down_targets)
        deduction = min(n * 8, 24)
        score -= deduction
        reasons.append(f"Down Targets ({n}): -{deduction}")

    crit_n = 0
    warn_n = 0
    for alert in firing_alerts or []:
        severity = str(alert.get("severity") or "warning").lower()
        if severity in ["critical", "high"]:
            crit_n += 1
        else:
            warn_n += 1
    alert_deduction = min(crit_n * 8 + warn_n * 4, 24)
    if alert_deduction:
        score -= alert_deduction
        bits = []
        if crit_n:
            bits.append(f"critical {crit_n}")
        if warn_n:
            bits.append(f"warning {warn_n}")
        reasons.append(f"Alerts ({', '.join(bits)}): -{alert_deduction}")

    if servers:
        max_cpu = max((float(s.get("cpu_pct") or 0) for s in servers), default=0)
        mem_vals = []
        for s in servers:
            mem = float(s.get("mem_pct") or 0)
            alias = (
                resolve_service(name=s.get("node_name") or s.get("hostname") or "", instance=s.get("instance") or "")
                or resolve_service(instance=s.get("node_name") or s.get("hostname") or "")
            )
            limit = (alias or {}).get("mem_alert_threshold")
            if limit and mem < float(limit):
                continue
            mem_vals.append(mem)
        max_mem = max(mem_vals) if mem_vals else 0
        max_disk = max((float(s.get("disk_pct") or 0) for s in servers), default=0)

        if max_cpu > 95:
            score -= 10
            reasons.append(f"CPU热点(最高{round(max_cpu,1)}%): -10")
        elif max_cpu > 85:
            score -= 5
            reasons.append(f"CPU偏高(最高{round(max_cpu,1)}%): -5")

        if max_mem > 95:
            score -= 10
            reasons.append(f"内存热点(最高{round(max_mem,1)}%): -10")
        elif max_mem > 85:
            score -= 5
            reasons.append(f"内存偏高(最高{round(max_mem,1)}%): -5")

        if max_disk > 95:
            score -= 15
            reasons.append(f"磁盘临界(最高{round(max_disk,1)}%): -15")
        elif max_disk > 90:
            score -= 5
            reasons.append(f"磁盘偏高(最高{round(max_disk,1)}%): -5")

    pvc_delta, pvc_reasons = pvc_health_penalty(pvc_items)
    score += pvc_delta
    reasons.extend(pvc_reasons[:8])

    for es_cluster in (elasticsearch or {}).get("clusters") or []:
        name = es_cluster.get("cluster") or "elasticsearch"
        status = (es_cluster.get("status") or "").lower()
        if status == "red":
            score -= 15
            reasons.append(f"Elasticsearch {name} red: -15")
        elif status == "yellow":
            score -= 5
            reasons.append(f"Elasticsearch {name} yellow: -5")

    already = {"prom_alerts", "prom_targets", "pvc_usage", "elasticsearch", "node_resources"}
    n_crit = 0
    n_warn = 0
    for check in cluster.get("checks") or []:
        cid = check.get("id") or ""
        level = check.get("level") or ""
        if cid in already or level in ("ok", "skip", "info"):
            continue
        name = check.get("name") or cid
        if level == "critical" and n_crit < 4:
            score -= 10
            n_crit += 1
            reasons.append(f"{name}: -10")
        elif level == "warning" and n_warn < 6:
            score -= 5
            n_warn += 1
            reasons.append(f"{name}: -5")

    score = max(0.0, score)
    level = "ok"
    if score < 60:
        level = "critical"
    elif score < 85:
        level = "warning"
    if not reasons:
        reasons.append("System Healthy")
    return round(score, 1), level, reasons


def pvc_health_penalty(pvc_items):
    reasons = []
    score_delta = 0
    for item in pvc_items or []:
        if not item.get("usage_alert"):
            continue
        pct = item.get("pct") or -1
        label = f"{item.get('service')} {item.get('key')}"
        if pct >= PVC_CRIT_PCT:
            score_delta -= 15
            reasons.append(f"PVC 临界 {pct}% ({label}): -15")
        elif pct >= PVC_WARN_PCT:
            score_delta -= 5
            reasons.append(f"PVC 偏高 {pct}% ({label}): -5")
    return score_delta, reasons
