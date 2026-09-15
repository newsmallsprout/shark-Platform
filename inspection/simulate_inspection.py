"""模拟多轮巡检：对照改前（只有 Prom 告警+节点）和改后（清单+PVC+别名）。"""
from inspection.cluster_checks import collect_cluster_checks, compute_health_score
from inspection.catalog import display_name


def score(down_targets, firing_alerts, servers, pvc_items, data_insufficient=False, elasticsearch=None):
    return compute_health_score(
        down_targets, firing_alerts, servers,
        pvc_items=pvc_items,
        data_insufficient=data_insufficient,
        elasticsearch=elasticsearch,
    )


def _vec(metric, value):
    return {"metric": dict(metric), "value": [0, str(value)]}


class Prom:
    def __init__(self, series):
        self.series = series  # list of (query_contains or exact, rows)
        self.calls = []

    def __call__(self, q):
        self.calls.append(q)
        if q.startswith("count(") and q.endswith(")"):
            inner = q[6:-1]
            rows = self._match(inner)
            if not rows:
                return []
            return [_vec({}, len(rows))]
        return self._match(q)

    def _match(self, q):
        if q in self.series:
            return self.series[q]
        # comparator queries: "metric == 0" / "> 10"
        for key, rows in self.series.items():
            if q.startswith(key) and q != key:
                rest = q[len(key):].strip()
                if rest.startswith("=="):
                    rhs = float(rest[2:].strip())
                    return [r for r in rows if abs(float(r["value"][1]) - rhs) < 1e-9]
                if rest.startswith(">"):
                    rhs = float(rest[1:].strip())
                    return [r for r in rows if float(r["value"][1]) > rhs]
                if rest.startswith("!="):
                    # not used as suffix on raw metric in our code except pvc phase in selector
                    return rows
        return []


def dump(title, cluster, health):
    print("=" * 72)
    print(title)
    print("- verdict:", cluster["verdict"])
    print("- findings:", cluster["findings"] or "无")
    print("- health:", health)
    print("- checks:")
    for c in cluster["checks"]:
        print(f"    [{c['level']:8}] {c['name']}: {c['result']}")
    if cluster.get("services"):
        print("- services:")
        for s in cluster["services"]:
            print(f"    [{s['status']:8}] {s['service']}: {s['summary']}")
    print("- pvc:", len((cluster.get("pvc") or {}).get("items") or []), "块", [
        f"{x['pct']}% {x['key']}"
        for x in (cluster.get("pvc") or {}).get("items") or []
    ])
    es = cluster.get("elasticsearch") or {}
    if es.get("clusters"):
        print("- es:", [
            f"{c.get('cluster')} {c.get('status')} nodes={c.get('nodes')} unassigned={c.get('unassigned_shards')}"
            for c in es["clusters"]
        ])
        print("- es heap:", [f"{h['node']} {h['heap_pct']}%" for h in (es.get("heap_nodes") or [])[:5]])


def ksm_ok():
    return {
        "kube_node_status_condition": [_vec({"node": "n1", "condition": "Ready"}, 1)],
        'kube_node_status_condition{condition="Ready",status="true"}': [_vec({"node": "n1"}, 1)],
        "kube_pod_status_phase": [_vec({"phase": "Running"}, 1)],
        "kube_persistentvolumeclaim_status_phase": [_vec({"phase": "Bound"}, 1)],
        "kube_deployment_spec_replicas": [_vec({"deployment": "web"}, 2)],
        "kube_pod_container_status_restarts_total": [_vec({"pod": "web-1"}, 0)],
        "probe_success": [_vec({"instance": "https://x"}, 1)],
    }


def es_green_heap():
    """现网 elasticsearch-exporter：color 标签 + 节点 name（无 cluster 时归到 elasticsearch）。"""
    return {
        "elasticsearch_cluster_health_status": [
            _vec({"color": "green"}, 1),
            _vec({"color": "yellow"}, 0),
            _vec({"color": "red"}, 0),
        ],
        "elasticsearch_cluster_health_number_of_nodes": [_vec({}, 3)],
        "elasticsearch_cluster_health_number_of_data_nodes": [_vec({}, 3)],
        "elasticsearch_cluster_health_unassigned_shards": [_vec({}, 0)],
        'elasticsearch_jvm_memory_used_bytes{area="heap"}': [
            _vec({"name": "es-1"}, 82),
        ],
        'elasticsearch_jvm_memory_max_bytes{area="heap"}': [
            _vec({"name": "es-1"}, 100),
        ],
    }


def scenario_prd_normal():
    """贴近现网：Flink 盘 33%/25%，撮合 0%，ES green 堆 82%，机器 instance 是 IP。"""
    series = {
        **ksm_ok(),
        **es_green_heap(),
        "pvc_stats_used_bytes": [
            _vec({"namespace": "flink-system", "persistentvolumeclaim": "major-job-tm-pvc"}, 33e9),
            _vec({"namespace": "flink-system", "persistentvolumeclaim": "single-job-tm-pvc"}, 25e9),
            _vec({"namespace": "flink-system", "persistentvolumeclaim": "single-job-jm-pvc"}, 5e9),
            _vec({"namespace": "flink-system", "persistentvolumeclaim": "major-job-jm-pvc"}, 2e9),
            _vec({"namespace": "monitor", "persistentvolumeclaim": "data-grafana-0"}, 3e9),
            _vec({"namespace": "biz-system", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 0),
            _vec({"namespace": "biz-system", "persistentvolumeclaim": "exchange-match-pvc"}, 0),
            _vec({"namespace": "middleware-system", "persistentvolumeclaim": "shark-platform-state-pvc"}, 0),
        ],
        "pvc_stats_capacity_bytes": [
            _vec({"namespace": "flink-system", "persistentvolumeclaim": "major-job-tm-pvc"}, 100e9),
            _vec({"namespace": "flink-system", "persistentvolumeclaim": "single-job-tm-pvc"}, 100e9),
            _vec({"namespace": "flink-system", "persistentvolumeclaim": "single-job-jm-pvc"}, 100e9),
            _vec({"namespace": "flink-system", "persistentvolumeclaim": "major-job-jm-pvc"}, 100e9),
            _vec({"namespace": "monitor", "persistentvolumeclaim": "data-grafana-0"}, 100e9),
            _vec({"namespace": "biz-system", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 100e9),
            _vec({"namespace": "biz-system", "persistentvolumeclaim": "exchange-match-pvc"}, 100e9),
            _vec({"namespace": "middleware-system", "persistentvolumeclaim": "shark-platform-state-pvc"}, 10e9),
        ],
    }
    servers = [
        {"instance": "10.20.10.72:9100", "cpu_pct": 20, "mem_pct": 40, "disk_pct": 55},
        {"instance": "10.10.0.71:9100", "cpu_pct": 15, "mem_pct": 82, "disk_pct": 40},
    ]
    return Prom(series), [], [], servers
    """PRD 常态：撮合 PVC 高、ES/JMS 内存高、其余健康。"""
    series = {
        "pvc_stats_used_bytes": [
            _vec({"namespace": "exchange", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 460e9),
            _vec({"namespace": "logging-system", "persistentvolumeclaim": "loki-data"}, 20e9),
            _vec({"namespace": "flink-system", "persistentvolumeclaim": "flink-checkpoints"}, 30e9),
        ],
        "pvc_stats_capacity_bytes": [
            _vec({"namespace": "exchange", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 500e9),
            _vec({"namespace": "logging-system", "persistentvolumeclaim": "loki-data"}, 200e9),
            _vec({"namespace": "flink-system", "persistentvolumeclaim": "flink-checkpoints"}, 100e9),
        ],
        "kube_node_status_condition": [_vec({"node": "ip-10-0-1-1", "condition": "Ready"}, 1)],
        'kube_node_status_condition{condition="Ready",status="true"}': [
            _vec({"node": "ip-10-0-1-1"}, 1),
            _vec({"node": "ip-10-0-1-2"}, 1),
        ],
        "kube_pod_status_phase": [_vec({"phase": "Running", "pod": "x"}, 1)],
        "kube_persistentvolumeclaim_status_phase": [_vec({"phase": "Bound"}, 1)],
        "kube_deployment_spec_replicas": [_vec({"deployment": "web"}, 2)],
        "kube_pod_container_status_restarts_total": [_vec({"pod": "web-1"}, 1)],
        "probe_success": [_vec({"instance": "https://es.etz.com"}, 1)],
    }
    servers = [
        {"instance": "10.0.1.11:9100", "cpu_pct": 20, "mem_pct": 40, "disk_pct": 55},
        {"instance": "jumpserver-0:9100", "cpu_pct": 15, "mem_pct": 82, "disk_pct": 40},
        {"instance": "elasticsearch-data-0:9100", "cpu_pct": 30, "mem_pct": 82, "disk_pct": 60},
    ]
    for s in servers:
        s["service"] = display_name(instance=s["instance"])
    return Prom(series), [], [], servers


def scenario_prom_down():
    return Prom({}), [], [], []


def scenario_real_fault():
    series = {
        "pvc_stats_used_bytes": [
            _vec({"namespace": "exchange", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 420e9),
            _vec({"namespace": "app", "persistentvolumeclaim": "order-mysql-data"}, 95e9),
        ],
        "pvc_stats_capacity_bytes": [
            _vec({"namespace": "exchange", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 500e9),
            _vec({"namespace": "app", "persistentvolumeclaim": "order-mysql-data"}, 100e9),
        ],
        'kube_node_status_condition{condition="Ready",status="true"}': [
            _vec({"node": "ip-10-0-1-1"}, 1),
            _vec({"node": "ip-10-0-1-2"}, 0),
        ],
        "kube_node_status_condition": [_vec({}, 1)],
        "kube_pod_status_phase": [_vec({"phase": "Failed", "pod": "order-0", "namespace": "app"}, 1)],
        'kube_pod_status_phase{phase=~"Pending|Failed|Unknown"}': [
            _vec({"phase": "Failed", "pod": "order-0", "namespace": "app"}, 1),
        ],
        "kube_persistentvolumeclaim_status_phase": [_vec({"phase": "Bound"}, 1)],
        "kube_deployment_spec_replicas": [_vec({"deployment": "web"}, 2)],
        "kube_pod_container_status_restarts_total": [_vec({"pod": "web-1"}, 1)],
        "probe_success": [
            _vec({"instance": "https://es.etz.com"}, 1),
            _vec({"instance": "https://match.etz.com"}, 0),
        ],
    }
    servers = [
        {"instance": "10.0.1.11:9100", "cpu_pct": 20, "mem_pct": 40, "disk_pct": 96},
        {"instance": "jumpserver-0:9100", "cpu_pct": 15, "mem_pct": 88, "disk_pct": 40},
    ]
    for s in servers:
        s["service"] = display_name(instance=s["instance"])
    firing = [{"name": "KubeNodeNotReady", "severity": "critical"}]
    down = [{"job": "node", "instance": "10.0.1.2:9100"}]
    return Prom(series), firing, down, servers


def scenario_mismatched_pvc_metrics():
    """used 来自 pvc_stats，capacity 只有 kubelet（键对不上）。"""
    series = {
        "pvc_stats_used_bytes": [
            _vec({"namespace": "app", "persistentvolumeclaim": "order-mysql-data"}, 90e9),
        ],
        "kubelet_volume_stats_capacity_bytes": [
            _vec({"namespace": "app", "persistentvolumeclaim": "order-mysql-data"}, 100e9),
        ],
    }
    return Prom(series), [], [], []


def scenario_jms_mem_only():
    """只有 JumpServer 内存 88%，其余空闲。"""
    series = {
        "pvc_stats_used_bytes": [
            _vec({"namespace": "default", "persistentvolumeclaim": "small"}, 1e9),
        ],
        "pvc_stats_capacity_bytes": [
            _vec({"namespace": "default", "persistentvolumeclaim": "small"}, 10e9),
        ],
        "kube_node_status_condition": [_vec({}, 1)],
        'kube_node_status_condition{condition="Ready",status="true"}': [_vec({"node": "n1"}, 1)],
        "kube_pod_status_phase": [_vec({"phase": "Running"}, 1)],
        "kube_persistentvolumeclaim_status_phase": [_vec({"phase": "Bound"}, 1)],
        "kube_deployment_spec_replicas": [_vec({}, 1)],
        "kube_pod_container_status_restarts_total": [_vec({}, 0)],
        "probe_success": [_vec({}, 1)],
    }
    servers = [
        {"instance": "jumpserver-0:9100", "cpu_pct": 10, "mem_pct": 88, "disk_pct": 30, "service": "JumpServer"},
        {"instance": "worker-1:9100", "cpu_pct": 12, "mem_pct": 40, "disk_pct": 30, "service": "worker-1:9100"},
    ]
    return Prom(series), [], [], servers


def main():
    problems = []

    # 1 PRD 常态
    prom, firing, down, servers = scenario_prd_normal()
    cluster = collect_cluster_checks(prom, firing, down, servers)
    h = score(down, firing, servers, cluster["pvc"]["items"], cluster.get("data_insufficient"), cluster.get("elasticsearch"))
    dump("1) 现网形态（Flink 多块盘 + 撮合 0% + ES green 堆 82% + 机器 IP）", cluster, h)
    keys = [x["key"] for x in cluster["pvc"]["items"]]
    if len(cluster["pvc"]["items"]) != 8:
        problems.append(f"现网 PVC 应列出 8 块，实际 {len(cluster['pvc']['items'])} {keys}")
    if "biz-system/exchange-match-engine-major-pvc" not in keys:
        problems.append("0% 撮合盘被丢掉了")
    flink = [k for k in keys if k.startswith("flink-system/")]
    if len(flink) != 4:
        problems.append(f"Flink 四块盘应全列出，实际 {flink}")
    es_check = next(c for c in cluster["checks"] if c["id"] == "elasticsearch")
    if es_check["level"] != "ok":
        problems.append(f"ES green 应为 ok: {es_check}")
    es_cs = (cluster.get("elasticsearch") or {}).get("clusters") or []
    if len(es_cs) != 1 or es_cs[0].get("status") != "green":
        problems.append(f"ES 应合成一个 green 集群，实际 {es_cs}")
    if any("撮合" in f or "yellow" in f for f in cluster["findings"]):
        problems.append(f"现网形态不应有撮合/ES 告警: {cluster['findings']}")
    if h[0] != 100:
        problems.append(f"现网形态健康分应 100，实际 {h}")

    # 2 Prometheus 全挂
    prom, firing, down, servers = scenario_prom_down()
    cluster = collect_cluster_checks(prom, firing, down, servers)
    h = score(down, firing, servers, cluster["pvc"]["items"], cluster.get("data_insufficient"), cluster.get("elasticsearch"))
    dump("2) Prometheus 拉不到任何指标", cluster, h)
    skips = sum(1 for c in cluster["checks"] if c["level"] == "skip")
    if "未见明显异常" in cluster["verdict"] and skips >= 5:
        problems.append("Prom 全挂时 verdict 仍是「未见明显异常」（假绿）")
    if h[0] == 100 and "未见明显异常" in cluster["verdict"]:
        problems.append("Prom 全挂时健康分 100 + 未见异常，和清单全 skip 矛盾")

    # 3 真实故障
    prom, firing, down, servers = scenario_real_fault()
    cluster = collect_cluster_checks(prom, firing, down, servers)
    h = score(down, firing, servers, cluster["pvc"]["items"], cluster.get("data_insufficient"), cluster.get("elasticsearch"))
    dump("3) 真实故障（NotReady + mysql PVC 95% + 撮合常态 + JMS 88% 内存）", cluster, h)
    pvc_check = next(c for c in cluster["checks"] if c["id"] == "pvc_usage")
    if "撮合" in pvc_check["result"] and "order-mysql" not in pvc_check["result"]:
        problems.append(f"PVC 结果行展示的是撮合（最高用量）而不是告警盘 mysql: {pvc_check['result']}")
    mem_check = next((c for c in cluster["checks"] if c["id"] == "node_mem"), None)
    if mem_check and mem_check["level"] != "ok":
        problems.append(f"JumpServer 88% 被清单判为异常（阈值应 95）: {mem_check}")
    if any("内存" in r and "88" in r for r in h[2]):
        problems.append(f"JumpServer 88% 被健康分扣分，但清单不当故障: {h}")
    if not any("order-mysql" in f or "95%" in f for f in cluster["findings"]):
        problems.append("mysql PVC 95% 没有进入 findings")

    # 4 used/cap 指标族不一致
    prom, firing, down, servers = scenario_mismatched_pvc_metrics()
    cluster = collect_cluster_checks(prom, firing, down, servers)
    h = score(down, firing, servers, cluster["pvc"]["items"], cluster.get("data_insufficient"), cluster.get("elasticsearch"))
    dump("4) used/cap 分属不同指标族（不再混拼）", cluster, h)
    if cluster.get("pvc", {}).get("available"):
        problems.append("不同指标族不应混拼出虚假用量")

    # 5 只有 JMS 内存
    prom, firing, down, servers = scenario_jms_mem_only()
    cluster = collect_cluster_checks(prom, firing, down, servers)
    h = score(down, firing, servers, cluster["pvc"]["items"], cluster.get("data_insufficient"), cluster.get("elasticsearch"))
    dump("5) 仅 JumpServer 内存 88%，无其它故障", cluster, h)
    if cluster["findings"]:
        problems.append(f"仅 JMS 88% 时 findings 应为空: {cluster['findings']}")
    if h[0] != 100:
        problems.append(f"仅 JMS 88% 时健康分应 100（已知常态），实际 {h}")

    # 6 撮合 92%（常态）+ mysql 86%（该告警）——结果行必须指向 mysql
    series = {
        "pvc_stats_used_bytes": [
            _vec({"namespace": "exchange", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 460e9),
            _vec({"namespace": "app", "persistentvolumeclaim": "order-mysql-data"}, 86e9),
        ],
        "pvc_stats_capacity_bytes": [
            _vec({"namespace": "exchange", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 500e9),
            _vec({"namespace": "app", "persistentvolumeclaim": "order-mysql-data"}, 100e9),
        ],
        "kube_node_status_condition": [_vec({}, 1)],
        'kube_node_status_condition{condition="Ready",status="true"}': [_vec({"node": "n1"}, 1)],
        "kube_pod_status_phase": [_vec({"phase": "Running"}, 1)],
        "kube_persistentvolumeclaim_status_phase": [_vec({"phase": "Bound"}, 1)],
        "kube_deployment_spec_replicas": [_vec({}, 1)],
        "kube_pod_container_status_restarts_total": [_vec({}, 0)],
        "probe_success": [_vec({}, 1)],
    }
    servers = [{"instance": "worker-1:9100", "cpu_pct": 10, "mem_pct": 40, "disk_pct": 30}]
    prom, firing, down = Prom(series), [], []
    cluster = collect_cluster_checks(prom, firing, down, servers)
    h = score(down, firing, servers, cluster["pvc"]["items"], cluster.get("data_insufficient"), cluster.get("elasticsearch"))
    dump("6) 撮合 PVC 92% 常态 + mysql 86% 告警", cluster, h)
    pvc_check = next(c for c in cluster["checks"] if c["id"] == "pvc_usage")
    if "撮合" in pvc_check["result"] and "mysql" not in pvc_check["result"]:
        problems.append(f"PVC 结果行应展示告警盘 mysql，而不是用量更高的撮合: {pvc_check['result']}")
    if pvc_check["level"] != "warning":
        problems.append(f"mysql 86% 应为 warning: {pvc_check}")

    # 7 ES yellow：应进 findings，堆仍展示
    series = {
        **ksm_ok(),
        "elasticsearch_cluster_health_status": [
            _vec({"cluster": "prd", "color": "green"}, 0),
            _vec({"cluster": "prd", "color": "yellow"}, 1),
            _vec({"cluster": "prd", "color": "red"}, 0),
        ],
        "elasticsearch_cluster_health_unassigned_shards": [_vec({"cluster": "prd"}, 4)],
        "pvc_stats_used_bytes": [_vec({"namespace": "ns", "persistentvolumeclaim": "p"}, 1e9)],
        "pvc_stats_capacity_bytes": [_vec({"namespace": "ns", "persistentvolumeclaim": "p"}, 10e9)],
    }
    servers = [{"instance": "10.0.0.1:9100", "cpu_pct": 10, "mem_pct": 40, "disk_pct": 30}]
    cluster = collect_cluster_checks(Prom(series), [], [], servers)
    h = score([], [], servers, cluster["pvc"]["items"], cluster.get("data_insufficient"), cluster.get("elasticsearch"))
    dump("7) ES yellow + 未分配分片", cluster, h)
    if not any("yellow" in f for f in cluster["findings"]):
        problems.append("ES yellow 应进入 findings")
    if h[0] != 95:
        problems.append(f"ES yellow 应扣 5 分，实际 {h}")

    # 8 ES 指标缺失
    series = {
        **ksm_ok(),
        "pvc_stats_used_bytes": [_vec({"namespace": "ns", "persistentvolumeclaim": "p"}, 1e9)],
        "pvc_stats_capacity_bytes": [_vec({"namespace": "ns", "persistentvolumeclaim": "p"}, 10e9)],
    }
    cluster = collect_cluster_checks(Prom(series), [], [], servers)
    dump("8) 无 ES exporter 指标", cluster, score([], [], servers, cluster["pvc"]["items"], cluster.get("data_insufficient"), cluster.get("elasticsearch")))
    es_check = next(c for c in cluster["checks"] if c["id"] == "elasticsearch")
    if es_check["level"] != "skip":
        problems.append(f"无 ES 指标应为 skip: {es_check}")
    if "无法判定" in cluster["verdict"]:
        problems.append("有 kube-state 和 PVC 时不应因缺 ES 无法判定")

    print("=" * 72)
    print("发现的逻辑问题:")
    if not problems:
        print("  无")
    else:
        for i, p in enumerate(problems, 1):
            print(f"  {i}. {p}")
    return problems


if __name__ == "__main__":
    main()
