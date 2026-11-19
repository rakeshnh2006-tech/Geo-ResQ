"""
backend/utils/audit.py
Append-only audit log utility — ST-13.

Usage
-----
    from backend.utils.audit import log_action

    log_action(
        action="incident.create",
        entity_type="incidents",
        entity_id=incident.id,
        payload={"status": "pending"},
    )

The function is a no-op when called outside an active Flask application context
(e.g., in tests that don't need audit coverage), so callers never need to guard it.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def log_action(
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    payload: dict[str, Any] | None = None,
    actor_id: int | None = None,
    ip_address: str | None = None,
) -> None:
    """Write one record to the audit_log table.

    Parameters
    ----------
    action:       Dot-separated verb, e.g. ``"incident.create"``.
    entity_type:  Table name of the primary affected record (optional).
    entity_id:    Primary key of that record (optional).
    payload:      Arbitrary JSON-serialisable dict for before/after diffs (optional).
    actor_id:     User id of the acting user.  When omitted, the current
                  Flask-Login user is used automatically if one is authenticated.
    ip_address:   Remote IP. When omitted, Flask's ``request.remote_addr`` is used.
    """
    try:
        # Import lazily to avoid circular imports at module load time.
        from flask import has_request_context, request as flask_request
        from flask_login import current_user

        from backend.app import db
        from backend.models.audit_log import AuditLog

        # Resolve actor from current request if not explicitly provided.
        resolved_actor: int | None = actor_id
        if resolved_actor is None:
            try:
                if current_user.is_authenticated:
                    resolved_actor = current_user.id
            except Exception:  # noqa: BLE001
                pass

        # Resolve IP address from request context.
        resolved_ip: str | None = ip_address
        if resolved_ip is None and has_request_context():
            try:
                resolved_ip = flask_request.remote_addr
            except Exception:  # noqa: BLE001
                pass

        entry = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            actor_id=resolved_actor,
            ip_address=resolved_ip,
        )
        db.session.add(entry)
        db.session.commit()

        log.info(
            "audit",
            extra={
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "actor_id": resolved_actor,
            },
        )
    except Exception as exc:  # noqa: BLE001
        # Audit failure must NEVER break the main request.
        log.error("audit.log_action failed for action=%s: %s", action, exc)
