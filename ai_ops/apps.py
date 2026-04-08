import os

from django.apps import AppConfig
from django.db.utils import OperationalError, ProgrammingError


class AiOpsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ai_ops"

    def ready(self) -> None:
        _sync_ai_config_from_env()


def _sync_ai_config_from_env() -> None:
    """若设置 SHARK_AI_API_KEY（或 DEEPSEEK_API_KEY），同步到活跃 AIConfig，便于 Compose 注入 DeepSeek。"""
    key = (
        os.environ.get("SHARK_AI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
    ).strip()
    if not key:
        return
    try:
        from .models import AIConfig
    except ImportError:
        return
    try:
        cfg = AIConfig.get_active_config()
        prov = (os.environ.get("SHARK_AI_PROVIDER") or "deepseek").strip().lower()
        if prov not in ("openai", "deepseek", "custom"):
            prov = "deepseek"
        base = (os.environ.get("SHARK_AI_API_BASE") or "https://api.deepseek.com/v1").strip()[
            :255
        ]
        model = (os.environ.get("SHARK_AI_MODEL") or "deepseek-chat").strip()[:100]
        enable = os.environ.get("SHARK_AI_ENABLE", "true").lower() not in (
            "0",
            "false",
            "no",
        )
        cfg.provider = prov
        cfg.api_base = base or cfg.api_base
        cfg.model = model or cfg.model
        cfg.api_key = key[:255]
        cfg.enable_ai_analysis = enable
        cfg.save(
            update_fields=[
                "provider",
                "api_base",
                "model",
                "api_key",
                "enable_ai_analysis",
            ]
        )
    except (OperationalError, ProgrammingError):
        pass
