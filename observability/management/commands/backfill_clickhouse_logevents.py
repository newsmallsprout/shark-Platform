"""
将 PostgreSQL 中已有 LogEvent 批量写入 ClickHouse（CH 表为空或需补历史时用）。
若 CH 中已有重叠数据，可能产生重复行；可先 TRUNCATE shark_obs.log_events。
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from observability.clickhouse_store import _ch_enabled, insert_log_events_from_orm
from observability.models import LogEvent


class Command(BaseCommand):
    help = "Backfill LogEvent rows from PostgreSQL into ClickHouse"

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
            default=100_000,
            help="Max rows to copy (default: 100000).",
        )
        parser.add_argument(
            "--stream-key",
            type=str,
            default="",
            help="Optional stream_key filter.",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=500,
            help="Rows per insert batch (default: 500).",
        )

    def handle(self, *args, **opts):
        if not _ch_enabled():
            self.stderr.write(
                "ClickHouse disabled: set OBSERVABILITY_OLAP_MODE=mirror|analytics and CLICKHOUSE_HOST."
            )
            return

        hours = max(1, int(opts["hours"]))
        limit = max(1, int(opts["limit"]))
        batch_size = max(50, min(int(opts["batch"]), 2000))
        sk = (opts["stream_key"] or "").strip()

        since = timezone.now() - timedelta(hours=hours)
        qs = LogEvent.objects.filter(event_time__gte=since).order_by("pk")
        if sk:
            qs = qs.filter(stream_key=sk)
        qs = qs[:limit]

        total_sent = 0
        buf: list[LogEvent] = []
        for ev in qs.iterator(chunk_size=batch_size):
            buf.append(ev)
            if len(buf) >= batch_size:
                insert_log_events_from_orm(buf)
                total_sent += len(buf)
                buf = []
        if buf:
            insert_log_events_from_orm(buf)
            total_sent += len(buf)

        self.stdout.write(self.style.SUCCESS(f"Inserted {total_sent} rows into ClickHouse."))
