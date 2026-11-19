"""
backend/routes/api_incidents.py
Incident API — ST-05
====================
POST /api/incidents   — submit a new incident report
GET  /api/incidents   — list incidents (coordinators only)
GET  /api/incidents/<id> — single incident detail (coordinators only)
PATCH /api/incidents/<id>/status — update status (coordinators only)
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from backend.agents.intake_agent import run_intake
from backend.app import db
from backend.models.incident import Incident, IncidentStatus
from backend.models.verification import VerificationStatus
from backend.utils.audit import log_action
from backend.utils.decorators import coordinator_required

log = logging.getLogger(__name__)

incidents_bp = Blueprint("incidents", __name__)


# ---------------------------------------------------------------------------
# POST /api/incidents
# ---------------------------------------------------------------------------

@incidents_bp.post("/incidents")
def create_incident():
    """Submit a new incident report.

    Public endpoint (no login required) — anonymous reports allowed.
    Rate-limited via Flask-Limiter (configured globally: 10/hour per IP).
    """
    body = request.get_json(silent=True) or {}
    raw_text = (body.get("description") or "").strip()

    if not raw_text or len(raw_text) < 10:
        return jsonify({
            "error": {"code": "VALIDATION_ERROR",
                      "message": "description must be at least 10 characters."}
        }), 400

    from backend.agents.verification_agent import run_verification

    reporter_id = current_user.id if current_user.is_authenticated else None

    # Parse optional GPS and location hint from JSON body
    user_lat  = _safe_float(body.get("user_lat"))
    user_lng  = _safe_float(body.get("user_lng"))
    loc_hint  = (body.get("location_hint") or "").strip() or None

    incident = run_intake(
        raw_text,
        reporter_id=reporter_id,
        user_lat=user_lat,
        user_lng=user_lng,
        location_hint=loc_hint,
    )

    # Run verification automatically — only on pending (not incomplete) incidents
    if incident.status == IncidentStatus.pending:
        try:
            run_verification(incident)
        except Exception as exc:  # noqa: BLE001
            log.warning("Verification failed for incident %d: %s", incident.id, exc)

    log_action(
        "incident.create",
        entity_type="incidents",
        entity_id=incident.id,
        payload={"status": incident.status.value, "severity": incident.severity},
    )
    return jsonify({
        "incident": {
            "id": incident.id,
            "status": incident.status.value,
            "location_name": incident.location_name,
            "lat": incident.lat,
            "lng": incident.lng,
            "incident_type": incident.incident_type.value if incident.incident_type else None,
            "severity": incident.severity,
            "affected_households": incident.affected_households,
            "report_time": incident.report_time.isoformat() if incident.report_time else None,
            "created_at": incident.created_at.isoformat(),
        }
    }), 201


# ---------------------------------------------------------------------------
# GET /api/incidents
# ---------------------------------------------------------------------------

@incidents_bp.get("/incidents")
@login_required
@coordinator_required
def list_incidents():
    """Return all incidents, newest first. Coordinator-only."""
    status_filter = request.args.get("status")
    stmt = select(Incident).order_by(Incident.created_at.desc())
    if status_filter:
        try:
            status_enum = IncidentStatus(status_filter)
            stmt = stmt.where(Incident.status == status_enum)
        except ValueError:
            return jsonify({
                "error": {"code": "VALIDATION_ERROR",
                          "message": f"Unknown status: {status_filter}"}
            }), 400

    incidents = db.session.scalars(stmt).all()
    return jsonify({"incidents": [i.to_dict() for i in incidents]}), 200


# ---------------------------------------------------------------------------
# GET /api/incidents/<id>
# ---------------------------------------------------------------------------

@incidents_bp.get("/incidents/<int:incident_id>")
@login_required
@coordinator_required
def get_incident(incident_id: int):
    incident = db.get_or_404(Incident, incident_id)
    data = incident.to_dict()
    data["raw_text"] = incident.raw_text
    data["structured_json"] = incident.structured_json
    return jsonify({"incident": data}), 200


# ---------------------------------------------------------------------------
# PATCH /api/incidents/<id>/status
# ---------------------------------------------------------------------------

@incidents_bp.patch("/incidents/<int:incident_id>/status")
@login_required
@coordinator_required
def update_incident_status(incident_id: int):
    incident = db.get_or_404(Incident, incident_id)
    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    try:
        incident.status = IncidentStatus(new_status)
    except (ValueError, TypeError):
        return jsonify({
            "error": {"code": "VALIDATION_ERROR",
                      "message": f"Invalid status: {new_status}"}
        }), 400

    db.session.commit()
    log.info("Incident %d status updated to %s by user %d",
             incident_id, new_status, current_user.id)
    log_action(
        "incident.status_update",
        entity_type="incidents",
        entity_id=incident_id,
        payload={"new_status": new_status},
    )
    return jsonify({"incident": incident.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/incidents/<id>/verify   — coordinator accepts an incomplete/conflict
# POST /api/incidents/<id>/reject   — coordinator rejects an incident
# ---------------------------------------------------------------------------

@incidents_bp.post("/incidents/<int:incident_id>/verify")
@login_required
@coordinator_required
def verify_incident(incident_id: int):
    incident = db.get_or_404(Incident, incident_id)
    body = request.get_json(silent=True) or {}
    note = body.get("note", "")

    incident.status = IncidentStatus.verified
    if incident.verification:
        incident.verification.status = VerificationStatus.passed
        incident.verification.coordinator_note = note
        incident.verification.reviewed_by_id = current_user.id
    db.session.commit()
    log.info("Incident %d manually verified by coordinator %d", incident_id, current_user.id)
    log_action(
        "incident.verify",
        entity_type="incidents",
        entity_id=incident_id,
        payload={"note": note},
    )
    return jsonify({"incident": incident.to_dict()}), 200


def _safe_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


@incidents_bp.post("/incidents/<int:incident_id>/reject")
@login_required
@coordinator_required
def reject_incident(incident_id: int):
    incident = db.get_or_404(Incident, incident_id)
    body = request.get_json(silent=True) or {}
    note = body.get("note", "")

    incident.status = IncidentStatus.rejected
    if incident.verification:
        incident.verification.coordinator_note = note
        incident.verification.reviewed_by_id = current_user.id
    db.session.commit()
    log.info("Incident %d rejected by coordinator %d", incident_id, current_user.id)
    log_action(
        "incident.reject",
        entity_type="incidents",
        entity_id=incident_id,
        payload={"note": note},
    )
    return jsonify({"incident": incident.to_dict()}), 200
