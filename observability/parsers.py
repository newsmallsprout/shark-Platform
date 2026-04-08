"""
访问日志解析：支持 Nginx JSON 行（推荐）与 extended/combined 文本行。
新增格式时在此扩展 parse_line，并在 ingest 中挂 log_format。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from django.utils import timezone
from django.utils.dateparse import parse_datetime

# combined + 末尾可选 request_time（与自定义 log_format 对齐）
_COMBINED = re.compile(
    r"^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+"
    r'"(?P<method>\S+)\s+(?P<uri>\S+)\s+(?P<proto>[^"]+)"\s+'
    r"(?P<status>\d{3})\s+(?P<bytes>\S+)\s+"
    r'"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)"'
    r"(?:\s+(?P<rt>[\d.]+))?"
)


def _parse_nginx_time(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    # ISO8601 from shark_json
    dt = parse_datetime(s.replace("Z", "+00:00"))
    if dt:
        return dt if timezone.is_aware(dt) else timezone.make_aware(dt)
    # 02/Jan/2026:12:34:56 +0800
    m = re.match(
        r"(\d{2})/(\w{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2})\s+([+-]\d{4})",
        s,
    )
    if m:
        day, mon_s, year, hh, mm, ss, tz = m.groups()
        months = {
            "Jan": 1,
            "Feb": 2,
            "Mar": 3,
            "Apr": 4,
            "May": 5,
            "Jun": 6,
            "Jul": 7,
            "Aug": 8,
            "Sep": 9,
            "Oct": 10,
            "Nov": 11,
            "Dec": 12,
        }
        mon = months.get(mon_s, 1)
        # 简化：忽略 tz 细节，按本地 aware
        naive = datetime(int(year), mon, int(day), int(hh), int(mm), int(ss))
        return timezone.make_aware(naive)
    return None


def parse_nginx_json_line(line: str) -> Optional[dict[str, Any]]:
    line = line.strip()
    if not line or line[0] not in "{[":
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    ts = obj.get("ts") or obj.get("time") or obj.get("time_local")
    et = _parse_nginx_time(str(ts)) if ts else timezone.now()
    if et is None:
        et = timezone.now()
    rt = obj.get("rt")
    try:
        request_time = float(rt) if rt is not None and str(rt) != "" else None
    except (TypeError, ValueError):
        request_time = None
    urt = obj.get("urt") or obj.get("upstream_response_time") or ""
    status = int(obj.get("status") or 0)
    b = obj.get("bytes")
    try:
        bytes_sent = int(b) if b is not None else 0
    except (TypeError, ValueError):
        bytes_sent = 0
    return {
        "event_time": et,
        "host": str(obj.get("host") or "")[:255],
        "method": str(obj.get("method") or "")[:16],
        "path": str(obj.get("uri") or obj.get("path") or "")[:4000],
        "status_code": status,
        "bytes_sent": bytes_sent,
        "request_time": request_time,
        "upstream_time": str(urt)[:64],
        "parser": "nginx_json",
    }


def parse_combined_line(line: str) -> Optional[dict[str, Any]]:
    m = _COMBINED.match(line.strip())
    if not m:
        return None
    et = _parse_nginx_time(m.group("time"))
    if et is None:
        et = timezone.now()
    status = int(m.group("status"))
    bs = m.group("bytes")
    try:
        bytes_sent = int(bs) if bs != "-" else 0
    except ValueError:
        bytes_sent = 0
    rt_raw = m.group("rt")
    request_time = None
    if rt_raw:
        try:
            request_time = float(rt_raw)
        except ValueError:
            pass
    return {
        "event_time": et,
        "host": "",
        "method": (m.group("method") or "")[:16],
        "path": (m.group("uri") or "")[:4000],
        "status_code": status,
        "bytes_sent": bytes_sent,
        "request_time": request_time,
        "upstream_time": "",
        "parser": "nginx_combined",
    }


def parse_line(line: str, log_format: str) -> Optional[dict[str, Any]]:
    fmt = (log_format or "auto").strip().lower()
    if fmt == "nginx_json":
        return parse_nginx_json_line(line)
    if fmt == "nginx_combined":
        return parse_combined_line(line)
    # auto
    r = parse_nginx_json_line(line)
    if r:
        return r
    return parse_combined_line(line)
