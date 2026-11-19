"""
backend/routes/api_briefings.py
Briefings API — ST-10
=====================
POST /api/briefings           — generate a new briefing (coordinators)
GET  /api/briefings           — list all briefings (coordinators)
GET  /api/briefings/<id>      — single briefing detail (coordinators)
GET  /api/briefings/<id>/pdf  — download PDF (coordinators)
"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, jsonify, send_file
from flask_login import current_user, login_required
from sqlalchemy import select

from backend.agents.briefing_agent import generate_briefing
from backend.app import db
from backend.models.briefing import Briefing
from backend.utils.audit import log_action
from backend.utils.decorators import coordinator_required

log = logging.getLogger(__name__)

briefings_bp = Blueprint("briefings", __name__)


@briefings_bp.post("/briefings")
@login_required
@coordinator_required
def create_briefing():
    briefing = generate_briefing(generated_by_id=current_user.id)
    log_action(
        "briefing.generate",
        entity_type="briefings",
        entity_id=briefing.id,
        payload={"briefing_id": briefing.id},
    )
    return jsonify({"briefing": briefing.to_dict()}), 201


@briefings_bp.get("/briefings")
@login_required
@coordinator_required
def list_briefings():
    briefings = db.session.scalars(
        select(Briefing).order_by(Briefing.created_at.desc())
    ).all()
    return jsonify({"briefings": [b.to_dict() for b in briefings]}), 200


@briefings_bp.get("/briefings/<int:briefing_id>")
@login_required
@coordinator_required
def get_briefing(briefing_id: int):
    briefing = db.get_or_404(Briefing, briefing_id)
    return jsonify({"briefing": briefing.to_dict()}), 200


@briefings_bp.get("/briefings/<int:briefing_id>/pdf")
@login_required
@coordinator_required
def download_briefing_pdf(briefing_id: int):
    briefing = db.get_or_404(Briefing, briefing_id)
    if not briefing.pdf_path:
        return jsonify({"error": {"code": "NOT_FOUND",
                                  "message": "PDF not available for this briefing."}}), 404
    pdf_path = Path(briefing.pdf_path)
    if not pdf_path.exists():
        return jsonify({"error": {"code": "NOT_FOUND",
                                  "message": "PDF file not found on disk."}}), 404
    return send_file(
        str(pdf_path),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"briefing_{briefing_id}.pdf",
    )
