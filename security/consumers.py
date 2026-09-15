# ============================================================
# security/consumers.py — WebSocket 消费者 (FastAPI /ws/tasks/{id} → Channels)
# ============================================================

from __future__ import annotations

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class ScanConsumer(AsyncWebsocketConsumer):
    """扫描进度实时推送，按 task_id 分组"""

    async def connect(self):
        self.task_id = self.scope["url_route"]["kwargs"]["task_id"]
        self.group_name = f"task_{self.task_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "scan_event",
                "event": "stage_changed",
                "data": {"stage": "connected", "message": "WebSocket 已连接"},
            },
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"WS disconnected: task={self.task_id}")

    async def receive(self, text_data=None, bytes_data=None):
        if text_data == "ping":
            await self.send(text_data="pong")

    async def scan_event(self, event):
        """接收频道层广播，转发给 WebSocket 客户端"""
        await self.send(
            text_data=json.dumps(
                {"event": event["event"], "data": event.get("data", {})},
                ensure_ascii=False,
            )
        )
