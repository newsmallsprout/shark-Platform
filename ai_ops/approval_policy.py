"""
Approval policy: severity + model confidence + change heuristics → queue / auto-approve (low risk only).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ai_ops.models import Incident, Ticket

_DANGEROUS_PATTERNS = re.compile(
    r"\b(kubectl\s+.*\b(delete|apply|patch|replace|rollout|scale|exec|attach|port-forward)\b|"
    r"rm\s+-rf|mkfs\.|shutdown|reboot|iptables\s+-F|curl\s+.*\|\s*sh)\b",
    re.IGNORECASE,
)


def model_confidence_bucket(final: Optional[Dict[str, Any]]) -> str:
    if not final:
        return "low"
    c = str((final.get("confidence") or "low")).lower()
    if c in ("high", "medium", "low"):
        return c
    return "low"


def evaluate_ticket_after_creation(
    ticket: Ticket,
    incident: Incident,
    final: Optional[Dict[str, Any]],
    *,
    from_webhook: bool = False,
) -> str:
    """
    Returns:
      ``noop`` — leave status as created (draft / auto_heal path unchanged)
      ``submit_pending`` — draft → pending_approval
      ``auto_approve`` — draft → approved (no human); use only for low-risk policy matches
    """
    from django.conf import settings

    if ticket.status != Ticket.STATUS_DRAFT:
        return "noop"
    if getattr(ticket, "routing", "") == "auto_heal":
        return "noop"

    if not getattr(settings, "AIOPS_APPROVAL_POLICY_ENABLED", True):
        return "noop"

    sev = (incident.severity or "").lower()
    conf = model_confidence_bucket(final)

    if getattr(settings, "AIOPS_APPROVAL_AUTO_LOW_RISK", False):
        if sev == "info" and conf == "high":
            prop = (ticket.proposed_action or "")[:20000]
            if not _DANGEROUS_PATTERNS.search(prop):
                return "auto_approve"

    if from_webhook and getattr(settings, "AIOPS_ALERT_AUTO_SUBMIT_TICKET_PENDING", False):
        return "submit_pending"

    return "noop"
