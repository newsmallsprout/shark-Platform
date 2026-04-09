"""
访问日志解析：支持 Nginx JSON 行（推荐）与 extended/combined 文本行。
新增格式时在此扩展 parse_line，并在 ingest 中挂 log_format。
"""

from __future__ import annotations

import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone as dt_timezone
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
    # Nginx $msec：秒.毫秒（Unix 时间戳）
    try:
        f = float(s)
        if f > 1_000_000_000:
            return datetime.fromtimestamp(f, tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError):
        pass
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
        # Nginx $time_local 尾缀 +0800 / -0500：按该偏移构造 aware，避免误用 Django 默认时区
        sign = 1 if tz[0] == "+" else -1
        off_h, off_m = int(tz[1:3]), int(tz[3:5])
        delta = timedelta(minutes=sign * (off_h * 60 + off_m))
        tzinfo = dt_timezone(delta)
        return datetime(int(year), mon, int(day), int(hh), int(mm), int(ss), tzinfo=tzinfo)
    return None


def _parse_ip_candidate(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if s.startswith("["):
        end = s.find("]")
        if end > 0:
            s = s[1:end]
    elif s.count(":") == 1 and "." in s.split(":")[0]:
        s = s.rsplit(":", 1)[0]
    try:
        ipaddress.ip_address(s.split("%", 1)[0].strip())
        return s.split("%", 1)[0].strip()[:64]
    except ValueError:
        return ""


def _ip_is_public_for_geo(ip: str) -> bool:
    """用于 GeoIP：跳过内网/回环/链路本地等，避免整条链落在 10.x 上解析不出国家城市。"""
    if not ip:
        return False
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0].strip())
    except ValueError:
        return False
    return not (
        a.is_private
        or a.is_loopback
        or a.is_link_local
        or a.is_reserved
        or a.is_multicast
        or a.is_unspecified
    )


def _xff_ip_chain(xff: str) -> list[str]:
    out: list[str] = []
    for part in (xff or "").split(","):
        ip = _parse_ip_candidate(part.strip())
        if ip:
            out.append(ip)
    return out


def extract_client_ip_from_json(obj: dict[str, Any]) -> str:
    """
    选取最可能代表真实访客的 IP 供 GeoIP 使用（入库写入 LogEvent.client_ip，不要求日志里已有该键名）。
    1) CDN / LB 常见直连头里的公网 IP
    2) X-Forwarded-For 中从左到右第一个公网段
    3) X-Real-IP / realip_remote_addr / remote_addr 等为公网时用之
    4) 否则退回 XFF 首段或 remote_addr（含内网地址，便于排查）
    """
    for key in (
        "client_ip",
        "cf_connecting_ip",
        "CF-Connecting-IP",
        "true_client_ip",
        "True-Client-IP",
        "http_cf_connecting_ip",
        "http_true_client_ip",
    ):
        raw = str(obj.get(key) or "").strip()
        if raw in ("", "-"):
            continue
        ip = _parse_ip_candidate(raw)
        if ip and _ip_is_public_for_geo(ip):
            return ip

    xff_raw = ""
    for key in ("http_x_forwarded_for", "x_forwarded_for", "X-Forwarded-For"):
        xff_raw = str(obj.get(key) or "").strip()
        if xff_raw and xff_raw != "-":
            break
    for ip in _xff_ip_chain(xff_raw):
        if _ip_is_public_for_geo(ip):
            return ip

    for key in (
        "http_x_real_ip",
        "x_real_ip",
        "X-Real-IP",
        "realip_remote_addr",
    ):
        raw = str(obj.get(key) or "").strip()
        if raw in ("", "-"):
            continue
        ip = _parse_ip_candidate(raw)
        if ip and _ip_is_public_for_geo(ip):
            return ip

    ra = str(obj.get("remote_addr") or "").strip()
    if ra.startswith("unix:"):
        ra = ""
    if ra in ("-", ""):
        ra = ""
    ra_ip = _parse_ip_candidate(ra)
    if ra_ip and _ip_is_public_for_geo(ra_ip):
        return ra_ip

    for key in (
        "http_x_real_ip",
        "x_real_ip",
        "X-Real-IP",
        "realip_remote_addr",
    ):
        raw = str(obj.get(key) or "").strip()
        if raw in ("", "-"):
            continue
        ip = _parse_ip_candidate(raw)
        if ip:
            return ip

    chain = _xff_ip_chain(xff_raw)
    if chain:
        return chain[0]
    return ra_ip or ""


def parse_nginx_json_line(line: str) -> Optional[dict[str, Any]]:
    line = line.strip()
    if not line or line[0] not in "{[":
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, list):
        if len(obj) != 1 or not isinstance(obj[0], dict):
            return None
        obj = obj[0]
    if not isinstance(obj, dict):
        return None
    ts = (
        obj.get("ts")
        or obj.get("time")
        or obj.get("time_local")
        or obj.get("msec")
    )
    et = _parse_nginx_time(str(ts)) if ts else timezone.now()
    if et is None:
        et = timezone.now()
    rt = obj.get("rt")
    if rt is None and "request_time" in obj:
        rt = obj.get("request_time")
    try:
        request_time = float(rt) if rt is not None and str(rt) != "" else None
    except (TypeError, ValueError):
        request_time = None
    urt = obj.get("urt") or obj.get("upstream_response_time") or ""
    status = int(obj.get("status") or obj.get("status_code") or 0)
    b = obj.get("bytes")
    if b is None:
        b = obj.get("body_bytes_sent") or obj.get("bytes_sent") or obj.get("size")
    try:
        bytes_sent = int(b) if b is not None and str(b) != "" else 0
    except (TypeError, ValueError):
        bytes_sent = 0
    pth = obj.get("uri") or obj.get("path") or obj.get("request_uri") or ""
    host = (
        obj.get("host")
        or obj.get("server_name")
        or obj.get("http_host")
        or ""
    )
    return {
        "event_time": et,
        "host": str(host or "")[:255],
        "method": str(obj.get("method") or "")[:16],
        "path": str(pth)[:4000],
        "status_code": status,
        "bytes_sent": bytes_sent,
        "request_time": request_time,
        "upstream_time": str(urt)[:64],
        "parser": "nginx_json",
        "client_ip": extract_client_ip_from_json(obj),
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
    ip_raw = (m.group("ip") or "").strip()
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
        "client_ip": _parse_ip_candidate(ip_raw),
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
