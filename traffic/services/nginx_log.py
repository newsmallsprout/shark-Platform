import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_missing_time_logged = False

# Nginx combined-ish (request_time at end is common custom format)
_COMBINED_RE = re.compile(
    r'^(?P<remote_addr>\S+) \S+ \S+ \[(?P<time_local>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<request_uri>\S+)(?: HTTP/[^"]+)?" (?P<status>\d{3}) (?P<body_bytes>\S+)'
    r'(?: "(?P<referer>[^"]*)" "(?P<user_agent>[^"]*)"(?: (?P<request_time>[\d.]+))?)?'
)

_TIME_LOCAL_FMT = "%d/%b/%Y:%H:%M:%S %z"

# Nginx $time_local 英文月缩写；strptime 的 %b 随系统 LC_TIME 变化，非英文环境常解析失败 → 误用「当前时间」
_NGX_TIME_LOCAL_RE = re.compile(
    r"^(?P<day>\d{1,2})/(?P<mon>[A-Za-z]{3})/(?P<year>\d{4}):"
    r"(?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})"
    r"(?:\s+(?P<tzsign>[+-])(?P<tzh>\d{2})(?P<tzm>\d{2}))?$"
)
_MONTH_EN = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def read_log_tail(path: str, max_bytes: int) -> List[str]:
    if not path or not os.path.isfile(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            start = max(0, size - max_bytes)
            f.seek(start)
            raw = f.read()
        text = raw.decode("utf-8", errors="replace")
        if start > 0 and text:
            text = text.split("\n", 1)[-1]
        return [ln for ln in text.splitlines() if ln.strip()]
    except OSError as e:
        logger.warning("read_log_tail %s: %s", path, e)
        return []


def _parse_time_local(s: str) -> Optional[float]:
    """Parse Nginx $time_local; locale-independent (English month abbr)."""
    s = (s or "").strip()
    if not s:
        return None
    m = _NGX_TIME_LOCAL_RE.match(s)
    if m:
        mon = _MONTH_EN.get(m.group("mon").lower())
        if mon is None:
            return None
        try:
            day = int(m.group("day"))
            year = int(m.group("year"))
            H, M, S = int(m.group("H")), int(m.group("M")), int(m.group("S"))
        except (TypeError, ValueError):
            return None
        if m.group("tzsign"):
            sign = 1 if m.group("tzsign") == "+" else -1
            off = sign * (int(m.group("tzh")) * 3600 + int(m.group("tzm")) * 60)
            tz = timezone(timedelta(seconds=off))
        else:
            tz = timezone.utc
        try:
            dt = datetime(year, mon, day, H, M, S, tzinfo=tz)
            return dt.timestamp()
        except ValueError:
            return None
    try:
        dt = datetime.strptime(s, _TIME_LOCAL_FMT)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _ts_from_epoch_field(val: Any) -> Optional[float]:
    """Nginx $msec is Unix seconds.fractions; some stacks use ms epoch."""
    if val is None:
        return None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return None
    if x > 1e12:
        x /= 1000.0
    if x < 946684800 or x > 4102444800:
        return None
    return x


def _ts_from_iso8601(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def parse_log_line(line: str, log_format: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    lf = (log_format or "json").strip().lower()
    if lf in ("nginx_json", "shark_json"):
        lf = "json"
    if lf == "auto":
        r = parse_log_line(line, "json")
        if r is not None:
            return r
        return parse_log_line(line, "combined")
    if lf == "json":
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return None
        return normalize_json_record(obj)
    m = _COMBINED_RE.match(line)
    if not m:
        return None
    gd = m.groupdict()
    ts = _parse_time_local(gd["time_local"] or "")
    if ts is None:
        ts = datetime.now(timezone.utc).timestamp()
    try:
        status = int(gd["status"])
    except (TypeError, ValueError):
        status = 0
    rt = gd.get("request_time")
    request_time_ms = float(rt) * 1000 if rt else 0.0
    return {
        "ts": ts,
        "status": status,
        "request_time_ms": request_time_ms,
        "request_uri": gd.get("request_uri") or "/",
        "remote_addr": gd.get("remote_addr") or "",
    }


def normalize_json_record(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map common Nginx JSON log keys to internal shape.

    ``ts`` must reflect **request time** from the log line (msec / time_local / ISO8601).
    If none parse, we fall back to "now" only as last resort (charts would stack at ingest time).
    """
    ts = None
    if "msec" in obj and obj["msec"] is not None and str(obj["msec"]).strip() != "":
        ts = _ts_from_epoch_field(obj["msec"])
    if ts is None and "time" in obj:
        v = obj["time"]
        if isinstance(v, (int, float)):
            ts = _ts_from_epoch_field(v)
        elif isinstance(v, str):
            ts = _ts_from_epoch_field(v.strip())
            if ts is None and "T" in v:
                ts = _ts_from_iso8601(v)
    if ts is None and "time_local" in obj:
        ts = _parse_time_local(str(obj["time_local"]))
    for k in ("time_iso8601", "time_iso8601_local"):
        if ts is None and k in obj:
            ts = _ts_from_iso8601(obj[k])
            if ts is not None:
                break
    if ts is None and "@timestamp" in obj:
        ts = _ts_from_iso8601(obj["@timestamp"])
    if ts is None:
        global _missing_time_logged
        if not _missing_time_logged:
            _missing_time_logged = True
            logger.warning(
                "traffic: log lines lack parseable request time (msec / time_local / time_iso8601); "
                "charts use ingest time until log_format is fixed"
            )
        ts = datetime.now(timezone.utc).timestamp()

    status = obj.get("status") or obj.get("response_status") or 0
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = 0

    rt = obj.get("request_time") or obj.get("request_time_ms")
    if rt is not None:
        try:
            request_time_ms = float(rt) * 1000 if float(rt) < 1000 else float(rt)
        except (TypeError, ValueError):
            request_time_ms = 0.0
    else:
        request_time_ms = 0.0

    uri = (
        obj.get("request_uri")
        or obj.get("uri")
        or obj.get("path")
        or "/"
    )
    if isinstance(uri, str) and "?" in uri:
        uri = uri.split("?", 1)[0]

    addr = (
        obj.get("remote_addr")
        or obj.get("client_ip")
        or obj.get("http_x_forwarded_for", "").split(",")[0].strip()
        or ""
    )

    return {
        "ts": float(ts),
        "status": status,
        "request_time_ms": request_time_ms,
        "request_uri": str(uri)[:2048],
        "remote_addr": str(addr).strip()[:64],
    }


def records_from_lines(lines: List[str], log_format: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ln in lines:
        rec = parse_log_line(ln, log_format)
        if rec:
            out.append(rec)
    return out


def load_records(
    access_path: str, log_format: str, max_tail_bytes: int
) -> List[Dict[str, Any]]:
    lines = read_log_tail(access_path, max_tail_bytes)
    return records_from_lines(lines, log_format)
