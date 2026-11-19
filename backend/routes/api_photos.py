"""
backend/routes/api_photos.py
Photo upload API for incident evidence images.

POST /api/incidents/<id>/photos   — upload 1–5 images (multipart/form-data)
GET  /api/incidents/<id>/photos   — list photos for an incident
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required
from sqlalchemy import select
from werkzeug.utils import secure_filename

from backend.app import db
from backend.models.incident import Incident
from backend.models.incident_photo import IncidentPhoto

photos_bp = Blueprint("photos", __name__)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "heic"}
MAX_PHOTOS_PER_INCIDENT = 10
MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB per file


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _upload_dir() -> Path:
    """Return (and create) the uploads directory inside frontend/static."""
    base = Path(current_app.static_folder) / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


@photos_bp.post("/incidents/<int:incident_id>/photos")
def upload_photos(incident_id: int):
    """Accept multipart photo uploads and save them under static/uploads/."""
    incident = db.get_or_404(Incident, incident_id)

    files = request.files.getlist("photos")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": {"code": "NO_FILES", "message": "No files uploaded."}}), 400

    # Count existing photos
    existing = db.session.scalar(
        db.select(db.func.count(IncidentPhoto.id))
        .where(IncidentPhoto.incident_id == incident_id)
    ) or 0
    if existing >= MAX_PHOTOS_PER_INCIDENT:
        return jsonify({
            "error": {"code": "TOO_MANY_PHOTOS",
                       "message": f"Maximum {MAX_PHOTOS_PER_INCIDENT} photos per incident."}
        }), 400

    upload_dir = _upload_dir()
    saved = []

    for f in files:
        if not f.filename or not _allowed(f.filename):
            continue
        # Read first to check size without seeking twice
        data = f.read()
        if len(data) > MAX_FILE_BYTES:
            continue

        ext = f.filename.rsplit(".", 1)[1].lower()
        unique_name = f"{incident_id}_{uuid.uuid4().hex}.{ext}"
        safe_name = secure_filename(unique_name)
        dest = upload_dir / safe_name
        dest.write_bytes(data)

        url_path = f"/static/uploads/{safe_name}"
        photo = IncidentPhoto(
            incident_id=incident_id,
            filename=safe_name,
            url_path=url_path,
        )
        db.session.add(photo)
        saved.append(photo)

    if not saved:
        return jsonify({
            "error": {"code": "NO_VALID_FILES",
                       "message": "No valid image files found. Allowed: jpg, png, gif, webp."}
        }), 400

    db.session.commit()
    return jsonify({
        "uploaded": len(saved),
        "photos": [p.to_dict() for p in saved],
    }), 201


@photos_bp.get("/incidents/<int:incident_id>/photos")
def list_photos(incident_id: int):
    """Return all photos for a given incident."""
    db.get_or_404(Incident, incident_id)
    photos = db.session.scalars(
        select(IncidentPhoto)
        .where(IncidentPhoto.incident_id == incident_id)
        .order_by(IncidentPhoto.uploaded_at)
    ).all()
    return jsonify({"photos": [p.to_dict() for p in photos]}), 200
