"""Django DATABASES：默认 SQLite；设置 POSTGRES_HOST 后切换 PostgreSQL。"""

from __future__ import annotations

import os
from pathlib import Path


def get_default_database(base_dir: Path) -> dict:
    host = (os.environ.get("POSTGRES_HOST") or "").strip()
    if host:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "shark"),
            "USER": os.environ.get("POSTGRES_USER", "shark"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "shark"),
            "HOST": host,
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(os.environ.get("POSTGRES_CONN_MAX_AGE", "60")),
            "OPTIONS": {
                "connect_timeout": int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "10")),
            },
        }
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": base_dir / "state" / "db.sqlite3",
    }
