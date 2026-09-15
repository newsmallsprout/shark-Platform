from __future__ import annotations
# ============================================================
# security/tools/subfinder.py — 子域名发现 (pentest 原样移植)
# ============================================================

import json

from .base import BaseTool


class SubfinderTool(BaseTool):
    name = "subfinder"
    command_template = "subfinder -d {domain} -json -silent"

    def build_command(self, target: str, options: dict | None = None) -> list[str]:
        return ["subfinder", "-d", target, "-json", "-silent"]

    def parse_output(self, lines: list[str]) -> list[dict]:
        results = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                results.append({
                    "type": "subdomain",
                    "value": data.get("host", data.get("subdomain", "")),
                    "source": data.get("source", "subfinder"),
                })
            except json.JSONDecodeError:
                continue
        return results
