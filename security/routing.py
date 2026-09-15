# ============================================================
# security/routing.py — WebSocket 路由
# ============================================================

from __future__ import annotations

from django.urls import re_path

from .consumers import ScanConsumer

websocket_urlpatterns = [
    re_path(r"^ws/tasks/(?P<task_id>[0-9a-fA-F-]+)$", ScanConsumer.as_asgi()),
]
