"""把 inspect-prd.sh 的检查清单落到 Prometheus 即时查询。

PVC 用量优先用已在 PRD 部署的 pvc-stats-exporter（pvc_stats_*），
没有时再退回 kubelet_volume_stats_*。
K8s 对象状态依赖 kube-state-metrics；没有对应指标时检查项为 skip，不假装正常。
"""

from .catalog import (
    KNOWN_NORMALS,
    PVC_CRIT_PCT,
    PVC_WARN_PCT,
    display_name,
    resolve_service,
    watch_namespaces,
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
    return {
        "available": bool(readable),
        "source": source,
        "used_query": used_q,
        "capacity_query": cap_q,
        "items": readable,
        "top": readable,
    }


def _series_names(rows, limit=20):
    names = []
    for row in rows[:limit]:
        m = _metric(row)
        ns = m.get("namespace") or ""
        name = (
            m.get("persistentvolumeclaim")
            or m.get("pod")
            or m.get("deployment")
            or m.get("node")
            or m.get("instance")
            or m.get("job")
            or m.get("alertname")
            or ""
        )
        svc = display_name(namespace=ns, name=name, instance=m.get("instance") or "")
        label = svc if svc != "-" else (f"{ns}/{name}" if ns and name else name or str(m))
        names.append(label)
    return names


def _check(cid, name, level, result, detail=None, source=""):
    return {
        "id": cid,
        "name": name,
        "level": level,
        "result": result,
        "detail": detail or [],
        "source": source,
    }


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


def _pod_key(metric):
    m = metric or {}
    ns = m.get("namespace") or ""
    pod = m.get("pod") or ""
    return f"{ns}/{pod}", ns, pod


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

    watched = watch_namespaces()
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
        watch = ns.lower() in watched or bool(alias)
        abnormal = phase not in ("running", "succeeded") or bool(wait_reason)
        if phase == "succeeded" and not alias:
            continue
        if not watch and not abnormal:
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
        if (ns or "").lower() == "kube-system":
            return False
        if (ns or "").lower() in watched:
            return True
        return bool(resolve_service(namespace=ns, name=name, instance=name))

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
        if (g.get("namespace") or "").lower() == "kube-system" and not any(p.get("level") != "ok" for p in g["pods"]):
            continue
        pods = g["pods"]
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


def collect_cluster_checks(query_fn, firing_alerts=None, down_targets=None, servers=None):
    firing_alerts = firing_alerts or []
    down_targets = down_targets or []
    servers = servers or []

    pvc = collect_pvc_usage(query_fn)
    es = collect_elasticsearch(query_fn)
    workloads = collect_workloads(query_fn)
    checks = []
    findings = []

    def presence(query):
        rows = query_fn(f"count({query})") or []
        if not rows:
            # some Prometheuses reject count() wrapping; try raw
            return bool(query_fn(query))
        return _num(rows[0]) > 0

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

    abn_q = 'kube_pod_status_phase{phase=~"Pending|Failed|Unknown"}'
    abn_rows = query_fn(f"{abn_q} == 1") or query_fn(abn_q) or []
    if presence("kube_pod_status_phase"):
        n = len(abn_rows)
        level = "ok" if n == 0 else "warning"
        checks.append(_check("pods", "异常 Pod", level, str(n), _series_names(abn_rows), "kube-state-metrics"))
        if n:
            findings.append(f"异常 Pod {n} 个")
    else:
        checks.append(_check("pods", "异常 Pod", "skip", "无 Pod 相位指标", source="kube-state-metrics"))

    oom_rows = query_fn('kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1') or []
    restart_rows = query_fn("kube_pod_container_status_restarts_total > 10") or []
    if presence("kube_pod_container_status_restarts_total") or presence(
        'kube_pod_container_status_last_terminated_reason'
    ):
        n_oom = len(oom_rows)
        n_re = len(restart_rows)
        level = "ok" if n_oom == 0 and n_re == 0 else "warning"
        checks.append(_check(
            "stability", "OOM / 重启>10",
            level, f"{n_oom} / {n_re}",
            _series_names(oom_rows + restart_rows),
            "kube-state-metrics",
        ))
        if n_oom:
            findings.append(f"OOMKilled {n_oom} 个")
        if n_re:
            findings.append(f"重启>10 的容器 {n_re} 个")
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
        level = "ok" if n == 0 else "warning"
        checks.append(_check("replicas", "零副本 Deployment", level, str(n), _series_names(zero_rows), "kube-state-metrics"))
        if n:
            findings.append(f"零副本 Deployment {n} 个")
    else:
        checks.append(_check("replicas", "零副本 Deployment", "skip", "无 Deployment 副本指标", source="kube-state-metrics"))

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
    checks.append(_check(
        "prom_alerts", "Prometheus firing",
        "ok" if n_firing == 0 else "warning",
        f"{n_firing} 条",
        [a.get("name") for a in firing_alerts[:10] if a.get("name")],
        "prometheus",
    ))
    if n_firing:
        findings.append(f"Prometheus firing {n_firing} 条")

    n_down = len(down_targets)
    checks.append(_check(
        "prom_targets", "Prometheus targets down",
        "ok" if n_down == 0 else "critical",
        str(n_down),
        [f"{t.get('job')}:{t.get('instance')}" for t in down_targets[:10]],
        "prometheus",
    ))
    if n_down:
        findings.append(f"Down Targets {n_down} 个")

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

    mem_top = sorted(servers, key=lambda s: float(s.get("mem_pct") or 0), reverse=True)[:1]
    disk_top = sorted(servers, key=lambda s: float(s.get("disk_pct") or 0), reverse=True)[:1]
    if mem_top:
        s = mem_top[0]
        inst = s.get("instance") or ""
        svc = display_name(instance=inst)
        alias = resolve_service(instance=inst)
        pct = float(s.get("mem_pct") or 0)
        threshold = (alias or {}).get("mem_alert_threshold") or 85
        level = "ok"
        if pct >= threshold:
            level = "warning"
            findings.append(f"节点内存 {pct}%：{svc} ({inst})")
        elif alias and alias.get("baseline"):
            pass
        checks.append(_check("node_mem", "节点内存最高", level, f"{pct}% {svc}", [inst], "node-exporter"))
    if disk_top:
        s = disk_top[0]
        inst = s.get("instance") or ""
        pct = float(s.get("disk_pct") or 0)
        svc = display_name(instance=inst)
        level = "ok" if pct < 90 else ("critical" if pct >= 95 else "warning")
        checks.append(_check("node_disk", "节点磁盘最高", level, f"{pct}% {svc}", [inst], "node-exporter"))
        if pct >= 90:
            findings.append(f"节点磁盘 {pct}%：{svc} ({inst})")

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

    return {
        "verdict": verdict,
        "findings": findings,
        "checks": checks,
        "pvc": pvc,
        "services": services,
        "elasticsearch": es,
        "workloads": workloads,
        "known_normals": KNOWN_NORMALS,
        "data_insufficient": data_insufficient,
        "middleware_todo": [
            "aws rds describe-db-instances",
            "aws elasticache describe-cache-clusters",
            "aws mq describe-brokers",
            "Mongo rs.status()",
            "Flink JobManager /jobs",
        ],
    }


def compute_health_score(down_targets, firing_alerts, servers, pvc_items=None, data_insufficient=False, elasticsearch=None):
    """健康分。data_insufficient 时分数为空，避免「全 skip 却 100 分」。"""
    if data_insufficient:
        return None, "unknown", ["核心检查未覆盖，分数无效"]

    score = 100.0
    reasons = []

    if down_targets:
        deduction = len(down_targets) * 20
        score -= deduction
        reasons.append(f"Down Targets ({len(down_targets)}): -{deduction}")

    for alert in firing_alerts or []:
        severity = str(alert.get("severity") or "warning").lower()
        if severity in ["critical", "high"]:
            score -= 15
            reasons.append(f"Critical Alert ({alert.get('name')}): -15")
        else:
            score -= 5
            reasons.append(f"Warning Alert ({alert.get('name')}): -5")

    if servers:
        max_cpu = max((float(s.get("cpu_pct") or 0) for s in servers), default=0)
        mem_vals = []
        for s in servers:
            mem = float(s.get("mem_pct") or 0)
            alias = resolve_service(instance=s.get("instance") or "")
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

    for cluster in (elasticsearch or {}).get("clusters") or []:
        name = cluster.get("cluster") or "elasticsearch"
        status = (cluster.get("status") or "").lower()
        if status == "red":
            score -= 15
            reasons.append(f"Elasticsearch {name} red: -15")
        elif status == "yellow":
            score -= 5
            reasons.append(f"Elasticsearch {name} yellow: -5")

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
