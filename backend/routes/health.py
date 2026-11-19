"""
backend/routes/health.py
Health check endpoint — ST-14.

GET /healthz
  200  {"status": "ok",    "db": "ok"}
  503  {"status": "error", "db": "unavailable", "detail": "..."}

Used by Docker HEALTHCHECK and IBM Cloud Code Engine liveness probe.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)

log = logging.getLogger(__name__)


@health_bp.get("/healthz")
def healthz():
    """Return 200 if the app + DB are reachable, 503 otherwise."""
    db_status = "ok"
    db_detail: str | None = None

    try:
        from sqlalchemy import text
        from backend.app import db
        db.session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        log.warning("healthz DB check failed: %s", exc)
        db_status = "unavailable"
        db_detail = str(exc)

    healthy = db_status == "ok"
    payload: dict = {"status": "ok" if healthy else "error", "db": db_status}
    if db_detail:
        payload["detail"] = db_detail

    return jsonify(payload), 200 if healthy else 503
