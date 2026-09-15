"""业务服务别名与已知常态。

巡检清单按「服务名」展示，而不是只显示 PVC / instance / IP。
匹配规则是子串，大小写不敏感。
"""

# usage_alert=False：用量高不记入「发现问题」（脚本里的已知常态）
SERVICE_ALIASES = [
    {
        "id": "match_engine",
        "service": "撮合引擎",
        "match_pvc": ["exchange-match-engine", "match-engine"],
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
