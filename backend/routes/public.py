from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from backend.app import db, limiter
from backend.models.incident import Incident, IncidentStatus
from backend.models.relief_request import ReliefRequest
from backend.utils.forms import IncidentReportForm, ReliefRequestForm
from sqlalchemy import func, select

public_bp = Blueprint("public", __name__)


@public_bp.get("/")
def index():
    return render_template("public/index.html")


@public_bp.route("/report", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def report():
    form = IncidentReportForm()
    if form.validate_on_submit():
        from backend.agents.intake_agent import run_intake
        from backend.agents.verification_agent import run_verification

        reporter_id = current_user.id if current_user.is_authenticated else None

        # Parse user-submitted GPS coords (may be blank)
        user_lat = _parse_coord(form.user_lat.data)
        user_lng = _parse_coord(form.user_lng.data)
        location_hint = form.location_hint.data.strip() if form.location_hint.data else None

        incident = run_intake(
            form.description.data,
            reporter_id=reporter_id,
            user_lat=user_lat,
            user_lng=user_lng,
            location_hint=location_hint,
        )

        if incident.status == IncidentStatus.pending:
            try:
                run_verification(incident)
            except Exception:
                pass

        flash("Your incident report has been submitted. Thank you.", "success")
        return redirect(url_for("public.status"))

    return render_template("public/report.html", form=form)


@public_bp.route("/relief", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def relief():
    form = ReliefRequestForm()

    # Pre-populate incident_id from query string if provided
    incident_id = request.args.get("incident_id", type=int)

    if form.validate_on_submit():
        incident_id = request.form.get("incident_id", type=int)
        if not incident_id:
            flash("Please link your request to an incident.", "warning")
            return render_template("public/relief.html", form=form, incident_id=None)

        from backend.agents.relief_assessment_agent import run_relief_assessment
        reporter_id = current_user.id if current_user.is_authenticated else None
        try:
            run_relief_assessment(form.description.data, incident_id, reporter_id)
            flash("Your relief request has been submitted. Thank you.", "success")
            return redirect(url_for("public.status"))
        except ValueError:
            flash("The referenced incident was not found.", "danger")

    return render_template("public/relief.html", form=form, incident_id=incident_id)


# ---------------------------------------------------------------------------
# Live locations API — returns all incidents that have GPS coords
# ---------------------------------------------------------------------------

@public_bp.get("/api/locations")
def live_locations():
    """Return incidents with known lat/lng for the live-location map layer."""
    incidents = db.session.scalars(
        select(Incident)
        .where(Incident.lat.isnot(None), Incident.lng.isnot(None))
        .order_by(Incident.created_at.desc())
        .limit(200)
    ).all()
    return jsonify({
        "locations": [
            {
                "id": inc.id,
                "lat": inc.lat,
                "lng": inc.lng,
                "location_name": inc.location_name,
                "incident_type": inc.incident_type.value if inc.incident_type else None,
                "severity": inc.severity,
                "status": inc.status.value if inc.status else None,
                "raw_text": inc.raw_text,
                "reporter_name": inc.reporter.full_name if inc.reporter else "Anonymous Citizen",
                "reporter_email": inc.reporter.email if inc.reporter else None,
                "created_at": inc.created_at.isoformat() if inc.created_at else None,
            }
            for inc in incidents
        ]
    })


@public_bp.get("/status")
def status():
    total      = db.session.scalar(select(func.count(Incident.id))) or 0
    verified   = db.session.scalar(
        select(func.count(Incident.id)).where(Incident.status == IncidentStatus.verified)
    ) or 0
    relief_count = db.session.scalar(select(func.count(ReliefRequest.id))) or 0

    from backend.models.accessibility_result import AccessibilityResult
    isolated = db.session.scalar(
        select(func.count(AccessibilityResult.id))
        .where(AccessibilityResult.is_isolated == True)  # noqa: E712
    ) or 0

    return render_template("public/status.html",
                           total=total, verified=verified,
                           relief_count=relief_count, isolated=isolated)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_coord(value: str | None) -> float | None:
    """Safely parse a lat/lng string submitted from a form hidden field."""
    try:
        v = float(value or "")
        # Sanity-check: must be a plausible geographic coordinate
        if -90 <= v <= 90 or -180 <= v <= 180:
            return v
    except (ValueError, TypeError):
        pass
    return None
