"""Resolve Prometheus base URL per incident (multi-cluster / multi-tenant routing)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from django.conf import settings

logger = logging.getLogger(__name__)


def resolve_prometheus_base_url(incident: Any) -> str:
    """
    Default: settings.PROMETHEUS_URL.

    Optional JSON map env AIOPS_PROMETHEUS_URL_BY_CLUSTER:
      {"default": "https://prom-a/", "prod-east": "https://prom-east/", ...}

    Incident alert labels ``cluster`` or ``k8s_cluster`` select the key; otherwise ``default`` then global.
    """
    default = (getattr(settings, "PROMETHEUS_URL", None) or "").strip()
    raw = (getattr(settings, "AIOPS_PROMETHEUS_URL_BY_CLUSTER", None) or "").strip()
    if not raw:
        return default

    try:
        m = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("AIOPS_PROMETHEUS_URL_BY_CLUSTER is not valid JSON; using PROMETHEUS_URL")
        return default

    if not isinstance(m, dict):
        return default

    labels: Dict[str, Any] = {}
    raw_alert = getattr(incident, "raw_alert_data", None)
    if isinstance(raw_alert, dict):
        lbl = raw_alert.get("labels")
        if isinstance(lbl, dict):
            labels = lbl

    for key in ("cluster", "k8s_cluster", "prometheus_cluster", "tenant"):
        c = str(labels.get(key) or "").strip()
        if c and c in m:
            u = str(m[c]).strip()
            if u:
                return u.rstrip("/")

    d = str(m.get("default") or "").strip()
    if d:
        return d.rstrip("/")
    return default
