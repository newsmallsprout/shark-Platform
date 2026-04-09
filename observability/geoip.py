"""
GeoLite2 City（.mmdb）：从镜像 URL 下载 .gz 并解压，ingest 时解析国家/城市/经纬度。
须遵守 MaxMind GeoLite2 EULA；镜像 URL 由运维自行配置。
"""

from __future__ import annotations

import gzip
import ipaddress
import logging
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_reader = None
_reader_lock = threading.Lock()
_download_lock = threading.Lock()


def geoip_database_path() -> Path:
    raw = (getattr(settings, "GEOIP_DATABASE_PATH", "") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(settings.BASE_DIR) / "state" / "GeoLite2-City.mmdb"


def geoip_mirror_url() -> str:
    return (getattr(settings, "GEOIP_DATABASE_URL", "") or "").strip()


def ensure_database_file(
    *,
    force: bool = False,
    progress: Optional[Callable[[str], None]] = None,
) -> bool:
    """从 GEOIP_DATABASE_URL 下载 .mmdb.gz 并解压到 GEOIP_DATABASE_PATH。"""
    prog = progress or (lambda _m: None)
    path = geoip_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 1_048_576 and not force:
        return True
    url = geoip_mirror_url()
    if not url:
        logger.warning(
            "GEOIP_DATABASE_URL empty; place GeoLite2-City.mmdb at %s or set mirror URL",
            path,
        )
        return path.exists()

    with _download_lock:
        if path.exists() and path.stat().st_size > 1_048_576 and not force:
            return True
        gz_path = path.with_suffix(path.suffix + ".gz")
        try:
            prog(f"GeoIP: GET {url[:80]}… (timeout 180s)")
            logger.info("GeoIP: downloading from mirror …")
            written = 0
            next_log = 10 * 1024 * 1024
            with requests.get(url, timeout=180, stream=True) as r:
                r.raise_for_status()
                total = r.headers.get("Content-Length")
                prog(
                    f"GeoIP: HTTP {r.status_code}"
                    + (f", Content-Length ~{int(total) // (1 << 20)} MiB" if total and total.isdigit() else "")
                    + " — streaming…"
                )
                with open(gz_path, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        if chunk:
                            f.write(chunk)
                            written += len(chunk)
                            if written >= next_log:
                                prog(f"GeoIP: downloaded ~{written // (1 << 20)} MiB…")
                                next_log = written + 10 * 1024 * 1024
            prog("GeoIP: decompressing .mmdb.gz …")
            with gzip.open(gz_path, "rb") as fin, open(path, "wb") as fout:
                shutil.copyfileobj(fin, fout)
            gz_path.unlink(missing_ok=True)
            sz = path.stat().st_size
            prog(f"GeoIP: done → {path} ({sz // (1 << 20)} MiB)")
            logger.info("GeoIP: saved %s (%s bytes)", path, sz)
            reload_reader()
            return True
        except Exception as e:
            prog(f"GeoIP: error: {e}")
            logger.warning("GeoIP: download failed: %s", e)
            gz_path.unlink(missing_ok=True)
            return path.exists()


def get_reader():
    """线程安全的只读 Reader；无库文件时返回 None。"""
    global _reader
    if _reader is not None:
        return _reader
    with _reader_lock:
        if _reader is not None:
            return _reader
        path = geoip_database_path()
        if not path.exists():
            ensure_database_file()
        if not path.exists():
            return None
        import geoip2.database

        _reader = geoip2.database.Reader(str(path))
        return _reader


def reload_reader() -> None:
    global _reader
    with _reader_lock:
        if _reader is not None:
            try:
                _reader.close()
            except Exception:
                pass
            _reader = None


def lookup_city(ip: str) -> Dict[str, Any]:
    """
    返回 country / city / lat / lon。
    地名优先 zh-CN（GeoLite2 有则返回），否则 en；无城市时用省/州一级行政区名。
    内网或未收录 IP 返回空 dict。
    """
    ip = (ip or "").strip()
    if not ip or ip.startswith("unix:"):
        return {}
    raw = ip.split("%", 1)[0].strip()
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        return {}

    reader = get_reader()
    if reader is None:
        return {}

    import geoip2.errors

    try:
        rec = reader.city(raw)
    except (geoip2.errors.AddressNotFoundError, ValueError, OSError):
        return {}

    def _label(names_map: Any, fallback: str) -> str:
        if names_map:
            get = getattr(names_map, "get", None)
            if callable(get):
                for key in ("zh-CN", "zh", "en"):
                    v = get(key)
                    if v:
                        return str(v).strip()
                try:
                    return str(next(iter(names_map.values()))).strip()
                except (StopIteration, TypeError, AttributeError):
                    pass
        return (fallback or "").strip()

    country = _label(
        rec.country.names,
        (rec.country.name or rec.country.iso_code or ""),
    )
    city = _label(
        rec.city.names,
        (rec.city.name or ""),
    )
    # 无城市名时用一级行政区（省/州），大屏更易读出「国家/地区」
    if not city and rec.subdivisions:
        ms = rec.subdivisions.most_specific
        city = _label(
            ms.names,
            (ms.name or ""),
        )
    lat = rec.location.latitude
    lon = rec.location.longitude
    return {
        "country": country[:128],
        "city": city[:256],
        "lat": float(lat) if lat is not None else None,
        "lon": float(lon) if lon is not None else None,
    }
