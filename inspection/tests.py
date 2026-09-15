import unittest

from inspection.catalog import display_name, resolve_service
from inspection.cluster_checks import collect_cluster_checks, collect_pvc_usage, pvc_health_penalty, compute_health_score


def _vec(metric, value):
    return {"metric": metric, "value": [0, str(value)]}


class CatalogTests(unittest.TestCase):
    def test_match_engine_pvc_alias(self):
        alias = resolve_service(namespace="exchange", name="exchange-match-engine-major-pvc")
        self.assertIsNotNone(alias)
        self.assertEqual(alias["service"], "撮合引擎")
        self.assertFalse(alias["usage_alert"])

    def test_exchange_match_pvc_alias(self):
        alias = resolve_service(namespace="biz-system", name="exchange-match-pvc")
        self.assertIsNotNone(alias)
        self.assertEqual(alias["service"], "撮合引擎")

    def test_display_falls_back_to_ns_name(self):
        self.assertEqual(display_name(namespace="biz", name="unknown-pvc"), "biz/unknown-pvc")


class ClusterCheckTests(unittest.TestCase):
    def test_pvc_join_and_known_normal_not_finding(self):
        data = {
            "pvc_stats_used_bytes": [
                _vec({"namespace": "exchange", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 90),
                _vec({"namespace": "logging-system", "persistentvolumeclaim": "other-data"}, 90),
            ],
            "pvc_stats_capacity_bytes": [
                _vec({"namespace": "exchange", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 100),
                _vec({"namespace": "logging-system", "persistentvolumeclaim": "other-data"}, 100),
            ],
        }

        def query_fn(q):
            for key, rows in data.items():
                if q == key or q.startswith(key):
                    return rows
            if q.startswith("count("):
                inner = q[len("count("):-1]
                if inner in data or any(inner.startswith(k) for k in data):
                    return [_vec({}, 1)]
                return []
            return []

        pvc = collect_pvc_usage(query_fn)
        self.assertTrue(pvc["available"])
        self.assertEqual(pvc["source"], "pvc_stats_*")
        match = next(x for x in pvc["items"] if "match-engine" in x["pvc"])
        self.assertEqual(match["service"], "撮合引擎")
        self.assertEqual(match["pct"], 90)
        self.assertFalse(match["usage_alert"])

        cluster = collect_cluster_checks(query_fn, firing_alerts=[], down_targets=[], servers=[])
        self.assertTrue(any("other-data" in f for f in cluster["findings"]))
        self.assertFalse(any("撮合引擎" in f for f in cluster["findings"]))

        delta, reasons = pvc_health_penalty(pvc["items"])
        self.assertEqual(delta, -5)
        self.assertTrue(any("other-data" in r for r in reasons))
        self.assertFalse(any("撮合引擎" in r for r in reasons))

    def test_missing_metrics_are_skip_not_ok(self):
        def query_fn(_q):
            return []

        cluster = collect_cluster_checks(query_fn, firing_alerts=[], down_targets=[], servers=[])
        by_id = {c["id"]: c for c in cluster["checks"]}
        self.assertEqual(by_id["pvc_usage"]["level"], "skip")
        self.assertEqual(by_id["nodes"]["level"], "skip")
        self.assertEqual(by_id["workloads"]["level"], "skip")
        self.assertEqual(by_id["prom_alerts"]["level"], "ok")
        self.assertTrue(cluster["data_insufficient"])
        self.assertIn("无法判定", cluster["verdict"])
        score, level, reasons = compute_health_score([], [], [], cluster["pvc"]["items"], True)
        self.assertIsNone(score)
        self.assertEqual(level, "unknown")

    def test_jumpserver_mem_does_not_penalize_score(self):
        servers = [
            {"instance": "jumpserver-0:9100", "mem_pct": 88, "cpu_pct": 10, "disk_pct": 30},
            {"instance": "worker-1:9100", "mem_pct": 40, "cpu_pct": 12, "disk_pct": 30},
        ]
        score, level, reasons = compute_health_score([], [], servers, [])
        self.assertEqual(score, 100.0)
        self.assertEqual(reasons, ["System Healthy"])

    def test_all_pvcs_are_listed(self):
        data = {
            "pvc_stats_used_bytes": [
                _vec({"namespace": "flink-system", "persistentvolumeclaim": "major-job-tm-pvc"}, 33),
                _vec({"namespace": "flink-system", "persistentvolumeclaim": "single-job-tm-pvc"}, 25),
                _vec({"namespace": "biz-system", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 0),
            ],
            "pvc_stats_capacity_bytes": [
                _vec({"namespace": "flink-system", "persistentvolumeclaim": "major-job-tm-pvc"}, 100),
                _vec({"namespace": "flink-system", "persistentvolumeclaim": "single-job-tm-pvc"}, 100),
                _vec({"namespace": "biz-system", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 100),
            ],
        }

        def query_fn(q):
            return data.get(q) or []

        cluster = collect_cluster_checks(query_fn, servers=[{"instance": "10.0.0.1:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        self.assertEqual(len(cluster["pvc"]["items"]), 3)
        self.assertEqual(len(cluster["services"]), 3)
        keys = [x["key"] for x in cluster["pvc"]["items"]]
        self.assertIn("flink-system/major-job-tm-pvc", keys)
        self.assertIn("biz-system/exchange-match-engine-major-pvc", keys)

    def test_elasticsearch_from_exporter(self):
        data = {
            "elasticsearch_cluster_health_status": [
                _vec({"cluster": "prd", "color": "green"}, 0),
                _vec({"cluster": "prd", "color": "yellow"}, 1),
                _vec({"cluster": "prd", "color": "red"}, 0),
            ],
            "elasticsearch_cluster_health_number_of_nodes": [_vec({"cluster": "prd"}, 3)],
            "elasticsearch_cluster_health_unassigned_shards": [_vec({"cluster": "prd"}, 2)],
            'elasticsearch_jvm_memory_used_bytes{area="heap"}': [
                _vec({"cluster": "prd", "name": "es-1"}, 82),
            ],
            "elasticsearch_jvm_memory_max_bytes{area=\"heap\"}": [
                _vec({"cluster": "prd", "name": "es-1"}, 100),
            ],
        }

        def query_fn(q):
            if q in data:
                return data[q]
            return []

        cluster = collect_cluster_checks(query_fn, servers=[{"instance": "10.0.0.1:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        es_check = next(c for c in cluster["checks"] if c["id"] == "elasticsearch")
        self.assertEqual(es_check["level"], "warning")
        self.assertTrue(any("yellow" in f for f in cluster["findings"]))
        es = cluster["elasticsearch"]["clusters"][0]
        self.assertEqual(es["status"], "yellow")
        self.assertEqual(es["nodes"], 3)
        score, _, reasons = compute_health_score([], [], [{"instance": "x", "mem_pct": 10, "cpu_pct": 10, "disk_pct": 10}], [], elasticsearch=cluster["elasticsearch"])
        self.assertEqual(score, 95.0)
        self.assertTrue(any("yellow" in r for r in reasons))

    def test_es_heap_without_cluster_label_joins(self):
        data = {
            "elasticsearch_cluster_health_status": [
                _vec({"color": "green"}, 1),
                _vec({"color": "yellow"}, 0),
                _vec({"color": "red"}, 0),
            ],
            'elasticsearch_jvm_memory_used_bytes{area="heap"}': [_vec({"name": "es-1"}, 82)],
            'elasticsearch_jvm_memory_max_bytes{area="heap"}': [_vec({"name": "es-1"}, 100)],
        }

        def query_fn(q):
            return data.get(q) or []

        from inspection.cluster_checks import collect_elasticsearch
        es = collect_elasticsearch(query_fn)
        self.assertEqual(len(es["clusters"]), 1)
        self.assertEqual(es["clusters"][0]["status"], "green")
        self.assertEqual(es["heap_nodes"][0]["heap_pct"], 82)
        self.assertEqual(es["heap_nodes"][0]["cluster"], "elasticsearch")

    def test_pvc_result_prefers_alerting_volume(self):
        data = {
            "pvc_stats_used_bytes": [
                _vec({"namespace": "exchange", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 92),
                _vec({"namespace": "app", "persistentvolumeclaim": "order-mysql-data"}, 86),
            ],
            "pvc_stats_capacity_bytes": [
                _vec({"namespace": "exchange", "persistentvolumeclaim": "exchange-match-engine-major-pvc"}, 100),
                _vec({"namespace": "app", "persistentvolumeclaim": "order-mysql-data"}, 100),
            ],
        }

        def query_fn(q):
            return data.get(q) or []

        cluster = collect_cluster_checks(query_fn, servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        pvc_check = next(c for c in cluster["checks"] if c["id"] == "pvc_usage")
        self.assertIn("mysql", pvc_check["result"])
        self.assertNotIn("撮合", pvc_check["result"])
        self.assertEqual(pvc_check["level"], "warning")

    def test_workloads_by_pod_name(self):
        from inspection.simulate_inspection import Prom

        prom = Prom({
            "kube_pod_status_phase": [
                _vec({"namespace": "biz-system", "pod": "exchange-match-engine-0", "phase": "Running"}, 1),
                _vec({"namespace": "flink-system", "pod": "major-job-taskmanager-1", "phase": "Pending"}, 1),
                _vec({"namespace": "kube-system", "pod": "coredns-abc", "phase": "Running"}, 1),
            ],
            'kube_pod_status_ready{condition="true"}': [
                _vec({"namespace": "biz-system", "pod": "exchange-match-engine-0", "condition": "true"}, 1),
            ],
            "kube_pod_info": [
                _vec({"namespace": "biz-system", "pod": "exchange-match-engine-0", "pod_ip": "10.1.2.8", "host_ip": "10.10.0.71", "node": "n1"}, 1),
            ],
        })
        cluster = collect_cluster_checks(prom, servers=[{"instance": "10.0.0.1:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        pods = [x["pod"] for x in cluster["workloads"]["items"]]
        self.assertIn("exchange-match-engine-0", pods)
        self.assertIn("major-job-taskmanager-1", pods)
        self.assertNotIn("coredns-abc", pods)
        match = next(x for x in cluster["workloads"]["items"] if x["pod"] == "exchange-match-engine-0")
        self.assertEqual(match["service"], "撮合引擎")
        self.assertEqual(match["phase"], "running")
        self.assertEqual(match["pod_ip"], "10.1.2.8")
        self.assertTrue(any("major-job-taskmanager" in f or "Pending" in f or "pending" in f for f in cluster["findings"]))
        wl = next(c for c in cluster["checks"] if c["id"] == "workloads")
        self.assertEqual(wl["level"], "warning")
        groups = cluster["workloads"]["groups"]
        self.assertTrue(any("match-engine" in (g.get("name") or "") or g.get("service") == "撮合引擎" for g in groups))
        self.assertFalse(any((g.get("namespace") or "").lower() == "kube-system" for g in groups))
        flink = next(g for g in groups if "taskmanager" in (g.get("name") or "") or g.get("service") == "Flink Job")
        self.assertEqual(flink["level"], "warning")
        self.assertLess(flink["ready"], max(flink["desired"], 1))
        self.assertFalse(any(g.get("pod_ip") for g in groups))
        pod_findings = [f for f in cluster["findings"] if "taskmanager" in f.lower() or "pending" in f.lower()]
        self.assertEqual(len(pod_findings), 1)

    def test_workloads_attach_without_owner(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import collect_workloads

        w = collect_workloads(Prom({
            "kube_pod_status_phase": [
                _vec({"namespace": "biz-system", "pod": "exchange-match-engine-0", "phase": "Running"}, 1),
                _vec({"namespace": "biz-system", "pod": "exchange-match-engine-1", "phase": "Running"}, 1),
            ],
            "kube_deployment_spec_replicas": [
                _vec({"namespace": "biz-system", "deployment": "exchange-match-engine"}, 2),
            ],
            "kube_deployment_status_replicas_ready": [
                _vec({"namespace": "biz-system", "deployment": "exchange-match-engine"}, 2),
            ],
        }))
        names = [g["name"] for g in w["groups"]]
        self.assertEqual(names, ["exchange-match-engine"])
        self.assertEqual(len(w["groups"][0]["pods"]), 2)
        self.assertEqual(w["groups"][0]["kind"], "Deployment")

    def test_workloads_created_by_on_pod_info(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import collect_workloads

        w = collect_workloads(Prom({
            "kube_pod_status_phase": [
                _vec({"namespace": "flink-system", "pod": "major-job-taskmanager-1", "phase": "Running"}, 1),
            ],
            "kube_pod_info": [
                _vec({
                    "namespace": "flink-system", "pod": "major-job-taskmanager-1",
                    "pod_ip": "10.1.2.9", "created_by_kind": "StatefulSet",
                    "created_by_name": "major-job-taskmanager",
                }, 1),
            ],
            "kube_statefulset_replicas": [
                _vec({"namespace": "flink-system", "statefulset": "major-job-taskmanager"}, 1),
            ],
            "kube_statefulset_status_replicas_ready": [
                _vec({"namespace": "flink-system", "statefulset": "major-job-taskmanager"}, 1),
            ],
        }))
        self.assertEqual(len(w["groups"]), 1)
        self.assertEqual(w["groups"][0]["kind"], "StatefulSet")
        self.assertEqual(w["groups"][0]["pods"][0]["pod_ip"], "10.1.2.9")

    def test_workloads_crashloop_not_false_green(self):
        from inspection.simulate_inspection import Prom

        waiting_q = 'kube_pod_container_status_waiting_reason{reason=~"CrashLoopBackOff|ImagePullBackOff|ErrImagePull|CreateContainerError"}'
        cluster = collect_cluster_checks(Prom({
            "kube_pod_status_phase": [
                _vec({"namespace": "biz-system", "pod": "exchange-match-engine-0", "phase": "Running"}, 1),
            ],
            waiting_q: [
                _vec({"namespace": "biz-system", "pod": "exchange-match-engine-0", "reason": "CrashLoopBackOff"}, 1),
            ],
            "kube_deployment_spec_replicas": [
                _vec({"namespace": "biz-system", "deployment": "exchange-match-engine"}, 1),
            ],
            "kube_deployment_status_replicas_ready": [
                _vec({"namespace": "biz-system", "deployment": "exchange-match-engine"}, 1),
            ],
        }), servers=[{"instance": "10.0.0.1:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        groups = cluster["workloads"]["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["level"], "critical")
        self.assertEqual(groups[0]["kind"], "Deployment")
        wl = next(c for c in cluster["checks"] if c["id"] == "workloads")
        self.assertEqual(wl["level"], "critical")
        crash = [f for f in cluster["findings"] if "CrashLoopBackOff" in f or "exchange-match-engine" in f]
        self.assertEqual(len(crash), 1)


if __name__ == "__main__":
    unittest.main()
