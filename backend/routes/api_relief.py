"""
backend/routes/api_relief.py
Relief Request API — ST-08
==========================
POST /api/relief-requests           — submit a relief request (public)
GET  /api/relief-requests           — list all (coordinators)
GET  /api/relief-requests/<id>      — single detail (coordinators)
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from backend.agents.relief_assessment_agent import run_relief_assessment
from backend.app import db
from backend.models.relief_request import ReliefRequest
from backend.utils.audit import log_action
from backend.utils.decorators import coordinator_required

log = logging.getLogger(__name__)

relief_bp = Blueprint("relief", __name__)


@relief_bp.post("/relief-requests")
def create_relief_request():
    body = request.get_json(silent=True) or {}
    raw_text = (body.get("description") or "").strip()
    incident_id = body.get("incident_id")

    if not raw_text or len(raw_text) < 10:
        return jsonify({"error": {"code": "VALIDATION_ERROR",
                                  "message": "description must be at least 10 characters."}}), 400
    if not incident_id:
        return jsonify({"error": {"code": "VALIDATION_ERROR",
                                  "message": "incident_id is required."}}), 400

    reporter_id = current_user.id if current_user.is_authenticated else None
    try:
        relief = run_relief_assessment(raw_text, int(incident_id), reporter_id)
    except ValueError as exc:
        return jsonify({"error": {"code": "NOT_FOUND", "message": str(exc)}}), 404

    log_action(
        "relief_request.create",
        entity_type="relief_requests",
        entity_id=relief.id,
        payload={
            "need_category": relief.need_category.value if relief.need_category else None,
            "urgency_score": relief.urgency_score,
        },
    )
    return jsonify({"relief_request": relief.to_dict()}), 201


@relief_bp.get("/relief-requests")
@login_required
@coordinator_required
def list_relief_requests():
    requests_qs = db.session.scalars(
        select(ReliefRequest).order_by(ReliefRequest.created_at.desc())
    ).all()
    return jsonify({"relief_requests": [r.to_dict() for r in requests_qs]}), 200


@relief_bp.get("/relief-requests/<int:relief_id>")
@login_required
@coordinator_required
def get_relief_request(relief_id: int):
    relief = db.get_or_404(ReliefRequest, relief_id)
    data = relief.to_dict()
    data["raw_text"] = relief.raw_text
    return jsonify({"relief_request": data}), 200
