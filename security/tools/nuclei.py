from __future__ import annotations
# ============================================================
# security/tools/nuclei.py — 漏洞扫描 (pentest 原样移植)
# ============================================================

import json

from .base import BaseTool


class NucleiTool(BaseTool):
    name = "nuclei"
    command_template = "nuclei -u {target} -json -silent"

    def build_command(self, target: str, options: dict | None = None) -> list[str]:
        severity = options.get("severity", "critical,high,medium") if options else "critical,high,medium"
        return ["nuclei", "-u", target, "-severity", severity, "-json", "-silent", "-stats"]

    def parse_output(self, lines: list[str]) -> list[dict]:
        results = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("["):
                continue
            try:
                data = json.loads(line)
                info = data.get("info", {})
                severity_map = {
                    "critical": "critical", "high": "high", "medium": "medium",
                    "low": "low", "info": "info",
                }
                raw_severity = (info.get("severity") or data.get("severity", "info")).lower()
                cls = info.get("classification", {})
                cls = cls if isinstance(cls, dict) else {}
                cve_ids = cls.get("cve-id", [None])
                results.append({
                    "title": info.get("name", data.get("template-id", "")),
                    "severity": severity_map.get(raw_severity, "info"),
                    "type": data.get("type", "vulnerability"),
                    "target": data.get("host", data.get("matched-at", "")),
                    "endpoint": data.get("matched-at", ""),
                    "description": info.get("description", ""),
                    "cve": cve_ids[0] if cve_ids else None,
                    "cvss_score": cls.get("cvss-score"),
                    "references": info.get("reference", []) or [],
                    "tags": info.get("tags", []) or [],
                    "remediation": info.get("remediation", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return results
