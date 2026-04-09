"""
Explicit FSM helpers for Incident / Ticket / AgentRun (documentation + transition guards).

Incident.status and Ticket.status remain the DB source of truth; this module centralizes
allowed transitions for future UI and automation.
"""

from __future__ import annotations

from typing import FrozenSet, Tuple

# Incident.status
INCIDENT_OPEN: FrozenSet[str] = frozenset({"open", "analyzing", "awaiting_evidence", "analyzed"})
INCIDENT_TERMINAL: FrozenSet[str] = frozenset({"resolved"})

_INCIDENT_EDGES: Tuple[Tuple[str, str], ...] = (
    ("open", "analyzing"),
    ("analyzing", "analyzed"),
    ("analyzing", "open"),
    ("analyzed", "analyzing"),
    ("analyzing", "awaiting_evidence"),
    ("awaiting_evidence", "analyzing"),
    ("open", "resolved"),
    ("analyzing", "resolved"),
    ("analyzed", "resolved"),
    ("awaiting_evidence", "resolved"),
)

INCIDENT_ALLOWED = frozenset(_INCIDENT_EDGES)


def incident_transition_ok(old: str, new: str) -> bool:
    if old == new:
        return True
    return (old, new) in INCIDENT_ALLOWED


# Ticket.status (see models.Ticket)
_TICKET_EDGES: Tuple[Tuple[str, str], ...] = (
    ("draft", "pending_approval"),
    ("pending_approval", "approved"),
    ("pending_approval", "rejected"),
    ("approved", "executed"),
)

TICKET_ALLOWED = frozenset(_TICKET_EDGES)


def ticket_transition_ok(old: str, new: str) -> bool:
    if old == new:
        return True
    return (old, new) in TICKET_ALLOWED
