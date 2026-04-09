"""
ClickHouse log_events：按 client_ip 用当前 GeoLite2 库批量 UPDATE geo_*（与 PG backfill_logevent_geoip 配套）。
对时间窗内每个「去重后的 IP」执行一条 ALTER TABLE … UPDATE，避免逐行 mutation 爆炸。

依赖：OBSERVABILITY_OLAP_MODE=mirror|analytics 且 CLICKHOUSE_* 可用；库文件同 ingest（GEOIP_DATABASE_PATH）。
"""

from __future__ import annotations

import re
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from observability.geoip import lookup_city

_IP_SAFE = re.compile(r"^[0-9a-fA-F:.%]+$")


def _esc_ch_str(s: str, max_len: int) -> str:
    t = (s or "")[:max_len]
    return t.replace("\\", "\\\\").replace("'", "\\'")


def _fmt_dt64_utc(dt) -> str:
    """ClickHouse toDateTime64(..., 3, 'UTC') 字面量。"""
    base = dt.strftime("%Y-%m-%d %H:%M:%S")
    ms = int(getattr(dt, "microsecond", 0)) // 1000
    return f"{base}.{ms:03d}"


class Command(BaseCommand):
    help = "Re-resolve GeoIP fields in ClickHouse log_events by client_ip (ALTER UPDATE per distinct IP)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=24 * 7,
            help="Only rows with event_time within the last N hours (default: 168).",
        )
        parser.add_argument(
            "--stream-key",
            type=str,
            default="",
            help="Optional stream_key filter.",
        )
        parser.add_argument(
            "--all-rows",
            action="store_true",
            help="Recompute geo for all rows in window (default: only where geo_country is empty).",
        )
        parser.add_argument(
            "--limit-ips",
            type=int,
            default=50_000,
            help="Max distinct client_ip values to process (default: 50000).",
        )
        parser.add_argument(
            "--sleep-ms",
            type=int,
            default=0,
            help="Pause between ALTER UPDATE (reduce CH load, default: 0).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List distinct IP count and exit without mutations.",
        )

    def handle(self, *args, **opts):
        from observability.clickhouse_store import _ch_enabled, ensure_schema, get_client, _utc_naive

        if not _ch_enabled():
            self.stderr.write(
                "ClickHouse disabled: set OBSERVABILITY_OLAP_MODE=mirror|analytics and CLICKHOUSE_HOST."
            )
            return

        hours = max(1, int(opts["hours"]))
        sk = (opts["stream_key"] or "").strip()[:128]
        only_empty = not bool(opts["all_rows"])
        limit_ips = max(1, int(opts["limit_ips"]))
        sleep_s = max(0, int(opts["sleep_ms"])) / 1000.0
        dry = bool(opts["dry_run"])

        ensure_schema()
        c = get_client()
        db = settings.CLICKHOUSE_DATABASE
        end = timezone.now()
        start = end - timedelta(hours=hours)
        t0 = _utc_naive(start)
        t1 = _utc_naive(end)

        where = [
            "event_time >= {t0:DateTime64(3, 'UTC')}",
            "event_time <= {t1:DateTime64(3, 'UTC')}",
            "client_ip != ''",
        ]
        params: dict = {"t0": t0, "t1": t1}
        if sk:
            where.append("stream_key = {sk:String}")
            params["sk"] = sk
        if only_empty:
            where.append("geo_country = ''")
        where_sql = " AND ".join(where)

        dist_sql = f"""
        SELECT client_ip, count() AS n
        FROM `{db}`.log_events
        WHERE {where_sql}
        GROUP BY client_ip
        ORDER BY n DESC
        LIMIT {limit_ips}
        """
        r = c.query(dist_sql, parameters=params)
        rows = r.result_rows or []
        self.stdout.write(
            f"Window UTC [{t0} .. {t1}], distinct client_ip (capped at {limit_ips}): {len(rows)}"
        )
        if dry:
            self.stdout.write(self.style.WARNING("dry-run: no ALTER TABLE executed."))
            return

        updated_ips = 0
        skipped = 0
        for ip_raw, _n in rows:
            ip = str(ip_raw or "").strip()[:64]
            if not ip or not _IP_SAFE.match(ip):
                skipped += 1
                continue
            g = lookup_city(ip)
            co = _esc_ch_str(str(g.get("country") or ""), 128)
            ci = _esc_ch_str(str(g.get("city") or ""), 256)
            la = g.get("lat")
            lo = g.get("lon")
            lat_sql = "NULL" if la is None else str(float(la))
            lon_sql = "NULL" if lo is None else str(float(lo))

            mut_where = [
                f"client_ip = '{_esc_ch_str(ip, 64)}'",
                f"event_time >= toDateTime64('{_fmt_dt64_utc(t0)}', 3, 'UTC')",
                f"event_time <= toDateTime64('{_fmt_dt64_utc(t1)}', 3, 'UTC')",
            ]
            if sk:
                mut_where.append(f"stream_key = '{_esc_ch_str(sk, 128)}'")
            if only_empty:
                mut_where.append("geo_country = ''")

            sql = (
                f"ALTER TABLE `{db}`.log_events UPDATE "
                f"geo_country = '{co}', "
                f"geo_city = '{ci}', "
                f"geo_lat = {lat_sql}, "
                f"geo_lon = {lon_sql} "
                f"WHERE {' AND '.join(mut_where)}"
            )
            try:
                c.command(sql)
                updated_ips += 1
            except Exception as e:
                self.stderr.write(f"ALTER failed for ip={ip!r}: {e}")
                skipped += 1
            if sleep_s:
                time.sleep(sleep_s)

        self.stdout.write(
            self.style.SUCCESS(
                f"Queued ALTER UPDATE for {updated_ips} distinct IP(s); skipped {skipped}. "
                "Mutations apply asynchronously; check system.mutations or wait before querying dashboards."
            )
        )
