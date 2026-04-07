"""
LangChain / LangGraph 工具适配：直接调用 ``sre_tools.execute_tool``，并在 _run 内通过 Redis 广播 tool_start / tool_end。

用法：在构建 LangGraph 前调用 ``make_streaming_sre_tools(run_id, incident_id)``，将返回的 BaseTool 列表交给 ToolNode 或 agent。
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, List, Literal, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from ai_ops.redis_stream import publish_agent_event
from ai_ops.services.sre_tools import execute_tool

logger = logging.getLogger(__name__)


def _prometheus_url() -> str:
    from django.conf import settings

    return getattr(settings, "PROMETHEUS_URL", "") or getattr(settings, "PROMETHEUS_BASE_URL", "") or ""


class _PrometheusQueryArgs(BaseModel):
    """演示用：将 query_prometheus 包装为强类型入参。"""

    query: str = Field(description="PromQL 表达式")
    query_type: Literal["instant", "range"] = Field(description="instant 或 range")
    range_minutes: int = Field(default=60, ge=1, le=1440)
    step: str = Field(default="60s")


class StreamingPrometheusQueryTool(BaseTool):
    """只读 PromQL 工具：执行前后向 Redis 发 tool_start / tool_end。"""

    name: str = "query_prometheus"
    description: str = "执行 PromQL（instant 或 range），返回 JSON 字符串 Observation。"
    args_schema: type[BaseModel] = _PrometheusQueryArgs

    run_id: str
    incident_id: Optional[int] = None

    def _run(
        self,
        query: str,
        query_type: str,
        range_minutes: int = 60,
        step: str = "60s",
    ) -> str:
        call_id = str(uuid.uuid4())
        arguments = {
            "query": query,
            "query_type": query_type,
            "range_minutes": range_minutes,
            "step": step,
        }
        publish_agent_event(
            self.run_id,
            "tool_start",
            {"tool_name": self.name, "call_id": call_id, "arguments": arguments},
            incident_id=self.incident_id,
        )
        try:
            obs, _ = execute_tool(self.name, arguments, prometheus_url=_prometheus_url())
            payload = obs
            err = None
            out = json.dumps(obs, ensure_ascii=False)
        except Exception as e:
            logger.exception("execute_tool failed")
            err = str(e)[:800]
            payload = {"ok": False, "error": err}
            out = json.dumps(payload, ensure_ascii=False)
        publish_agent_event(
            self.run_id,
            "tool_end",
            {
                "tool_name": self.name,
                "call_id": call_id,
                "ok": err is None,
                "error": err,
                "observation": payload,
            },
            incident_id=self.incident_id,
        )
        return out

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        # Phase 1 全同步 Celery 路径；异步占位避免部分 Runner 调 ainvoke 时报未实现。
        return self._run(*args, **kwargs)


def make_streaming_sre_tools(
    run_id: str,
    *,
    incident_id: Optional[int] = None,
    include_prometheus: bool = True,
) -> List[BaseTool]:
    """按需扩展更多 Streaming*Tool 子类即可。"""
    tools: List[BaseTool] = []
    if include_prometheus:
        tools.append(
            StreamingPrometheusQueryTool(
                run_id=run_id,
                incident_id=incident_id,
            )
        )
    return tools
