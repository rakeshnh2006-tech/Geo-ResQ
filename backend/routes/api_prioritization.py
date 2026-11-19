"""
backend/routes/api_prioritization.py
Prioritization API — ST-09
===========================
GET  /api/prioritization            — ranked list (coordinators)
POST /api/prioritization/run        — trigger re-score of all unscored requests
"""
from __future__ import annotations

from flask import Blueprint, jsonify
from flask_login import login_required

from backend.agents.prioritization_agent import get_ranked_requests, run_prioritization
from backend.utils.audit import log_action
from backend.utils.decorators import coordinator_required

prioritization_bp = Blueprint("prioritization", __name__)


@prioritization_bp.get("/prioritization")
@login_required
@coordinator_required
def get_prioritization():
    ranked = get_ranked_requests()
    return jsonify({"prioritization": ranked}), 200


@prioritization_bp.post("/prioritization/run")
@login_required
@coordinator_required
def run_prioritization_endpoint():
    scores = run_prioritization()
    log_action(
        "prioritization.run",
        payload={"scored_count": len(scores)},
    )
    return jsonify({
        "scored": len(scores),
        "message": f"Scored {len(scores)} new relief requests.",
    }), 200
