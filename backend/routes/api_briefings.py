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


@briefings_bp.get("/briefings/<int:briefing_id>/view")
@login_required
@coordinator_required
def view_briefing(briefing_id: int):
    briefing = db.get_or_404(Briefing, briefing_id)
    from backend.agents.briefing_agent import _render_html, _export_pdf_fpdf2, PDF_DIR
    from backend.models.user import User

    author = "Coordinator"
    if briefing.generated_by_id:
        user = db.session.get(User, briefing.generated_by_id)
        if user:
            author = user.full_name

    html = _render_html(briefing.snapshot_json or {}, briefing.summary_text or "", author)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@briefings_bp.get("/briefings/<int:briefing_id>/pdf")
@login_required
@coordinator_required
def download_briefing_pdf(briefing_id: int):
    briefing = db.get_or_404(Briefing, briefing_id)
    pdf_path = Path(briefing.pdf_path).resolve() if briefing.pdf_path else None

    if not pdf_path or not pdf_path.exists():
        # Check instance/briefings fallback
        candidate = (Path("instance/briefings") / f"briefing_{briefing_id}.pdf").resolve()
        if candidate.exists():
            pdf_path = candidate
        else:
            # Dynamically generate on-the-fly using fpdf2
            from backend.agents.briefing_agent import _export_pdf_fpdf2
            from backend.models.user import User

            author = "Coordinator"
            if briefing.generated_by_id:
                user = db.session.get(User, briefing.generated_by_id)
                if user:
                    author = user.full_name

            new_pdf = _export_pdf_fpdf2(
                briefing.snapshot_json or {},
                briefing.summary_text or "",
                author,
                briefing.id,
            )
            if new_pdf and Path(new_pdf).resolve().exists():
                briefing.pdf_path = new_pdf
                db.session.commit()
                pdf_path = Path(new_pdf).resolve()
            else:
                return jsonify({"error": {"code": "NOT_FOUND",
                                          "message": "PDF not available for this briefing."}}), 404

    return send_file(
        str(pdf_path.resolve()),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"briefing_{briefing_id}.pdf",
    )


def _cleanup_briefing_files(briefing_id: int, pdf_path_str: str | None = None) -> None:
    """Safely unlink PDF and HTML files associated with a deleted briefing."""
    try:
        from backend.agents.briefing_agent import PDF_DIR
        paths_to_check = [
            PDF_DIR / f"briefing_{briefing_id}.pdf",
            PDF_DIR / f"briefing_{briefing_id}.html",
            Path("instance/briefings") / f"briefing_{briefing_id}.pdf",
            Path("instance/briefings") / f"briefing_{briefing_id}.html",
        ]
        if pdf_path_str:
            paths_to_check.append(Path(pdf_path_str))

        for p in paths_to_check:
            try:
                resolved = p.resolve()
                if resolved.exists() and resolved.is_file():
                    resolved.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception as exc:
        log.warning("Failed to remove briefing files: %s", exc)


@briefings_bp.delete("/briefings/<int:briefing_id>")
@login_required
@coordinator_required
def delete_briefing(briefing_id: int):
    briefing = db.get_or_404(Briefing, briefing_id)
    pdf_path = briefing.pdf_path
    db.session.delete(briefing)
    db.session.commit()
    _cleanup_briefing_files(briefing_id, pdf_path)
    log_action(
        "briefing.delete",
        entity_type="briefings",
        entity_id=briefing_id,
        payload={"briefing_id": briefing_id},
    )
    return jsonify({"success": True, "message": f"Briefing #{briefing_id} deleted."}), 200


@briefings_bp.post("/briefings/batch-delete")
@login_required
@coordinator_required
def batch_delete_briefings():
    from flask import request
    data = request.get_json(silent=True) or {}
    ids = data.get("briefing_ids", [])
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": {"code": "BAD_REQUEST", "message": "No briefing IDs provided."}}), 400

    deleted_count = 0
    for bid in ids:
        b = db.session.get(Briefing, bid)
        if b:
            pdf_path = b.pdf_path
            db.session.delete(b)
            _cleanup_briefing_files(bid, pdf_path)
            deleted_count += 1
            log_action(
                "briefing.delete",
                entity_type="briefings",
                entity_id=bid,
                payload={"briefing_id": bid, "batch": True},
            )

    db.session.commit()
    return jsonify({
        "success": True,
        "deleted_count": deleted_count,
        "message": f"Successfully deleted {deleted_count} briefing(s)."
    }), 200
