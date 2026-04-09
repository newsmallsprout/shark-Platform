"""Outbound webhooks (Slack-compatible JSON) for ops events."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _notify_url() -> str:
    return (getattr(settings, "AIOPS_NOTIFY_WEBHOOK_URL", None) or "").strip()


def notify_payload(payload: Dict[str, Any], *, timeout_sec: float = 8.0) -> bool:
    url = _notify_url()
    if not url:
        return False
    try:
        r = requests.post(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=timeout_sec,
        )
        if r.status_code >= 300:
            logger.warning("notify webhook HTTP %s: %s", r.status_code, r.text[:500])
            return False
        return True
    except Exception:
        logger.exception("notify webhook failed")
        return False


def notify_incident_ticket_event(
    *,
    event: str,
    incident_id: int,
    alert_name: str,
    run_id: str,
    ticket_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """event examples: run_start, ticket_created, pending_approval, run_failed"""
    body: Dict[str, Any] = {
        "source": "shark-aiops",
        "event": event,
        "incident_id": incident_id,
        "alert_name": alert_name,
        "run_id": run_id,
    }
    if ticket_id:
        body["ticket_id"] = ticket_id
    if extra:
        body["extra"] = extra
    notify_payload(body)
