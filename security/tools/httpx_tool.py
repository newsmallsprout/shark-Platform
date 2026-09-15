from __future__ import annotations
# ============================================================
# security/tools/httpx_tool.py — HTTP 存活探测 (pentest 原样移植)
# ============================================================

import json

from .base import BaseTool


class HTTPxTool(BaseTool):
    name = "httpx"
    command_template = "httpx -l {target_list} -title -tech-detect -status-code -json"

    def build_command(self, target: str, options: dict | None = None) -> list[str]:
        return ["httpx", "-u", target, "-title", "-tech-detect", "-status-code", "-json", "-silent"]

    def parse_output(self, lines: list[str]) -> list[dict]:
        results = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                tech_list = data.get("tech", []) or data.get("technologies", [])
                results.append({
                    "type": "url",
                    "value": data.get("url", data.get("input", "")),
                    "status_code": data.get("status_code"),
                    "title": data.get("title", ""),
                    "technologies": tech_list if isinstance(tech_list, list) else [tech_list],
                    "webserver": data.get("webserver", ""),
                })
            except json.JSONDecodeError:
                continue
        return results
