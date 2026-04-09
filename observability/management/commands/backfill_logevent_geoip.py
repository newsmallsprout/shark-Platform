"""
根据 client_ip 用当前 GeoLite2 库重算 geo_* 字段（历史数据在升级解析规则或换库后常需跑一次）。
不自动改 ClickHouse；若 OLAP 用 CH，请在 PG 回填后 truncate 对应窗口再执行 backfill_clickhouse_logevents，或依赖新流量双写。
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from observability.geoip import lookup_city
from observability.models import LogEvent


class Command(BaseCommand):
    help = "Re-resolve GeoIP (country/city/lat/lon) from client_ip for existing LogEvent rows"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=24 * 7,
            help="Only events with event_time within the last N hours (default: 168).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=200_000,
            help="Max rows to process (default: 200000).",
        )
        parser.add_argument(
            "--stream-key",
            type=str,
            default="",
            help="Optional stream_key filter.",
        )
        parser.add_argument(
            "--only-empty-geo",
            action="store_true",
            help="Only rows where geo_country is empty (default: all rows with client_ip).",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=500,
            help="Rows per bulk_update (default: 500).",
        )

    def handle(self, *args, **opts):
        hours = max(1, int(opts["hours"]))
        limit = max(1, int(opts["limit"]))
        batch_size = max(50, min(int(opts["batch"]), 2000))
        sk = (opts["stream_key"] or "").strip()
        only_empty = bool(opts["only_empty_geo"])

        since = timezone.now() - timedelta(hours=hours)
        qs = LogEvent.objects.filter(event_time__gte=since).exclude(client_ip="")
        if sk:
            qs = qs.filter(stream_key=sk)
        if only_empty:
            qs = qs.filter(geo_country="")
        qs = qs.order_by("pk")[:limit]

        buf: list[LogEvent] = []
        updated = 0
        for ev in qs.iterator(chunk_size=batch_size):
            g = lookup_city(ev.client_ip or "")
            ev.geo_country = (g.get("country") or "")[:128]
            ev.geo_city = (g.get("city") or "")[:256]
            ev.geo_lat = g.get("lat")
            ev.geo_lon = g.get("lon")
            buf.append(ev)
            if len(buf) >= batch_size:
                LogEvent.objects.bulk_update(
                    buf,
                    ["geo_country", "geo_city", "geo_lat", "geo_lon"],
                    batch_size=batch_size,
                )
                updated += len(buf)
                buf = []
        if buf:
            LogEvent.objects.bulk_update(
                buf,
                ["geo_country", "geo_city", "geo_lat", "geo_lon"],
                batch_size=batch_size,
            )
            updated += len(buf)

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated geo fields for {updated} LogEvent row(s). "
                "ClickHouse: run python manage.py backfill_clickhouse_geoip (same window) to refresh OLAP."
            )
        )
