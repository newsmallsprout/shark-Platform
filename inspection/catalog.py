"""业务服务别名与已知常态。

巡检清单按「服务名」展示，而不是只显示 PVC / instance / IP。
匹配规则是子串，大小写不敏感。
"""

# usage_alert=False：用量高不记入「发现问题」（脚本里的已知常态）
SERVICE_ALIASES = [
    {
        "id": "match_engine",
        "service": "撮合引擎",
        "match_pvc": ["exchange-match-engine", "match-engine", "exchange-match"],
        "match_ns": [],
        "match_instance": ["match-engine", "exchange-match"],
        "baseline": "以 Prom 用量表为准（现网可能很低）",
        "usage_alert": False,
    },
    {
        "id": "elasticsearch",
        "service": "Elasticsearch",
        "match_pvc": ["elasticsearch", "es-data", "es-master"],
        "match_ns": [],
        "match_instance": ["elasticsearch", "-es-"],
        "baseline": "堆内存约 82% 为已知常态",
        "usage_alert": True,
        "mem_alert_threshold": 95,
    },
    {
        "id": "jumpserver",
        "service": "JumpServer",
        "match_pvc": ["jumpserver", "jms"],
        "match_ns": [],
        "match_instance": ["jumpserver", "jms"],
        "baseline": "内存 80%+ 为已知常态",
        "usage_alert": True,
        "mem_alert_threshold": 95,
    },
    {
        "id": "traefik",
        "service": "Traefik",
        "match_pvc": ["traefik"],
        "match_ns": ["traefik-system"],
        "match_instance": ["traefik"],
        "baseline": "accesslog 无轮转，关注 /data/traefik/logs",
        "usage_alert": True,
    },
    {
        "id": "flink",
        "service": "Flink Job",
        "match_pvc": ["flink"],
        "match_ns": ["flink-system"],
        "match_instance": ["flink"],
        "baseline": "",
        "usage_alert": True,
    },
]

KNOWN_NORMALS = [
    "JumpServer 内存 80%+ 为已知常态",
    "Elasticsearch 内存约 82% 为已知常态",
    "撮合引擎 PVC 看用量表，不以「占用高」预设",
    "Traefik accesslog 无轮转，看 /data/traefik/logs",
]

PVC_WARN_PCT = 85
PVC_CRIT_PCT = 95

# CronJob 失败记录会长期留在 kube-state-metrics 里。超过这个窗口的历史失败不进发现问题。
JOB_FAIL_LOOKBACK_SEC = 24 * 3600

# node-exporter 已从集群摘掉但仍留在 Prometheus 抓取列表里，HostDown 会一直响。
# 这类进「已下线残留」，不进发现问题、不扣分，避免忘记摘 scrape。
STALE_HOSTDOWN_NAMES = ("hostdown", "instancedown", "nodedown")

# 系统命名空间默认不进工作负载表（异常 Pod 仍会抬出来）。别名只是展示名，不是白名单。
HIDE_NAMESPACES = ("kube-system", "kube-public", "kube-node-lease")

# 指标族：先扫 Prom 里实际有的名字，对上前缀才检查。不是写死实例清单。
METRIC_FAMILY_RECIPES = [
    {
        "id": "redis",
        "name": "Redis / ElastiCache",
        "source": "redis-exporter",
        "prefixes": ["redis_"],
        "up": "redis_up",
        "mem_used": "redis_memory_used_bytes",
        "mem_max": "redis_memory_max_bytes",
        "resources": [
            {"kind": "mem", "mode": "ratio", "used": "redis_memory_used_bytes", "max": "redis_memory_max_bytes", "label": "内存"},
        ],
    },
    {
        "id": "mysql",
        "name": "MySQL / RDS",
        "source": "mysqld-exporter",
        "prefixes": ["mysql_", "mysqld_"],
        "up": "mysql_up",
        "resources": [
            {
                "kind": "mem", "mode": "ratio", "label": "缓冲池",
                "used": "mysql_global_status_innodb_buffer_pool_bytes_data",
                "max": "mysql_global_variables_innodb_buffer_pool_size",
            },
            {
                "kind": "mem", "mode": "ratio", "label": "缓冲池",
                "used": "mysql_global_status_innodb_buffer_pool_pages_data",
                "max": "mysql_global_status_innodb_buffer_pool_pages_total",
            },
        ],
    },
    {
        "id": "postgres",
        "name": "PostgreSQL / RDS",
        "source": "postgres-exporter",
        "prefixes": ["pg_"],
        "up": "pg_up",
    },
    {
        "id": "mongodb",
        "name": "MongoDB",
        "source": "mongodb-exporter",
        "prefixes": ["mongodb_"],
        "up": "mongodb_up",
        "resources": [
            {
                "kind": "mem", "mode": "ratio", "label": "WT缓存",
                "used": "mongodb_ss_wt_cache_bytes_currently_in_cache",
                "max": "mongodb_ss_wt_cache_maximum_bytes_configured",
            },
            {
                "kind": "mem", "mode": "ratio", "label": "WT缓存",
                "used": "mongodb_mongod_wiredtiger_cache_bytes_currently_in_the_cache",
                "max": "mongodb_mongod_wiredtiger_cache_maximum_bytes_configured",
            },
            {"kind": "mem", "mode": "used", "used": "mongodb_ss_mem_resident", "label": "RSS", "unit": "mb"},
        ],
    },
    {
        "id": "rabbitmq",
        "name": "RabbitMQ / Amazon MQ",
        "source": "rabbitmq-exporter",
        "prefixes": ["rabbitmq_"],
        "up": "rabbitmq_up",
        "resources": [
            {
                "kind": "mem", "mode": "ratio", "label": "内存",
                "used": "rabbitmq_process_resident_memory_bytes",
                "max": "rabbitmq_resident_memory_limit_bytes",
            },
            {
                "kind": "mem", "mode": "ratio", "label": "内存",
                "used": "rabbitmq_node_mem_used",
                "max": "rabbitmq_node_mem_limit",
            },
            {
                "kind": "disk", "mode": "free", "label": "磁盘剩余",
                "used": "rabbitmq_disk_space_available_bytes",
                "max": "rabbitmq_disk_space_available_limit_bytes",
            },
        ],
    },
    {
        "id": "kafka",
        "name": "Kafka",
        "source": "kafka-exporter",
        "prefixes": ["kafka_"],
        "up": "kafka_brokers",
        "resources": [
            {
                "kind": "mem", "mode": "ratio", "label": "JVM堆",
                "used": "kafka_jvm_memory_used_bytes",
                "max": "kafka_jvm_memory_max_bytes",
            },
        ],
    },
    {
        "id": "nats",
        "name": "NATS",
        "source": "nats-exporter",
        "prefixes": ["nats_"],
        "up": "nats_up",
    },
    {
        "id": "minio",
        "name": "MinIO",
        "source": "minio-exporter",
        "prefixes": ["minio_"],
        "up": "minio_cluster_health_status",
        "resources": [
            {
                "kind": "disk", "mode": "ratio", "label": "磁盘",
                "used": "minio_cluster_disk_used_bytes",
                "max": "minio_cluster_disk_total_bytes",
            },
            {
                "kind": "disk", "mode": "ratio", "label": "磁盘",
                "used": "minio_disk_storage_used_bytes",
                "max": "minio_disk_storage_total_bytes",
            },
            {
                "kind": "disk", "mode": "ratio", "label": "磁盘",
                "used": "minio_cluster_usage_total_bytes",
                "max": "minio_cluster_capacity_raw_total_bytes",
            },
        ],
    },
    {
        "id": "rds_cloudwatch",
        "name": "RDS (CloudWatch)",
        "source": "cloudwatch-exporter",
        "prefixes": ["aws_rds_"],
        "cpu": "aws_rds_cpuutilization_average",
        "cpu_warn": 80,
        "lag": "aws_rds_replica_lag_average",
        "lag_warn": 30,
    },
    {
        "id": "elasticache_cloudwatch",
        "name": "ElastiCache (CloudWatch)",
        "source": "cloudwatch-exporter",
        "prefixes": ["aws_elasticache_"],
        "cpu": "aws_elasticache_cpuutilization_average",
        "cpu_warn": 80,
        "mem_pct_metric": "aws_elasticache_databasememoryusagepercentage_average",
        "mem_warn": 80,
        "resources": [
            {
                "kind": "mem", "mode": "gauge_pct",
                "metric": "aws_elasticache_databasememoryusagepercentage_average",
                "label": "内存",
            },
        ],
    },
]

# 这些 *_up 是网卡/节点态，不是中间件 exporter
UP_METRIC_DENY = {
    "up",
    "probe_success",
    "node_network_up",
    "node_bonding_active",
    "node_network_carrier",
    "node_network_dormant",
    "node_network_iface_id",
    "node_network_iface_link",
    "node_network_iface_link_mode",
}


def hidden_namespace(ns):
    return (ns or "").lower() in HIDE_NAMESPACES


def watch_namespaces():
    """兼容旧调用：现在只表示「额外关心的 ns」，不再当白名单。"""
    ns = set()
    for alias in SERVICE_ALIASES:
        for item in alias.get("match_ns") or []:
            if item:
                ns.add(item.lower())
    return ns


def recipe_covers_metric(spec, metric_name):
    name = (metric_name or "").lower()
    for prefix in spec.get("prefixes") or []:
        if name.startswith(prefix.lower()):
            return True
    return False


def resolve_service(namespace="", name="", instance=""):
    ns = (namespace or "").lower()
    nm = (name or "").lower()
    inst = (instance or "").lower()
    for alias in SERVICE_ALIASES:
        for needle in alias.get("match_pvc") or []:
            n = needle.lower()
            if n and (n in nm or n in inst):
                return alias
        for needle in alias.get("match_ns") or []:
            n = needle.lower()
            if n and ns == n:
                return alias
        for needle in alias.get("match_instance") or []:
            n = needle.lower()
            if n and n in inst:
                return alias
    return None


def display_name(namespace="", name="", instance=""):
    alias = resolve_service(namespace=namespace, name=name, instance=instance)
    if alias:
        return alias["service"]
    if namespace and name:
        return f"{namespace}/{name}"
    return name or instance or "-"
