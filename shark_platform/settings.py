"""
Django settings — AIOps Platform 中心控制面（Django + DRF + LangGraph + Celery + SSE）。
"""

from pathlib import Path
import os
import warnings

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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "state" / "db.sqlite3",
    }
}

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

# L4 自愈：经验库匹配置信度 ≥ 此阈值时自动批准工单并下发 PlaybookJob
AIOPS_AUTO_HEAL_CONFIDENCE_THRESHOLD = float(
    os.environ.get("AIOPS_AUTO_HEAL_CONFIDENCE", "0.95")
)
AIOPS_DEFAULT_PLAYBOOK_NODE = os.environ.get("AIOPS_DEFAULT_PLAYBOOK_NODE", "default")
