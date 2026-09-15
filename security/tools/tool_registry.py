from __future__ import annotations
# ============================================================
# security/tools/tool_registry.py — 工具注册表 (pentest 原样移植)
# ============================================================

from .base import BaseTool
from .subfinder import SubfinderTool
from .httpx_tool import HTTPxTool
from .nmap import NmapTool
from .nuclei import NucleiTool

TOOLS: dict[str, type[BaseTool]] = {
    "subfinder": SubfinderTool,
    "httpx": HTTPxTool,
    "nmap": NmapTool,
    "nuclei": NucleiTool,
}


def get_tool(name: str) -> BaseTool:
    tool_cls = TOOLS.get(name)
    if tool_cls is None:
        raise ValueError(f"Unknown tool: {name}. Available: {list(TOOLS.keys())}")
    return tool_cls()


def list_tools() -> list[str]:
    return list(TOOLS.keys())


def get_default_tools() -> list[BaseTool]:
    return [SubfinderTool(), HTTPxTool(), NmapTool()]
