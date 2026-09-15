from __future__ import annotations
# ============================================================
# security/tools/nmap.py — 端口扫描 (pentest 原样移植)
# ============================================================

from .base import BaseTool


class NmapTool(BaseTool):
    name = "nmap"
    command_template = "nmap -sV -sC -oX - {target}"

    def build_command(self, target: str, options: dict | None = None) -> list[str]:
        ports = options.get("ports", "1-1000") if options else "1-1000"
        return [
            "nmap", "-sV", "-sC", "-T4", "-p", ports, "-oX", "-", target,
        ]

    def parse_output(self, lines: list[str]) -> list[dict]:
        import xml.etree.ElementTree as ET

        xml_str = "\n".join(lines)
        results = []

        try:
            root = ET.fromstring(xml_str)
            for host in root.findall(".//host"):
                ip_elem = host.find(".//address[@addrtype='ipv4']")
                ip = ip_elem.get("addr", "") if ip_elem is not None else ""

                for port_elem in host.findall(".//port"):
                    port_id = port_elem.get("portid", "")
                    protocol = port_elem.get("protocol", "")
                    state = port_elem.find("state")
                    state_val = state.get("state", "") if state is not None else ""
                    service = port_elem.find("service")
                    if service is not None:
                        results.append({
                            "type": "port",
                            "value": f"{ip}:{port_id}",
                            "port": int(port_id),
                            "protocol": protocol,
                            "service": service.get("name", ""),
                            "version": service.get("product", "") + " " + service.get("version", ""),
                            "state": state_val,
                        })
        except ET.ParseError:
            pass

        return results
