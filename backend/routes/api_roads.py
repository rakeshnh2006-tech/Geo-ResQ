"""
backend/routes/api_roads.py
Road segment API — ST-07
=========================
GET  /api/roads                     — list all road segments (coordinators)
POST /api/roads/<id>/block          — mark segment blocked + rerun accessibility
POST /api/roads/<id>/unblock        — unmark blocked + rerun accessibility
GET  /api/accessibility             — get current isolated villages (coordinators)
POST /api/accessibility/run         — trigger a full accessibility recompute
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify
from flask_login import current_user, login_required
from sqlalchemy import select

from backend.agents.accessibility_agent import (
    block_road,
    get_isolated_villages,
    run_accessibility,
    unblock_road,
)
from backend.app import db
from backend.models.road_segment import RoadSegment
from backend.utils.audit import log_action
from backend.utils.decorators import coordinator_required

log = logging.getLogger(__name__)

roads_bp = Blueprint("roads", __name__)


# ---------------------------------------------------------------------------
# GET /api/roads
# ---------------------------------------------------------------------------

@roads_bp.get("/roads")
@login_required
@coordinator_required
def list_roads():
    segments = db.session.scalars(select(RoadSegment)).all()
    return jsonify({"roads": [s.to_dict() for s in segments]}), 200


# ---------------------------------------------------------------------------
# POST /api/roads/<id>/block
# ---------------------------------------------------------------------------

@roads_bp.post("/roads/<int:segment_id>/block")
@login_required
@coordinator_required
def block_road_endpoint(segment_id: int):
    try:
        summary = block_road(segment_id)
    except ValueError as e:
        return jsonify({"error": {"code": "NOT_FOUND", "message": str(e)}}), 404
    log.info("Road %d blocked by coordinator %d", segment_id, current_user.id)
    log_action(
        "road.block",
        entity_type="road_segments",
        entity_id=segment_id,
        payload={"summary": summary},
    )
    return jsonify({"summary": summary}), 200


# ---------------------------------------------------------------------------
# POST /api/roads/<id>/unblock
# ---------------------------------------------------------------------------

@roads_bp.post("/roads/<int:segment_id>/unblock")
@login_required
@coordinator_required
def unblock_road_endpoint(segment_id: int):
    try:
        summary = unblock_road(segment_id)
    except ValueError as e:
        return jsonify({"error": {"code": "NOT_FOUND", "message": str(e)}}), 404
    log.info("Road %d unblocked by coordinator %d", segment_id, current_user.id)
    log_action(
        "road.unblock",
        entity_type="road_segments",
        entity_id=segment_id,
        payload={"summary": summary},
    )
    return jsonify({"summary": summary}), 200


# ---------------------------------------------------------------------------
# GET /api/accessibility
# ---------------------------------------------------------------------------

@roads_bp.get("/accessibility")
@login_required
@coordinator_required
def accessibility_status():
    isolated = get_isolated_villages()
    return jsonify({
        "isolated_villages": [r.to_dict() for r in isolated]
    }), 200


# ---------------------------------------------------------------------------
# POST /api/accessibility/run
# ---------------------------------------------------------------------------

@roads_bp.post("/accessibility/run")
@login_required
@coordinator_required
def run_accessibility_endpoint():
    summary = run_accessibility()
    return jsonify({"summary": summary}), 200
