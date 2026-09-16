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
        self.assertGreaterEqual(score, 50)

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


if __name__ == "__main__":
    unittest.main()
