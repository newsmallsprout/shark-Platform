"""
SREToolAdapter：将现有 ``ai_ops.services.sre_tools.execute_tool`` 封装为 LangGraph / LangChain 可调用的 Tool。

- 若已安装 ``langchain_core``，生成 ``StructuredTool`` 列表，可直接 bind_tools / ToolNode。
- 未安装时仍提供 ``run_platform_read_tool`` 统一入口，便于单元测试与渐进迁移。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

logger = logging.getLogger(__name__)

from ai_ops.services.sre_tools import execute_tool, tool_schemas

try:
    from langchain_core.tools import StructuredTool
except ImportError:  # pragma: no cover - 可选依赖
    StructuredTool = None  # type: ignore[misc, assignment]

try:
    from pydantic import Field, create_model
except ImportError:  # pragma: no cover
    Field = None  # type: ignore
    create_model = None  # type: ignore


def _prometheus_url_from_settings() -> str:
    from django.conf import settings

    return getattr(settings, "PROMETHEUS_URL", "") or getattr(settings, "PROMETHEUS_BASE_URL", "") or ""


def run_platform_read_tool(
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    prometheus_url: Optional[str] = None,
) -> Tuple[Dict[str, Any], bool]:
    """
    统一调用入口：与旧 ReAct 循环使用同一套底层实现，保证行为一致。
    返回 (observation_dict, is_final_report_tool)。
    """
    url = prometheus_url or _prometheus_url_from_settings()
    return execute_tool(tool_name, arguments or {}, prometheus_url=url)


def _json_schema_to_pydantic_model(name: str, schema: Dict[str, Any]) -> Optional[Type[Any]]:
    """将 OpenAI function parameters 子集转为 Pydantic 动态模型（仅支持 object + 常见标量）。"""
    if create_model is None or Field is None or not isinstance(schema, dict):
        return None
    if schema.get("type") != "object":
        return None
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    field_defs: Dict[str, Any] = {}
    for prop_name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        t = spec.get("type", "string")
        py_t: Any = str
        if t == "integer":
            py_t = int
        elif t == "number":
            py_t = float
        elif t == "boolean":
            py_t = bool
        desc = spec.get("description", "")
        if prop_name in required:
            field_defs[prop_name] = (py_t, Field(..., description=desc))
        else:
            field_defs[prop_name] = (Optional[py_t], Field(None, description=desc))
    if not field_defs:
        return None
    return create_model(f"{name}Args", **field_defs)  # type: ignore[arg-type]


class SREToolAdapter:
    """
    平台只读工具适配器：从现有 ``tool_schemas()`` 自动生成 LangChain Tool（若依赖可用）。
    """

    def __init__(self, prometheus_url: Optional[str] = None):
        self._prometheus_url = prometheus_url

    @property
    def prometheus_url(self) -> str:
        return self._prometheus_url or _prometheus_url_from_settings()

    def make_langchain_tools(self) -> List[Any]:
        """
        返回 ``StructuredTool`` 列表；未安装 langchain_core 时返回空列表并打日志。
        """
        if StructuredTool is None:
            logger.warning("langchain_core 未安装，跳过 StructuredTool 生成；请 pip install langchain-core")
            return []

        tools: List[Any] = []
        for schema in tool_schemas():
            fn_block = schema.get("function") or {}
            name = fn_block.get("name")
            desc = fn_block.get("description") or ""
            params = fn_block.get("parameters") or {}
            if not name:
                continue

            ArgsModel = _json_schema_to_pydantic_model(str(name), params)

            def _closure(tool_name: str) -> Callable[..., str]:
                def _invoke(**kwargs: Any) -> str:
                    obs, _ = run_platform_read_tool(tool_name, kwargs, prometheus_url=self.prometheus_url)
                    return json.dumps(obs, ensure_ascii=False)

                return _invoke

            invoker = _closure(str(name))
            if ArgsModel is not None:
                st = StructuredTool.from_function(
                    func=invoker,
                    name=str(name),
                    description=desc,
                    args_schema=ArgsModel,
                )
            else:
                st = StructuredTool.from_function(
                    func=invoker,
                    name=str(name),
                    description=desc,
                )
            tools.append(st)
        return tools

    @staticmethod
    def openai_functions_payload() -> List[Dict[str, Any]]:
        """与旧版 chat.completions tools 参数格式一致，便于双栈并存期复用。"""
        return tool_schemas()
