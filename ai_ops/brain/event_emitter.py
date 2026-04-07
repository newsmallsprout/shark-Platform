"""
AgentEventEmitter：将 LangGraph / 手工节点事件推入 Redis Pub/Sub，供 WebSocket/SSE 层订阅广播。

设计要点：
- 与具体 ASGI 框架解耦：只负责 publish；Django Channels / FastAPI 侧单独 subscribe。
- 事件载荷为 JSON，含单调 seq，便于前端排序与断线重连后的 gap 检测（重连策略由网关实现）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore


@dataclass
class AgentEvent:
    """单条可序列化事件（也可作为类型契约供前端 TS 对齐）。"""

    run_id: str
    incident_id: Optional[int]
    seq: int
    ts: float  # time.time() 单调时钟旁路，展示层再格式化为 ISO8601
    type: str  # thought_delta | tool_call | tool_result | graph_node | ticket_draft | error | done | ...
    payload: Dict[str, Any]

    def to_json_bytes(self) -> bytes:
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentEvent":
        return cls(
            run_id=d["run_id"],
            incident_id=d.get("incident_id"),
            seq=int(d["seq"]),
            ts=float(d["ts"]),
            type=str(d["type"]),
            payload=d.get("payload") or {},
        )


class AgentEventEmitter:
    """
    流式事件推送器：每个 Agent 运行实例对应一个 run_id，订阅方监听 channel ``agent:run:{run_id}``。

    LangGraph 侧建议在 Celery Worker 中于节点入口/出口调用 ``emit``，或对 ``graph.astream_events`` 的
    异步迭代做一层薄封装（见 ``emit_langchain_style_event``）。
    """

    CHANNEL_PREFIX = "agent:run:"

    def __init__(self, redis_url: Optional[str] = None, *, client: Optional[Any] = None):
        import os

        url = redis_url or os.environ.get("AGENT_EVENT_REDIS_URL") or os.environ.get(
            "CELERY_BROKER_URL", "redis://localhost:6379/0"
        )
        if client is not None:
            self._redis = client
        else:
            if redis is None:
                raise RuntimeError("redis 包未安装，无法使用 AgentEventEmitter")
            self._redis = redis.Redis.from_url(url, decode_responses=False)
        # 进程内 seq 计数器（按 run_id）；分布式场景可换 Redis INCR
        self._seq: Dict[str, int] = {}

    @classmethod
    def channel(cls, run_id: str) -> str:
        return f"{cls.CHANNEL_PREFIX}{run_id}"

    def next_seq(self, run_id: str) -> int:
        self._seq[run_id] = self._seq.get(run_id, 0) + 1
        return self._seq[run_id]

    def emit(
        self,
        run_id: str,
        event_type: str,
        payload: Dict[str, Any],
        *,
        incident_id: Optional[int] = None,
    ) -> AgentEvent:
        """发布一条事件；返回结构化对象便于调用方写审计日志。"""
        ev = AgentEvent(
            run_id=run_id,
            incident_id=incident_id,
            seq=self.next_seq(run_id),
            ts=time.time(),
            type=event_type,
            payload=payload,
        )
        try:
            self._redis.publish(self.channel(run_id), ev.to_json_bytes())
        except Exception:
            logger.exception("AgentEventEmitter.publish failed run_id=%s type=%s", run_id, event_type)
        return ev

    def listen(self, run_id: str, timeout_sec: float = 0.0) -> Iterator[AgentEvent]:
        """
        阻塞式消费（用于简易 CLI 调试或单进程集成测试）。
        生产环境 WebSocket 服务建议使用异步 subscribe + 协程推送。
        """
        if redis is None:
            raise RuntimeError("redis 包未安装")
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(self.channel(run_id))
        for raw in pubsub.listen():
            if raw["type"] != "message":
                continue
            data = raw.get("data")
            if not isinstance(data, (bytes, str)):
                continue
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            try:
                d = json.loads(data)
                yield AgentEvent.from_dict(d)
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning("skip malformed agent event: %r", data)

    # --- LangGraph / LangChain 风格事件的便捷映射（按需扩展） ---

    def emit_thought_delta(self, run_id: str, text_chunk: str, *, incident_id: Optional[int] = None) -> AgentEvent:
        """模型流式 token / 摘要增量。"""
        return self.emit(run_id, "thought_delta", {"text": text_chunk}, incident_id=incident_id)

    def emit_tool_call(
        self, run_id: str, tool_name: str, arguments: Dict[str, Any], *, incident_id: Optional[int] = None
    ) -> AgentEvent:
        return self.emit(
            run_id,
            "tool_call",
            {"tool_name": tool_name, "arguments": arguments},
            incident_id=incident_id,
        )

    def emit_tool_result(
        self,
        run_id: str,
        tool_name: str,
        observation: Dict[str, Any],
        *,
        incident_id: Optional[int] = None,
    ) -> AgentEvent:
        """Observation 若过大，上游应先落对象存储，此处只传摘要或引用 id。"""
        return self.emit(
            run_id,
            "tool_result",
            {"tool_name": tool_name, "observation": observation},
            incident_id=incident_id,
        )

    def emit_done(self, run_id: str, summary: Optional[Dict[str, Any]] = None, *, incident_id: Optional[int] = None):
        return self.emit(run_id, "done", summary or {}, incident_id=incident_id)

    @staticmethod
    def new_run_id() -> str:
        return str(uuid.uuid4())

    def emit_langchain_style_event(
        self,
        run_id: str,
        lc_event: Dict[str, Any],
        *,
        incident_id: Optional[int] = None,
    ) -> Optional[AgentEvent]:
        """
        将 LangChain ``astream_events`` 单帧粗映射到本平台事件类型（覆盖常见 event 名即可）。
        lc_event 结构随版本变化，此处采用保守解析。
        """
        et = str(lc_event.get("event") or "")
        data = lc_event.get("data") or {}
        name = lc_event.get("name")

        if "on_chat_model_stream" in et:
            chunk = data.get("chunk")
            text = getattr(chunk, "content", None) or (data.get("content") if isinstance(data, dict) else None)
            if text:
                return self.emit_thought_delta(run_id, str(text), incident_id=incident_id)
            return None

        if "on_tool_start" in et:
            return self.emit_tool_call(
                run_id,
                str(name or data.get("name") or "unknown_tool"),
                data.get("input") if isinstance(data.get("input"), dict) else {"raw": data.get("input")},
                incident_id=incident_id,
            )

        if "on_tool_end" in et:
            out = data.get("output")
            obs = out if isinstance(out, dict) else {"result": str(out)}
            return self.emit_tool_result(
                run_id,
                str(name or data.get("name") or "unknown_tool"),
                obs,
                incident_id=incident_id,
            )

        # 图节点级（LangGraph）
        if "on_chain" in et or "chain" in et.lower():
            return self.emit(
                run_id,
                "graph_node",
                {"event": et, "name": name, "data_keys": list(data.keys()) if isinstance(data, dict) else []},
                incident_id=incident_id,
            )

        return self.emit(
            run_id,
            "raw_lc_event",
            {"event": et, "name": name, "data": data},
            incident_id=incident_id,
        )
