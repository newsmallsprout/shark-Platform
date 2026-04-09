"""
Django settings — AIOps Platform 中心控制面（Django + DRF + LangGraph + Celery + SSE）。
"""

from pathlib import Path
import os
import warnings

from shark_platform.db_config import get_default_database

warnings.filterwarnings("ignore", category=FutureWarning, module="google.auth")
warnings.filterwarnings("ignore", category=FutureWarning, module="google.oauth2")

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-6=1go(k#*p-)7rg)n6*th=wv1skh=3o4+^2^!m=56dro8j+3o1",
)

DEBUG = os.environ.get("DEBUG", "False") == "True"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost,http://127.0.0.1,http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173",
).split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "core",
    "api",
    "ai_ops",
    "observability",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "shark_platform.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "shark_platform.wsgi.application"

DATABASES = {"default": get_default_database(BASE_DIR)}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "frontend/dist/assets"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
WHITENOISE_MANIFEST_STRICT = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOW_ALL_ORIGINS = True

PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000")

AGENT_SSE_PUBLIC_BASE = os.environ.get(
    "AGENT_SSE_PUBLIC_BASE", "http://localhost:8010"
).rstrip("/")

WORK_ORDER_GATE_ENABLED = os.environ.get(
    "SHARK_WORK_ORDER_GATE_ENABLED", "false"
).lower() in ("1", "true", "yes")
WORK_ORDER_GATE_ALLOW_SUPERUSER = os.environ.get(
    "SHARK_WORK_ORDER_GATE_ALLOW_SUPERUSER", "true"
).lower() in ("1", "true", "yes")

# Edge probe / log collector shared secret (optional; empty disables token check)
SHARK_EDGE_TOKEN = os.environ.get("SHARK_EDGE_TOKEN", "").strip()

# Prometheus base URL for SRE tools / LangGraph (replaces legacy InspectionConfig)
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "").strip()

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

LOGIN_URL = "/login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login"

SESSION_COOKIE_AGE = 1800
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "aiops-platform",
    }
}

# 访问日志落库（observability）：单流最大事件数，超出删最旧
OBSERVABILITY_MAX_EVENTS_PER_STREAM = int(
    os.environ.get("OBSERVABILITY_MAX_EVENTS", "200000")
)
OBSERVABILITY_DISABLE_DETECTORS = os.environ.get(
    "OBSERVABILITY_DISABLE_DETECTORS", ""
).lower() in ("1", "true", "yes")
OBSERVABILITY_LLM_TIMEOUT_SEC = int(
    os.environ.get("OBSERVABILITY_LLM_TIMEOUT_SEC", "90")
)

# ClickHouse OLAP：off=不写不查 | mirror=双写，聚合仍走 PG | analytics=双写且 API 聚合优先走 CH
OBSERVABILITY_OLAP_MODE = os.environ.get(
    "OBSERVABILITY_OLAP_MODE", "off"
).strip().lower()
if OBSERVABILITY_OLAP_MODE not in ("off", "mirror", "analytics"):
    OBSERVABILITY_OLAP_MODE = "off"

CLICKHOUSE_HOST = (os.environ.get("CLICKHOUSE_HOST") or "").strip()
CLICKHOUSE_PORT = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.environ.get("CLICKHOUSE_DATABASE", "shark_obs")
# 原始行摘要（可选写入 CH，便于外部排查）
CLICKHOUSE_STORE_RAW_EXCERPT = os.environ.get(
    "CLICKHOUSE_STORE_RAW_EXCERPT", ""
).lower() in ("1", "true", "yes")

# GeoLite2 City：镜像 URL（.mmdb.gz），首次 ingest 或 manage.py download_geoip 时拉取；须遵守 MaxMind EULA
GEOIP_DATABASE_URL = (os.environ.get("GEOIP_DATABASE_URL") or "").strip()
GEOIP_DATABASE_PATH = (os.environ.get("GEOIP_DATABASE_PATH") or "").strip()

# L4 自愈：经验库匹配置信度 ≥ 此阈值时自动批准工单并下发 PlaybookJob
AIOPS_AUTO_HEAL_CONFIDENCE_THRESHOLD = float(
    os.environ.get("AIOPS_AUTO_HEAL_CONFIDENCE", "0.95")
)
AIOPS_DEFAULT_PLAYBOOK_NODE = os.environ.get("AIOPS_DEFAULT_PLAYBOOK_NODE", "default")

# 告警 Webhook 触发的 Celery 诊断是否落库工单（False 时仅更新 AnalysisReport / agent_trace）
AIOPS_AUTO_CREATE_TICKET_ON_ALERT = os.environ.get(
    "AIOPS_AUTO_CREATE_TICKET_ON_ALERT", "true"
).lower() in ("1", "true", "yes")

# Webhook 来源工单：是否在 draft 后自动提交待审批
AIOPS_ALERT_AUTO_SUBMIT_TICKET_PENDING = os.environ.get(
    "AIOPS_ALERT_AUTO_SUBMIT_TICKET_PENDING", "false"
).lower() in ("1", "true", "yes")

# 审批策略总开关（False 时跳过自动 submit / 自动批准逻辑）
AIOPS_APPROVAL_POLICY_ENABLED = os.environ.get(
    "AIOPS_APPROVAL_POLICY_ENABLED", "true"
).lower() in ("1", "true", "yes")

# 极低风险：severity=info 且模型 confidence=high 且无危险命令模式时 draft→approved
AIOPS_APPROVAL_AUTO_LOW_RISK = os.environ.get(
    "AIOPS_APPROVAL_AUTO_LOW_RISK", "false"
).lower() in ("1", "true", "yes")

# 出站通知（Slack/钉钉等 POST JSON；空则不发）
AIOPS_NOTIFY_WEBHOOK_URL = (os.environ.get("AIOPS_NOTIFY_WEBHOOK_URL") or "").strip()
AIOPS_NOTIFY_ON_RUN_START = os.environ.get(
    "AIOPS_NOTIFY_ON_RUN_START", "false"
).lower() in ("1", "true", "yes")
AIOPS_NOTIFY_ON_TICKET_EVENTS = os.environ.get(
    "AIOPS_NOTIFY_ON_TICKET_EVENTS", "true"
).lower() in ("1", "true", "yes")

# 多集群 Prometheus：JSON 映射，如 {"default":"https://prom/","prod-east":"https://pe/"}
AIOPS_PROMETHEUS_URL_BY_CLUSTER = (
    os.environ.get("AIOPS_PROMETHEUS_URL_BY_CLUSTER") or ""
).strip()

# 注入 Agent 软上下文的接入层日志 stream（空则取最近有数据的 LogStream）
AIOPS_OBSERVABILITY_STREAM_KEY_FOR_INCIDENTS = (
    os.environ.get("AIOPS_OBSERVABILITY_STREAM_KEY_FOR_INCIDENTS") or ""
).strip()

# 服务目录 JSON（列表或字典），注入模型 bootstrap
AIOPS_SERVICE_CATALOG_JSON = (os.environ.get("AIOPS_SERVICE_CATALOG_JSON") or "").strip()

# 工单执行成功后可选 PromQL 校验（空则跳过）
AIOPS_POST_EXEC_VERIFY_PROMQL = (os.environ.get("AIOPS_POST_EXEC_VERIFY_PROMQL") or "").strip()

# Webhook 鉴权：任选其一配置；未配置则不校验该项
AIOPS_WEBHOOK_BEARER_TOKEN = (os.environ.get("AIOPS_WEBHOOK_BEARER_TOKEN") or "").strip()
AIOPS_WEBHOOK_HMAC_SECRET = (os.environ.get("AIOPS_WEBHOOK_HMAC_SECRET") or "").strip()

# 运维 API：为 True 时仅 is_staff 可访问（与 AiOpsOpsPermission 配合）
AIOPS_OPS_REQUIRE_STAFF = os.environ.get(
    "AIOPS_OPS_REQUIRE_STAFF", "false"
).lower() in ("1", "true", "yes")

# HashiCorp Vault（可选）：仅占位读取，密钥仍以环境变量为主
AIOPS_VAULT_ADDR = (os.environ.get("AIOPS_VAULT_ADDR") or "").strip()
AIOPS_VAULT_SECRET_PATH = (os.environ.get("AIOPS_VAULT_SECRET_PATH") or "").strip()


def _resolve_aiops_deployment_mode() -> str:
    """部署形态（显式配置优先，否则根据是否在 Pod 内推断）。"""
    v = os.environ.get("AIOPS_DEPLOYMENT_MODE", "").strip().lower()
    if v in ("kubernetes", "hybrid", "physical", "unspecified"):
        return v
    # 标准 K8s  downward API / 自动注入
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return "kubernetes"
    return "unspecified"


# kubernetes=中心主要在集群内，工作负载数据以 API/指标栈为主；hybrid=集群+物理机并存；physical=以边缘探针为主
AIOPS_DEPLOYMENT_MODE = _resolve_aiops_deployment_mode()
# 是否在 Kubernetes Pod 中运行（不依赖显式开关，便于云上/自建集群一致）
AIOPS_IN_KUBERNETES_POD = bool(os.environ.get("KUBERNETES_SERVICE_HOST", "").strip())
