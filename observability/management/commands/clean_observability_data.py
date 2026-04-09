"""
清理可观测性落库数据：PostgreSQL LogEvent（可选 LogInsight），可选同步 ClickHouse log_events。

默认仅统计待删行数（dry-run）；必须加 --apply 才真正删除。ClickHouse 使用异步 mutation，大表需等待合并。

「全删」示例（先 CH 再 PG）：
  python manage.py clean_observability_data --truncate-clickhouse \\
    --confirm-truncate TRUNCATE_CH_LOG_EVENTS --apply
  python manage.py clean_observability_data --purge-all-postgres --with-insights \\
    --confirm-purge DELETE_ALL_OBSERVABILITY_PG_DATA --apply
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from observability.models import LogEvent, LogInsight


def _ch_cutoff_literal(dt) -> str:
    base = dt.strftime("%Y-%m-%d %H:%M:%S")
    ms = int(getattr(dt, "microsecond", 0)) // 1000
    return f"{base}.{ms:03d}"


class Command(BaseCommand):
    help = "Prune old LogEvent rows (PG); optional LogInsight + ClickHouse log_events"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Delete rows strictly older than N days (by event_time / insight created_at). Default: 7.",
        )
        parser.add_argument(
            "--stream-key",
            type=str,
            default="",
            help="Only affect this stream_key (optional).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete; without this flag only print counts (safe default).",
        )
        parser.add_argument(
            "--with-insights",
            action="store_true",
            help="Also delete LogInsight rows older than cutoff (same --stream-key filter if set).",
        )
        parser.add_argument(
            "--clickhouse",
            action="store_true",
            help="Queue ClickHouse ALTER … DELETE for log_events older than cutoff (same stream filter).",
        )
        parser.add_argument(
            "--truncate-clickhouse",
            action="store_true",
            help="TRUNCATE entire ClickHouse log_events table (ignores --days). Requires --confirm-truncate.",
        )
        parser.add_argument(
            "--confirm-truncate",
            type=str,
            default="",
            help='Must be exactly: TRUNCATE_CH_LOG_EVENTS',
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=3000,
            help="PostgreSQL delete batch size (default: 3000).",
        )
        parser.add_argument(
            "--purge-all-postgres",
            action="store_true",
            help="Delete ALL LogEvent rows (ignores --days). Optional --stream-key limits to one stream. Requires --confirm-purge.",
        )
        parser.add_argument(
            "--confirm-purge",
            type=str,
            default="",
            help="With --purge-all-postgres: must be exactly DELETE_ALL_OBSERVABILITY_PG_DATA",
        )

    def handle(self, *args, **opts):
        batch = max(200, min(int(opts["batch"]), 10_000))
        sk = (opts["stream_key"] or "").strip()[:128]
        apply = bool(opts["apply"])
        days = max(1, int(opts["days"]))
        cutoff = timezone.now() - timedelta(days=days)
        ch_truncate = bool(opts["truncate_clickhouse"])
        confirm = (opts["confirm_truncate"] or "").strip()
        purge_all_pg = bool(opts["purge_all_postgres"])
        confirm_purge = (opts["confirm_purge"] or "").strip()

        if purge_all_pg:
            if confirm_purge != "DELETE_ALL_OBSERVABILITY_PG_DATA":
                raise CommandError(
                    "Refusing full PG purge: pass "
                    "--confirm-purge DELETE_ALL_OBSERVABILITY_PG_DATA"
                )
            qs_ev = LogEvent.objects.all()
            if sk:
                qs_ev = qs_ev.filter(stream_key=sk)
            n_ev = qs_ev.count()
            qs_in = None
            n_in = 0
            if opts["with_insights"]:
                qs_in = LogInsight.objects.all()
                if sk:
                    qs_in = qs_in.filter(stream_key=sk)
                n_in = qs_in.count()
            self.stdout.write(
                "Purge ALL PostgreSQL observability rows"
                + (f" (stream_key={sk!r})" if sk else " (all streams)")
            )
            self.stdout.write(f"  LogEvent rows: {n_ev}")
            if opts["with_insights"]:
                self.stdout.write(f"  LogInsight rows: {n_in}")
            if not apply:
                self.stdout.write(
                    self.style.WARNING("Dry-run only. Re-run with --apply to delete.")
                )
                return
            deleted_ev = 0
            while True:
                ids = list(qs_ev.order_by("pk").values_list("pk", flat=True)[:batch])
                if not ids:
                    break
                LogEvent.objects.filter(pk__in=ids).delete()
                deleted_ev += len(ids)
                if deleted_ev % (batch * 5) == 0:
                    self.stdout.write(f"  … deleted {deleted_ev} LogEvent …")
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {deleted_ev} LogEvent row(s) (PG).")
            )
            if opts["with_insights"] and qs_in is not None:
                del_in, _ = qs_in.delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted {del_in} LogInsight row(s) (PG).")
                )
            self.stdout.write(
                "LogStream 表未删除；若需去掉流记录请从后台删或另行处理。"
            )
            return

        if ch_truncate:
            if confirm != "TRUNCATE_CH_LOG_EVENTS":
                raise CommandError(
                    "Refusing to truncate ClickHouse: pass --confirm-truncate TRUNCATE_CH_LOG_EVENTS"
                )
            if not apply:
                self.stdout.write(
                    self.style.WARNING(
                        "Dry-run: would TRUNCATE ClickHouse log_events (add --apply to execute)."
                    )
                )
                return
            self._truncate_clickhouse()
            self.stdout.write(self.style.SUCCESS("ClickHouse log_events truncated."))
            return

        qs_ev = LogEvent.objects.filter(event_time__lt=cutoff)
        if sk:
            qs_ev = qs_ev.filter(stream_key=sk)
        n_ev = qs_ev.count()

        n_in = 0
        qs_in = None
        if opts["with_insights"]:
            qs_in = LogInsight.objects.filter(created_at__lt=cutoff)
            if sk:
                qs_in = qs_in.filter(stream_key=sk)
            n_in = qs_in.count()

        self.stdout.write(
            f"Cutoff: {cutoff.isoformat()} (older than {days} day(s))"
            + (f", stream_key={sk!r}" if sk else ", all streams")
        )
        self.stdout.write(f"  LogEvent rows to delete: {n_ev}")
        if opts["with_insights"]:
            self.stdout.write(f"  LogInsight rows to delete: {n_in}")

        if opts["clickhouse"] and not apply:
            self._preview_clickhouse_delete(cutoff, sk)

        if not apply:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to delete.")
            )
            return

        deleted_ev = 0
        while True:
            ids = list(qs_ev.order_by("pk").values_list("pk", flat=True)[:batch])
            if not ids:
                break
            LogEvent.objects.filter(pk__in=ids).delete()
            deleted_ev += len(ids)
            if deleted_ev % (batch * 5) == 0:
                self.stdout.write(f"  … deleted {deleted_ev} LogEvent …")
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_ev} LogEvent row(s)."))

        if opts["with_insights"] and qs_in is not None:
            del_in, _ = qs_in.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {del_in} LogInsight row(s)."))

        if opts["clickhouse"]:
            self._run_clickhouse_delete(cutoff, sk)

    def _ch_escape_str(self, s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace("'", "''")

    def _preview_clickhouse_delete(self, cutoff, sk: str) -> None:
        from observability.clickhouse_store import _ch_enabled, ensure_schema, get_client, _utc_naive

        if not _ch_enabled():
            self.stdout.write(
                self.style.WARNING("ClickHouse disabled; skip --clickhouse.")
            )
            return
        ensure_schema()
        db = settings.CLICKHOUSE_DATABASE
        c = get_client()
        w = _utc_naive(cutoff)
        where = f"event_time < toDateTime64('{_ch_cutoff_literal(w)}', 3, 'UTC')"
        if sk:
            where += f" AND stream_key = '{self._ch_escape_str(sk)}'"
        cnt_sql = f"SELECT count() FROM `{db}`.log_events WHERE {where}"
        try:
            r = c.query(cnt_sql)
            n = int(r.result_rows[0][0] if r.result_rows else 0)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"ClickHouse count query failed: {e}"))
            return
        self.stdout.write(f"  CH: Would queue DELETE for ~{n} row(s) (add --apply).")

    def _run_clickhouse_delete(self, cutoff, sk: str) -> None:
        from observability.clickhouse_store import _ch_enabled, ensure_schema, get_client, _utc_naive

        if not _ch_enabled():
            return
        ensure_schema()
        db = settings.CLICKHOUSE_DATABASE
        c = get_client()
        w = _utc_naive(cutoff)
        where = f"event_time < toDateTime64('{_ch_cutoff_literal(w)}', 3, 'UTC')"
        if sk:
            where += f" AND stream_key = '{self._ch_escape_str(sk)}'"
        sql = f"ALTER TABLE `{db}`.log_events DELETE WHERE {where}"
        try:
            c.command(sql)
            self.stdout.write(
                self.style.SUCCESS(
                    "ClickHouse DELETE mutation submitted; check system.mutations / wait for completion."
                )
            )
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"ClickHouse DELETE failed: {e}"))

    def _truncate_clickhouse(self) -> None:
        from observability.clickhouse_store import _ch_enabled, ensure_schema, get_client

        if not _ch_enabled():
            raise CommandError("ClickHouse disabled")
        ensure_schema()
        db = settings.CLICKHOUSE_DATABASE
        c = get_client()
        c.command(f"TRUNCATE TABLE IF EXISTS `{db}`.log_events")
