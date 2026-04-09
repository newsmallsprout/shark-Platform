"""
Golden incidents：对固定 incident 上下文做软上下文与 Prometheus URL 解析回归（不调用大模型）。

用法：
  python manage.py golden_incidents_check
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from ai_ops.graph import gather_soft_context
from ai_ops.models import Incident
from ai_ops.prometheus_urls import resolve_prometheus_base_url


class Command(BaseCommand):
    help = "Golden check: gather_soft_context + resolve_prometheus_base_url for sample incidents"

    def handle(self, *args, **options):
        root = Path(__file__).resolve().parents[3]
        p = root / "ai_ops" / "fixtures" / "golden_incidents.json"
        if not p.exists():
            self.stdout.write(self.style.WARNING(f"Missing {p}; create it or skip."))
            return
        raw = json.loads(p.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("incidents", [])
        for item in items:
            pk = item.get("incident_id")
            if pk is None:
                continue
            inc = Incident.objects.filter(pk=pk).first()
            if not inc:
                self.stdout.write(self.style.ERROR(f"incident_id={pk} not in DB; seed or adjust fixture"))
                continue
            ctx = gather_soft_context(inc.pk)
            assert "text" in ctx
            url = resolve_prometheus_base_url(inc)
            self.stdout.write(
                f"OK incident={pk} prom_base={url!r} soft_context_chars={len(ctx.get('text') or '')}"
            )
        self.stdout.write(self.style.SUCCESS("golden_incidents_check done"))
