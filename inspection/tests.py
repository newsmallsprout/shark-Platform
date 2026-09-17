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
        self.assertEqual(by_id["prom_alerts"]["level"], "ok")
        uncovered = by_id["uncovered"]
        self.assertEqual(uncovered["level"], "skip")
        blob = uncovered["result"] + " " + " ".join(uncovered.get("detail") or [])
        self.assertIn("节点", blob)
        self.assertIn("PVC", blob)
        self.assertIn("工作负载", blob)
        self.assertIn("中间件", blob)
        self.assertNotIn("pvc_usage", by_id)
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

    def test_hot_nodes_listed_in_checklist(self):
        from inspection.simulate_inspection import Prom

        cluster = collect_cluster_checks(
            Prom({}),
            servers=[
                {"instance": "w1:9100", "cpu_pct": 91, "mem_pct": 40, "disk_pct": 30},
                {"instance": "w2:9100", "cpu_pct": 10, "mem_pct": 20, "disk_pct": 15},
                {"instance": "jumpserver-0:9100", "cpu_pct": 10, "mem_pct": 88, "disk_pct": 30},
            ],
        )
        row = next(c for c in cluster["checks"] if c["id"] == "node_resources")
        self.assertEqual(row["level"], "warning")
        self.assertTrue(row["result"].startswith("1 / 3"))
        blob = " ".join(row["detail"] or [])
        self.assertIn("w1:9100", blob)
        self.assertNotIn("jumpserver", blob.lower())
        self.assertNotIn("w2:9100", blob)

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

    def test_middleware_redis_mysql_from_exporter(self):
        from inspection.simulate_inspection import Prom

        cluster = collect_cluster_checks(Prom({
            "redis_up": [
                _vec({"instance": "elasticache-1:9121"}, 1),
                _vec({"instance": "elasticache-2:9121"}, 0),
            ],
            "mysql_up": [
                _vec({"instance": "rds-order:9104"}, 1),
            ],
        }), servers=[{"instance": "10.0.0.1:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        names = [x["name"] for x in cluster["middleware"]["items"]]
        self.assertIn("Redis / ElastiCache", names)
        self.assertIn("MySQL / RDS", names)
        redis = next(x for x in cluster["middleware"]["items"] if x["id"] == "redis")
        self.assertEqual(redis["level"], "critical")
        self.assertEqual(redis["down"], 1)
        self.assertTrue(any("Redis" in f for f in cluster["findings"]))
        self.assertFalse(any(x["id"] == "mongodb" for x in cluster["middleware"]["items"]))

    def test_middleware_resources_used_max_and_watermark(self):
        from inspection.simulate_inspection import Prom

        names = [
            "redis_up", "redis_memory_used_bytes", "redis_memory_max_bytes",
            "mysql_up", "mysql_global_status_innodb_buffer_pool_bytes_data",
            "mysql_global_variables_innodb_buffer_pool_size",
            "rabbitmq_up", "rabbitmq_process_resident_memory_bytes",
            "rabbitmq_resident_memory_limit_bytes",
            "rabbitmq_disk_space_available_bytes", "rabbitmq_disk_space_available_limit_bytes",
            "mongodb_up", "mongodb_ss_mem_resident",
            "memcached_up", "memcached_current_bytes", "memcached_limit_bytes",
        ]
        cluster = collect_cluster_checks(Prom({
            "redis_up": [_vec({"instance": "r:9121"}, 1)],
            "redis_memory_used_bytes": [_vec({"instance": "r:9121"}, 80e6)],
            "redis_memory_max_bytes": [_vec({"instance": "r:9121"}, 0)],
            "mysql_up": [_vec({"instance": "db:9104"}, 1)],
            "mysql_global_status_innodb_buffer_pool_bytes_data": [_vec({"instance": "db:9104"}, 7.2e9)],
            "mysql_global_variables_innodb_buffer_pool_size": [_vec({"instance": "db:9104"}, 8e9)],
            "rabbitmq_up": [_vec({"instance": "mq:9419"}, 1)],
            "rabbitmq_process_resident_memory_bytes": [_vec({"instance": "mq:9419"}, 1e9)],
            "rabbitmq_resident_memory_limit_bytes": [_vec({"instance": "mq:9419"}, 4e9)],
            "rabbitmq_disk_space_available_bytes": [_vec({"instance": "mq:9419"}, 20e6)],
            "rabbitmq_disk_space_available_limit_bytes": [_vec({"instance": "mq:9419"}, 50e6)],
            "mongodb_up": [_vec({"instance": "mongo:9216"}, 0)],
            "mongodb_ss_mem_resident": [_vec({"instance": "mongo:9216"}, 3100)],
            "memcached_up": [_vec({"instance": "mc:9150"}, 1)],
            "memcached_current_bytes": [_vec({"instance": "mc:9150"}, 200e6)],
            "memcached_limit_bytes": [_vec({"instance": "mc:9150"}, 512e6)],
        }), servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}], metric_names=names)
        redis = next(x for x in cluster["middleware"]["items"] if x["id"] == "redis")
        self.assertIn("无上限", redis["result"])
        self.assertEqual(redis["level"], "ok")
        mysql = next(x for x in cluster["middleware"]["items"] if x["id"] == "mysql")
        self.assertEqual(mysql["level"], "warning")
        self.assertIn("缓冲池", mysql["result"])
        rabbit = next(x for x in cluster["middleware"]["items"] if x["id"] == "rabbitmq")
        self.assertEqual(rabbit["level"], "warning")
        self.assertIn("磁盘剩余", rabbit["result"])
        self.assertNotIn("磁盘 40%", rabbit["result"])
        mongo = next(x for x in cluster["middleware"]["items"] if x["id"] == "mongodb")
        self.assertEqual(mongo["level"], "critical")
        self.assertIn("RSS", mongo["result"])
        self.assertIn("3.1GB", mongo["result"])
        self.assertIsNone(mongo.get("mem_pct"))
        mc = next(x for x in cluster["middleware"]["items"] if x["id"] == "memcached_up")
        self.assertIn("内存", mc["result"])
        self.assertGreater(mc.get("mem_pct") or 0, 30)

    def test_middleware_rds_cloudwatch_cpu(self):
        from inspection.simulate_inspection import Prom

        cluster = collect_cluster_checks(Prom({
            "aws_rds_cpuutilization_average": [
                _vec({"dimension_DBInstanceIdentifier": "order-db"}, 91),
            ],
        }), servers=[{"instance": "10.0.0.1:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        rds = next(x for x in cluster["middleware"]["items"] if x["id"] == "rds_cloudwatch")
        self.assertEqual(rds["level"], "warning")
        self.assertTrue(any("RDS" in f for f in cluster["findings"]))

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
        score, _, reasons = compute_health_score(
            [], [], [{"instance": "10.0.0.1:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}],
            [], cluster=cluster,
        )
        self.assertEqual(score, 90.0)
        self.assertTrue(any("工作负载" in r for r in reasons))

    def test_app_namespace_listed_without_whitelist(self):
        from inspection.simulate_inspection import Prom

        cluster = collect_cluster_checks(Prom({
            "kube_pod_status_phase": [
                _vec({"namespace": "order-system", "pod": "order-api-0", "phase": "Running"}, 1),
            ],
            "kube_deployment_spec_replicas": [
                _vec({"namespace": "order-system", "deployment": "order-api"}, 1),
            ],
            "kube_deployment_status_replicas_ready": [
                _vec({"namespace": "order-system", "deployment": "order-api"}, 1),
            ],
        }), servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        names = [g["name"] for g in cluster["workloads"]["groups"]]
        self.assertIn("order-api", names)
        self.assertEqual(cluster["workloads"]["groups"][0]["namespace"], "order-system")

    def test_middleware_discovers_by_metric_names(self):
        from inspection.simulate_inspection import Prom

        names = ["nats_up", "memcached_up", "node_network_up", "kube_pod_status_phase"]
        cluster = collect_cluster_checks(Prom({
            "nats_up": [_vec({"instance": "nats-0:7777"}, 1)],
            "memcached_up": [_vec({"instance": "mc-0:9150"}, 0)],
            "node_network_up": [_vec({"device": "eth0"}, 1)],
        }), servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}], metric_names=names)
        ids = [x["id"] for x in cluster["middleware"]["items"]]
        self.assertIn("nats", ids)
        self.assertIn("memcached_up", ids)
        self.assertNotIn("redis", ids)
        self.assertFalse(any("network" in i for i in ids))
        mc = next(x for x in cluster["middleware"]["items"] if x["id"] == "memcached_up")
        self.assertEqual(mc["level"], "critical")
        self.assertEqual(cluster["middleware"]["discovered_names"], 4)
        self.assertTrue(cluster["discovery"]["scanned"])

    def test_elasticsearch_up_not_listed_as_middleware(self):
        from inspection.simulate_inspection import Prom

        names = ["elasticsearch_cluster_health_up", "elasticsearch_node_stats_up", "redis_up"]
        cluster = collect_cluster_checks(Prom({
            "elasticsearch_cluster_health_up": [_vec({"cluster": "es-cluster"}, 1)],
            "elasticsearch_node_stats_up": [_vec({"cluster": "es-cluster"}, 1)],
            "redis_up": [_vec({"instance": "redis:9121"}, 1)],
        }), servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}], metric_names=names)
        ids = [x["id"] for x in cluster["middleware"]["items"]]
        self.assertEqual(ids, ["redis"])
        self.assertFalse(any("elasticsearch" in i for i in ids))

    def test_uncovered_folded_last_lists_missing_recipes(self):
        from inspection.simulate_inspection import Prom

        cluster = collect_cluster_checks(Prom({
            "redis_up": [_vec({"instance": "r:9121"}, 1)],
        }), servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}], metric_names=["redis_up"])
        self.assertEqual(cluster["checks"][-1]["id"], "uncovered")
        self.assertEqual(cluster["checks"][-1]["level"], "skip")
        self.assertFalse(any(c["level"] == "skip" and c["id"] != "uncovered" for c in cluster["checks"]))
        text = cluster["checks"][-1]["result"]
        self.assertIn("PostgreSQL", text)
        self.assertIn("Kafka", text)
        self.assertNotIn("Redis / ElastiCache", text)

    def test_certs_jobs_hpa_when_metrics_present(self):
        import time
        from inspection.simulate_inspection import Prom

        soon = time.time() + 5 * 86400
        names = [
            "kube_job_status_failed",
            "kube_horizontalpodautoscaler_spec_max_replicas",
            "kube_horizontalpodautoscaler_status_desired_replicas",
            "certmanager_certificate_expiration_timestamp_seconds",
        ]
        cluster = collect_cluster_checks(Prom({
            "kube_job_status_failed": [
                _vec({"namespace": "app", "job_name": "migrate"}, 1),
            ],
            "kube_horizontalpodautoscaler_spec_max_replicas": [
                _vec({"namespace": "app", "horizontalpodautoscaler": "api"}, 4),
            ],
            "kube_horizontalpodautoscaler_status_desired_replicas": [
                _vec({"namespace": "app", "horizontalpodautoscaler": "api"}, 4),
            ],
            "certmanager_certificate_expiration_timestamp_seconds": [
                _vec({"namespace": "app", "name": "web-tls"}, soon),
            ],
        }), servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}], metric_names=names)
        by_id = {c["id"]: c for c in cluster["checks"]}
        self.assertEqual(by_id["jobs"]["level"], "warning")
        self.assertEqual(by_id["hpa"]["level"], "warning")
        self.assertEqual(by_id["certs"]["level"], "warning")
        self.assertTrue(any("失败 Job" in f for f in cluster["findings"]))
        self.assertTrue(any("HPA" in f for f in cluster["findings"]))
        self.assertTrue(any("证书" in f for f in cluster["findings"]))

    def test_old_cronjob_failures_are_ignored(self):
        import time
        from inspection.simulate_inspection import Prom

        now = time.time()
        old = now - 3 * 86400
        recent = now - 3600
        names = ["kube_job_status_failed", "kube_job_status_start_time", "kube_job_owner"]
        cluster = collect_cluster_checks(Prom({
            "kube_job_status_failed": [
                _vec({"namespace": "middleware-system", "job_name": "jaeger-es-rollover-1"}, 1),
                _vec({"namespace": "middleware-system", "job_name": "argo-watcher-1"}, 1),
                _vec({"namespace": "app", "job_name": "migrate-now"}, 1),
            ],
            "kube_job_status_start_time": [
                _vec({"namespace": "middleware-system", "job_name": "jaeger-es-rollover-1"}, old),
                _vec({"namespace": "middleware-system", "job_name": "argo-watcher-1"}, recent),
                _vec({"namespace": "app", "job_name": "migrate-now"}, old),
            ],
            "kube_job_owner": [
                _vec({"namespace": "middleware-system", "job_name": "jaeger-es-rollover-1", "owner_kind": "CronJob"}, 1),
                _vec({"namespace": "middleware-system", "job_name": "argo-watcher-1", "owner_kind": "CronJob"}, 1),
                _vec({"namespace": "app", "job_name": "migrate-now", "owner_kind": "Job"}, 1),
            ],
        }), servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}], metric_names=names)
        jobs = next(c for c in cluster["checks"] if c["id"] == "jobs")
        self.assertEqual(jobs["level"], "warning")
        self.assertIn("忽略 CronJob 历史 1", jobs["result"])
        self.assertTrue(any("argo-watcher-1" in x for x in jobs["detail"]))
        self.assertFalse(any("jaeger-es-rollover-1" in x for x in jobs["detail"]))
        self.assertTrue(any("migrate-now" in x for x in jobs["detail"]))
        self.assertEqual(len([f for f in cluster["findings"] if "失败 Job" in f]), 1)

    def test_stale_hostdown_listed_as_decommissioned(self):
        from inspection.simulate_inspection import Prom

        firing = [
            {"name": "HostDown", "severity": "critical", "instance": "10.10.60.232:9100"},
            {"name": "HostDown", "severity": "critical", "instance": "10.0.1.1:9100"},
            {"name": "KubeNodeNotReady", "severity": "critical", "instance": "n1"},
        ]
        down = [
            {"job": "node-exporter", "instance": "10.10.96.64:9100"},
            {"job": "node-exporter", "instance": "10.0.1.1:9100"},
        ]
        cluster = collect_cluster_checks(Prom({
            "kube_node_status_addresses": [
                _vec({"node": "n1", "address_type": "InternalIP", "address": "10.0.1.1"}, 1),
            ],
            "kube_node_status_condition": [_vec({"node": "n1", "condition": "Ready"}, 1)],
            'kube_node_status_condition{condition="Ready",status="true"}': [_vec({"node": "n1"}, 1)],
        }), firing_alerts=firing, down_targets=down, servers=[{"instance": "10.0.1.1:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        names = [a["name"] + ":" + (a.get("instance") or "") for a in cluster["firing_alerts"]]
        self.assertIn("HostDown:10.0.1.1:9100", names)
        self.assertIn("KubeNodeNotReady:n1", names)
        self.assertFalse(any("10.10.60.232" in n for n in names))
        downs = [t["instance"] for t in cluster["down_targets"]]
        self.assertEqual(downs, ["10.0.1.1:9100"])
        leftover = cluster["decommissioned"]
        self.assertTrue(any("10.10.60.232" in (x.get("instance") or "") for x in leftover))
        self.assertTrue(any("10.10.96.64" in (x.get("instance") or "") for x in leftover))
        self.assertFalse(any("10.0.1.1" in (x.get("instance") or "") for x in leftover))
        stale = next(c for c in cluster["checks"] if c["id"] == "decommissioned")
        self.assertEqual(stale["level"], "info")
        self.assertTrue(any("10.10.60.232" in x for x in stale["detail"]))
        self.assertFalse(any("已下线" in (f or "") for f in cluster["findings"]))
        score, _, reasons = compute_health_score(
            cluster["down_targets"], cluster["firing_alerts"],
            [{"instance": "10.0.1.1:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}],
            [], cluster=cluster,
        )
        self.assertFalse(any("10.10.60.232" in r or "10.10.96.64" in r for r in reasons))
        self.assertGreaterEqual(score, 70)

    def test_old_failed_pods_are_ignored(self):
        import time
        from inspection.simulate_inspection import Prom

        now = time.time()
        old = now - 3 * 86400
        recent = now - 3600
        abn_q = 'kube_pod_status_phase{phase=~"Pending|Failed|Unknown"}'
        cluster = collect_cluster_checks(Prom({
            "kube_pod_status_phase": [_vec({"namespace": "app", "pod": "keep"}, 1)],
            abn_q: [
                _vec({"namespace": "app", "pod": "old-fail", "phase": "Failed"}, 1),
                _vec({"namespace": "app", "pod": "new-fail", "phase": "Failed"}, 1),
                _vec({"namespace": "app", "pod": "pending-now", "phase": "Pending"}, 1),
            ],
            f"{abn_q} == 1": [
                _vec({"namespace": "app", "pod": "old-fail", "phase": "Failed"}, 1),
                _vec({"namespace": "app", "pod": "new-fail", "phase": "Failed"}, 1),
                _vec({"namespace": "app", "pod": "pending-now", "phase": "Pending"}, 1),
            ],
            "kube_pod_created": [
                _vec({"namespace": "app", "pod": "old-fail"}, old),
                _vec({"namespace": "app", "pod": "new-fail"}, recent),
                _vec({"namespace": "app", "pod": "pending-now"}, recent),
            ],
        }), servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        pods = next(c for c in cluster["checks"] if c["id"] == "pods")
        self.assertEqual(pods["level"], "warning")
        self.assertIn("忽略 Failed 历史 1", pods["result"])
        blob = " ".join(pods["detail"] or [])
        self.assertIn("new-fail", blob)
        self.assertIn("pending-now", blob)
        self.assertNotIn("old-fail", blob)
        self.assertTrue(any("-" in x and ":" in x for x in (pods["detail"] or []) if "new-fail" in x))

    def test_inactive_phase_series_are_not_abnormal(self):
        from inspection.simulate_inspection import Prom

        abn_q = 'kube_pod_status_phase{phase=~"Pending|Failed|Unknown"}'
        cluster = collect_cluster_checks(Prom({
            "kube_pod_status_phase": [_vec({"namespace": "app", "pod": "running", "phase": "Running"}, 1)],
            abn_q: [
                _vec({"namespace": "app", "pod": "running", "phase": "Pending"}, 0),
                _vec({"namespace": "app", "pod": "running", "phase": "Failed"}, 0),
                _vec({"namespace": "app", "pod": "running", "phase": "Unknown"}, 0),
            ],
        }), servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        pods = next(c for c in cluster["checks"] if c["id"] == "pods")
        self.assertEqual(pods["level"], "ok")
        self.assertTrue(str(pods["result"]).startswith("0"))
        self.assertFalse(any("异常 Pod" in (f or "") for f in cluster["findings"]))

    def test_previous_down_is_leftover_without_hosts(self):
        from inspection.simulate_inspection import Prom

        down = [
            {"job": "mongodb-exporter", "instance": "192.168.12.103:9216", "last_scrape": "2026-08-01T00:00:00Z"},
        ]
        cluster = collect_cluster_checks(
            Prom({}),
            firing_alerts=[],
            down_targets=down,
            servers=[],
            previous_leftover_keys=["mongodb-exporter|192.168.12.103:9216"],
            previous_times={"mongodb-exporter|192.168.12.103:9216": "2026-08-01T00:00:00Z"},
        )
        self.assertEqual(cluster["down_targets"], [])
        leftover = cluster["decommissioned"]
        self.assertTrue(any("192.168.12.103:9216" in (x.get("instance") or "") for x in leftover))
        mongo = next(x for x in leftover if "192.168.12.103" in (x.get("instance") or ""))
        self.assertTrue(mongo.get("when"))

    def test_manual_ignore_skips_whole_abnormal_check(self):
        from inspection.simulate_inspection import Prom

        now = __import__("time").time()
        abn_q = 'kube_pod_status_phase{phase=~"Pending|Failed|Unknown"}'
        cluster = collect_cluster_checks(
            Prom({
                "kube_pod_status_phase": [_vec({"namespace": "app", "pod": "keep"}, 1)],
                abn_q: [
                    _vec({"namespace": "app", "pod": "noise", "phase": "Pending"}, 1),
                ],
                f"{abn_q} == 1": [
                    _vec({"namespace": "app", "pod": "noise", "phase": "Pending"}, 1),
                ],
                "kube_pod_created": [
                    _vec({"namespace": "app", "pod": "noise"}, now - 600),
                ],
                "kube_node_status_addresses": [
                    _vec({"node": "n1", "address_type": "InternalIP", "address": "10.0.1.1"}, 1),
                ],
            }),
            firing_alerts=[{"name": "HostDown", "instance": "10.0.1.1:9100", "job": "node-exporter"}],
            down_targets=[{"job": "kube-state-metrics", "instance": "10.0.1.1:8080"}],
            servers=[{"instance": "10.0.1.1:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}],
            ignore_keys=["check:pods", "check:prom_targets", "check:prom_alerts"],
        )
        pods = next(c for c in cluster["checks"] if c["id"] == "pods")
        self.assertEqual(pods["level"], "ok")
        self.assertEqual(pods["result"], "已忽略")
        self.assertEqual(cluster["down_targets"], [])
        self.assertEqual(cluster["firing_alerts"], [])

    def test_manual_ignore_skips_one_detail_item(self):
        from inspection.simulate_inspection import Prom

        now = __import__("time").time()
        abn_q = 'kube_pod_status_phase{phase=~"Pending|Failed|Unknown"}'
        cluster = collect_cluster_checks(
            Prom({
                "kube_pod_status_phase": [_vec({"namespace": "app", "pod": "keep"}, 1)],
                abn_q: [
                    _vec({"namespace": "app", "pod": "noise", "phase": "Pending"}, 1),
                    _vec({"namespace": "app", "pod": "keep-fail", "phase": "Failed"}, 1),
                ],
                f"{abn_q} == 1": [
                    _vec({"namespace": "app", "pod": "noise", "phase": "Pending"}, 1),
                    _vec({"namespace": "app", "pod": "keep-fail", "phase": "Failed"}, 1),
                ],
                "kube_pod_created": [
                    _vec({"namespace": "app", "pod": "noise"}, now - 600),
                    _vec({"namespace": "app", "pod": "keep-fail"}, now - 600),
                ],
            }),
            servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}],
            ignore_keys=["pod:app/noise"],
        )
        pods = next(c for c in cluster["checks"] if c["id"] == "pods")
        blob = " ".join(pods["detail"] or [])
        self.assertNotIn("noise", blob)
        self.assertIn("keep-fail", blob)
        self.assertEqual(pods["level"], "warning")

    def test_dead_machine_exporters_are_leftover(self):
        from inspection.simulate_inspection import Prom

        down = [
            {"job": "kubernetes-nodes", "instance": "test-k8s-worker-16", "last_scrape": "2026-09-16T05:01:00Z"},
            {"job": "mongodb-exporter", "instance": "192.168.12.103:9216", "last_scrape": "2026-09-16T05:02:00Z"},
            {"job": "kube-state-metrics", "instance": "172.20.144.10:8080"},
        ]
        cluster = collect_cluster_checks(Prom({
            "kube_node_status_addresses": [
                _vec({"node": "test-k8s-worker-04", "address_type": "InternalIP", "address": "192.168.12.188"}, 1),
            ],
        }), firing_alerts=[], down_targets=down, servers=[], previous_leftover_keys=[
            "mongodb-exporter|192.168.12.103:9216",
        ])
        kept = [f"{t.get('job')}:{t.get('instance')}" for t in cluster["down_targets"]]
        self.assertEqual(kept, ["kube-state-metrics:172.20.144.10:8080"])
        leftover = cluster["decommissioned"]
        self.assertTrue(any("test-k8s-worker-16" in (x.get("instance") or "") for x in leftover))
        self.assertTrue(any("192.168.12.103:9216" in (x.get("instance") or "") for x in leftover))
        mongo = next(x for x in leftover if "192.168.12.103" in (x.get("instance") or ""))
        self.assertTrue(mongo.get("persistent"))
        self.assertTrue(mongo.get("when"))
        self.assertTrue(any("192.168.12.103" in (n or "") for n in cluster["known_normals"]))

    def test_zero_replica_is_record_not_finding(self):
        from inspection.simulate_inspection import Prom

        cluster = collect_cluster_checks(Prom({
            "kube_deployment_spec_replicas": [
                _vec({"namespace": "app", "deployment": "scaled-down"}, 0),
                _vec({"namespace": "app", "deployment": "api"}, 2),
            ],
        }), servers=[{"instance": "w:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}])
        replicas = next(c for c in cluster["checks"] if c["id"] == "replicas")
        self.assertEqual(replicas["level"], "info")
        self.assertTrue(any("scaled-down" in x for x in replicas["detail"]))
        self.assertFalse(any("零副本" in (f or "") for f in cluster["findings"]))

    def test_score_caps_many_down_targets(self):
        downs = [{"job": "node-exporter", "instance": f"10.0.0.{i}:9100"} for i in range(10)]
        score, _, reasons = compute_health_score(
            downs, [],
            [{"instance": "n:9100", "mem_pct": 20, "cpu_pct": 10, "disk_pct": 10}],
            [],
        )
        self.assertGreaterEqual(score, 76)
        self.assertLess(score, 100)
        self.assertTrue(any("Down Targets (10): -24" in r for r in reasons))

    def test_server_label_uses_node_name_not_ip(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import label_servers

        servers = [
            {"instance": "10.0.1.1:9100", "cpu_pct": 10},
            {"instance": "jumpserver-0:9100", "cpu_pct": 10},
        ]
        labeled = label_servers(Prom({
            "kube_node_status_addresses": [
                _vec({"node": "test-k8s-worker-04", "address_type": "InternalIP", "address": "10.0.1.1"}, 1),
            ],
        }), servers)
        self.assertEqual(labeled[0]["service"], "test-k8s-worker-04")
        self.assertEqual(labeled[0]["kind"], "k8s")
        self.assertEqual(labeled[0]["ip"], "10.0.1.1")
        self.assertEqual(labeled[1]["service"], "JumpServer")
        self.assertEqual(labeled[1]["kind"], "host")
        self.assertEqual(labeled[1]["role"], "JumpServer")

    def test_eks_identity_from_kube_metrics(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import label_servers

        labeled = label_servers(Prom({
            "kube_node_status_addresses": [
                _vec({"node": "ip-10-0-1-23.ec2.internal", "address_type": "InternalIP", "address": "10.0.1.23"}, 1),
            ],
            "kube_node_info": [
                _vec({"node": "ip-10-0-1-23.ec2.internal", "provider_id": "aws:///us-east-1a/i-0abc123"}, 1),
            ],
            "kube_node_labels": [
                _vec({
                    "node": "ip-10-0-1-23.ec2.internal",
                    "label_eks_amazonaws_com_nodegroup": "ng-workers",
                    "label_node_kubernetes_io_instance_type": "m5.xlarge",
                }, 1),
            ],
        }), [{"instance": "10.0.1.23:9100", "cpu_pct": 10}])
        row = labeled[0]
        self.assertEqual(row["kind"], "k8s")
        self.assertEqual(row["cloud"], "aws")
        self.assertEqual(row["instance_id"], "i-0abc123")
        self.assertEqual(row["nodegroup"], "ng-workers")
        self.assertEqual(row["role"], "ng-workers")
        self.assertEqual(row["node_name"], "ip-10-0-1-23.ec2.internal")
        self.assertEqual(row["ip"], "10.0.1.23")

    def test_eks_from_ec2_internal_hostname(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import label_servers

        labeled = label_servers(Prom({
            "kube_node_status_addresses": [
                _vec({"node": "ip-10-0-2-9.ec2.internal", "address_type": "InternalIP", "address": "10.0.2.9"}, 1),
            ],
        }), [{"instance": "10.0.2.9:9100", "cpu_pct": 10}])
        row = labeled[0]
        self.assertEqual(row["kind"], "k8s")
        self.assertEqual(row["cloud"], "aws")
        self.assertEqual(row["role"], "EKS 节点")
        self.assertEqual(row["node_name"], "ip-10-0-2-9.ec2.internal")

    def test_uname_hostname_not_ip_as_machine_name(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import label_servers

        labeled = label_servers(Prom({
            "node_uname_info": [
                _vec({"instance": "192.168.12.188:9100", "nodename": "test-k8s-worker-04"}, 1),
                _vec({"instance": "192.168.12.8:9100", "nodename": "dev-mysql-01"}, 1),
                _vec({"instance": "192.168.12.32:9100", "nodename": "jumpserver-0"}, 1),
            ],
        }), [
            {"instance": "192.168.12.188:9100", "cpu_pct": 10},
            {"instance": "192.168.12.8:9100", "cpu_pct": 10},
            {"instance": "192.168.12.32:9100", "cpu_pct": 10},
        ])
        worker, mysql, jms = labeled
        self.assertEqual(worker["node_name"], "test-k8s-worker-04")
        self.assertEqual(worker["ip"], "192.168.12.188")
        self.assertEqual(worker["kind"], "k8s")
        self.assertEqual(worker["role"], "K8s worker")
        self.assertEqual(mysql["node_name"], "dev-mysql-01")
        self.assertEqual(mysql["ip"], "192.168.12.8")
        self.assertEqual(mysql["kind"], "host")
        self.assertEqual(mysql["role"], "独立主机")
        self.assertEqual(jms["role"], "JumpServer")
        self.assertEqual(jms["kind"], "host")
        self.assertEqual(jms["node_name"], "jumpserver-0")

    def test_kube_uses_type_label_not_address_type(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import label_servers

        labeled = label_servers(Prom({
            "kube_node_status_addresses": [
                _vec({"node": "test-k8s-control-plane-01", "type": "ExternalIP", "address": "1.2.3.4"}, 1),
                _vec({"node": "test-k8s-control-plane-01", "type": "InternalIP", "address": "192.168.12.188"}, 1),
                _vec({"node": "test-k8s-control-plane-01", "type": "Hostname", "address": "test-k8s-control-plane-01"}, 1),
            ],
        }), [{"instance": "192.168.12.188:9100", "cpu_pct": 10}])
        row = labeled[0]
        self.assertEqual(row["node_name"], "test-k8s-control-plane-01")
        self.assertEqual(row["ip"], "192.168.12.188")
        self.assertEqual(row["kind"], "k8s")
        self.assertEqual(row["role"], "K8s 控制面")

    def test_hostname_from_node_exporter_node_label(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import label_servers

        labeled = label_servers(Prom({
            "count by (instance, nodename, node) (node_load1)": [
                _vec({"instance": "192.168.12.8:9100", "node": "test-k8s-worker-02"}, 1),
            ],
        }), [{"instance": "192.168.12.8:9100", "cpu_pct": 10}])
        row = labeled[0]
        self.assertEqual(row["node_name"], "test-k8s-worker-02")
        self.assertEqual(row["ip"], "192.168.12.8")
        self.assertEqual(row["kind"], "k8s")
        self.assertEqual(row["role"], "K8s worker")

    def test_hostname_from_prometheus_targets(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import label_servers

        targets = [{
            "labels": {"instance": "192.168.12.188:9100", "job": "node-exporter", "node": "test-k8s-control-plane-01"},
            "discoveredLabels": {"__meta_kubernetes_pod_node_name": "test-k8s-control-plane-01"},
        }]
        labeled = label_servers(Prom({}), [{"instance": "192.168.12.188:9100", "cpu_pct": 10}], targets=targets)
        row = labeled[0]
        self.assertEqual(row["node_name"], "test-k8s-control-plane-01")
        self.assertEqual(row["ip"], "192.168.12.188")
        self.assertEqual(row["kind"], "k8s")
        self.assertEqual(row["role"], "K8s 控制面")

    def test_servers_sort_attention_then_name_hypervisors_last(self):
        from inspection.cluster_checks import sort_servers

        rows = [
            {"node_name": "test-es-03", "kind": "host", "level": "ok", "ip": "192.168.12.33"},
            {"node_name": "ORACLE-SERVER-XG-2L", "kind": "host", "level": "ok", "ip": "192.168.12.188"},
            {"node_name": "test-es-01", "kind": "host", "level": "ok", "ip": "192.168.12.80"},
            {"node_name": "HITACHI-HA-8000V", "kind": "host", "level": "ok"},
            {"node_name": "test-es-02", "kind": "host", "level": "ok", "ip": "192.168.12.10"},
            {"node_name": "Gen10", "kind": "host", "level": "ok"},
            {"node_name": "test-k8s-worker-04", "kind": "k8s", "level": "ok"},
            {"node_name": "jumpserver-0", "kind": "host", "level": "warning"},
        ]
        sort_servers(rows)
        self.assertEqual([r["node_name"] for r in rows], [
            "jumpserver-0",
            "test-es-01",
            "test-es-02",
            "test-es-03",
            "test-k8s-worker-04",
            "Gen10",
            "HITACHI-HA-8000V",
            "ORACLE-SERVER-XG-2L",
        ])

    def test_eks_from_uname_without_kube_state(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import label_servers

        labeled = label_servers(Prom({
            "node_uname_info": [
                _vec({"instance": "10.0.3.9:9100", "nodename": "ip-10-0-3-9.ec2.internal"}, 1),
            ],
        }), [{"instance": "10.0.3.9:9100", "cpu_pct": 10}])
        row = labeled[0]
        self.assertEqual(row["kind"], "k8s")
        self.assertEqual(row["cloud"], "aws")
        self.assertEqual(row["role"], "EKS 节点")
        self.assertEqual(row["node_name"], "ip-10-0-3-9.ec2.internal")
        self.assertEqual(row["ip"], "10.0.3.9")

    def test_jumpserver_hostdown_stays_a_real_finding(self):
        from inspection.simulate_inspection import Prom

        firing = [
            {"name": "HostDown", "severity": "critical", "instance": "jumpserver-0:9100", "job": "node-exporter"},
            {"name": "HostDown", "severity": "critical", "instance": "10.10.60.232:9100", "job": "node-exporter"},
        ]
        cluster = collect_cluster_checks(Prom({
            "kube_node_status_addresses": [
                _vec({"node": "n1", "address_type": "InternalIP", "address": "10.0.1.1"}, 1),
            ],
        }), firing_alerts=firing, down_targets=[], servers=[])
        names = [a.get("instance") for a in cluster["firing_alerts"]]
        self.assertIn("jumpserver-0:9100", names)
        self.assertNotIn("10.10.60.232:9100", names)
        leftover = [x.get("instance") for x in cluster["decommissioned"]]
        self.assertIn("10.10.60.232:9100", leftover)
        self.assertNotIn("jumpserver-0:9100", leftover)

    def test_server_delta_24h_from_offset_samples(self):
        from inspection.cluster_checks import attach_server_deltas

        servers = [{"instance": "n:9100", "disk_pct": 70, "mem_pct": 40}]
        attach_server_deltas(
            servers,
            [_vec({"instance": "n:9100"}, 32)],
            [_vec({"instance": "n:9100"}, 55)],
        )
        self.assertEqual(servers[0]["mem_delta_24h"], 8.0)
        self.assertEqual(servers[0]["disk_delta_24h"], 15.0)

    def test_pvc_and_node_24h_rise_is_a_finding(self):
        from inspection.simulate_inspection import Prom
        from inspection.cluster_checks import collect_pvc_usage

        pvc = collect_pvc_usage(Prom({
            "pvc_stats_used_bytes": [
                _vec({"namespace": "app", "persistentvolumeclaim": "order-data"}, 80),
            ],
            "pvc_stats_capacity_bytes": [
                _vec({"namespace": "app", "persistentvolumeclaim": "order-data"}, 100),
            ],
            "pvc_stats_used_bytes offset 24h": [
                _vec({"namespace": "app", "persistentvolumeclaim": "order-data"}, 50),
            ],
            "pvc_stats_capacity_bytes offset 24h": [
                _vec({"namespace": "app", "persistentvolumeclaim": "order-data"}, 100),
            ],
        }))
        self.assertEqual(pvc["items"][0]["delta_24h"], 30.0)

        cluster = collect_cluster_checks(Prom({
            "pvc_stats_used_bytes": [
                _vec({"namespace": "app", "persistentvolumeclaim": "order-data"}, 80),
            ],
            "pvc_stats_capacity_bytes": [
                _vec({"namespace": "app", "persistentvolumeclaim": "order-data"}, 100),
            ],
            "pvc_stats_used_bytes offset 24h": [
                _vec({"namespace": "app", "persistentvolumeclaim": "order-data"}, 50),
            ],
            "pvc_stats_capacity_bytes offset 24h": [
                _vec({"namespace": "app", "persistentvolumeclaim": "order-data"}, 100),
            ],
        }), servers=[{
            "instance": "n:9100", "cpu_pct": 10, "mem_pct": 20, "disk_pct": 61,
            "disk_delta_24h": 12, "node_name": "test-k8s-worker-04",
        }])
        trend = next(c for c in cluster["checks"] if c["id"] == "resource_trend")
        self.assertEqual(trend["level"], "warning")
        blob = " ".join(cluster["findings"])
        self.assertIn("磁盘", blob)
        self.assertIn("PVC", blob)
        self.assertFalse(any("撮合" in f for f in cluster["findings"]))


if __name__ == "__main__":
    unittest.main()
