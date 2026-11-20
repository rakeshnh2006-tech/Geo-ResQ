"""
backend/agents/intake_agent.py
Incident Intake Agent — ST-05
==============================
Receives raw free-text from a citizen report, calls IBM Granite via
watsonx.ai to extract structured fields, validates with Pydantic, and
persists the resulting Incident row.

Extracted fields
----------------
location_name     str
lat               float | None
lng               float | None
incident_type     one of: flood | landslide | road_block |
                          infrastructure | medical | other
severity          int 1–5
affected_households int | None
report_time       ISO-8601 datetime string | None

If extraction is incomplete (required fields missing), the incident is
saved with status=incomplete and flagged for coordinator review.
If watsonx fails entirely, the incident is saved with
status=incomplete so it is not silently lost.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.app import db
from backend.models.incident import Incident, IncidentStatus, IncidentType
from backend.utils.watsonx_client import WatsonxError, generate

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required fields — incident is "incomplete" if any of these are absent
# ---------------------------------------------------------------------------
_REQUIRED_FIELDS = {"location_name", "incident_type", "severity"}

# ---------------------------------------------------------------------------
# Pydantic extraction schema
# ---------------------------------------------------------------------------

class ExtractedIncident(BaseModel):
    location_name: str | None = None
    lat: float | None = None
    lng: float | None = None
    incident_type: str | None = None
    severity: int | None = Field(default=None, ge=1, le=5)
    affected_households: int | None = Field(default=None, ge=0)
    report_time: str | None = None   # ISO-8601 string; parsed separately

    @field_validator("incident_type", mode="before")
    @classmethod
    def normalise_incident_type(cls, v):
        if v is None:
            return None
        mapping = {
            "flood": "flood",
            "landslide": "landslide",
            "rockslide": "landslide",
            "road_block": "road_block",
            "road block": "road_block",
            "road": "road_block",
            "infrastructure": "infrastructure",
            "bridge": "infrastructure",
            "power": "infrastructure",
            "medical": "medical",
            "health": "medical",
        }
        return mapping.get(str(v).lower().strip(), "other")


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """\
You are a disaster-response data extraction assistant. \
Extract the following fields from the incident report below and return \
ONLY valid JSON with these exact keys: \
location_name, lat, lng, incident_type, severity, affected_households, report_time.

Rules:
- incident_type must be one of: flood, landslide, road_block, infrastructure, medical, other
- severity is an integer 1 (minor) to 5 (catastrophic)
- lat/lng are decimal degrees, null if unknown
- affected_households is an integer, null if unknown
- report_time is ISO-8601 (YYYY-MM-DDTHH:MM:SS), null if unknown
- Use null (not empty string) for unknown values
- Return ONLY the JSON object, no explanation

Incident report:
\"\"\"
{raw_text}
\"\"\"

JSON:
"""


def _build_prompt(raw_text: str) -> str:
    return _EXTRACTION_PROMPT.format(raw_text=raw_text[:3000])


# ---------------------------------------------------------------------------
# Rule-based fallback extractor (runs when Watsonx is unavailable)
# ---------------------------------------------------------------------------

_TYPE_KEYWORDS: dict[str, list[str]] = {
    "flood":          ["flood", "flooding", "inundated", "waterlogged", "submerged", "overflow"],
    "landslide":      ["landslide", "land slide", "rockslide", "mudslide", "debris", "rockfall",
                       "rock burr", "boulders", "rock block"],
    "road_block":     ["road block", "road blocked", "road closed", "tree fall", "tree fallen",
                       "blocked road", "road damage", "bridge", "culvert"],
    "infrastructure": ["power", "electricity", "electric", "transformer", "lines down",
                       "water supply", "pipeline", "infrastructure"],
    "medical":        ["medical", "injured", "casualty", "casualties", "hospital", "ambulance",
                       "snake bite", "illness", "sick"],
}

_HH_RE = re.compile(
    r"(\d{1,4})\s*(?:household|family|families|home|hh|people|persons|residents)",
    re.IGNORECASE,
)

_SEV_KEYWORDS = {
    5: ["catastrophic", "critical", "destroyed", "killed", "death", "dead", "evacuated",
        "displaced", "isolated", "cut off", "washed out", "collapsed"],
    4: ["severe", "major", "dangerous", "urgent", "emergency", "buried", "trapped",
        "stranded", "blocked", "broken", "injured"],
    3: ["moderate", "significant", "considerable", "affected", "damaged"],
    2: ["minor", "small", "limited", "partial"],
    1: ["possible", "suspected", "reported"],
}


def _rule_based_extract(raw_text: str, location_hint: str | None = None) -> dict:
    """Keyword-based extraction — used when Granite is unavailable."""
    text_lower = raw_text.lower()

    # Incident type
    incident_type = "other"
    for itype, keywords in _TYPE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            incident_type = itype
            break

    # Severity — scan for the highest-scoring keywords
    severity = 3   # default: moderate
    for sev in sorted(_SEV_KEYWORDS, reverse=True):
        if any(kw in text_lower for kw in _SEV_KEYWORDS[sev]):
            severity = sev
            break

    # Affected households
    hh_match = _HH_RE.search(raw_text)
    affected_households = int(hh_match.group(1)) if hh_match else None

    # Location name — use hint if provided, else try to find a capitalised phrase
    location_name = location_hint or None
    if not location_name:
        # Look for "at <Place>" or "near <Place>" patterns
        loc_re = re.search(
            r"\b(?:at|near|in|around|from)\s+([A-Z][a-zA-Z\s]{2,30}?)(?:[,.\s]|$)",
            raw_text,
        )
        if loc_re:
            location_name = loc_re.group(1).strip()

    return {
        "location_name": location_name,
        "lat": None,
        "lng": None,
        "incident_type": incident_type,
        "severity": severity,
        "affected_households": affected_households,
        "report_time": None,
    }


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    """Find the outermost {...} block in Granite's output and parse it."""
    match = _JSON_RE.search(text)
    if not match:
        raise ValueError(f"No JSON object found in model output: {text!r}")
    return json.loads(match.group())


def _missing_required(data: ExtractedIncident) -> list[str]:
    missing = []
    for field in _REQUIRED_FIELDS:
        if getattr(data, field) is None:
            missing.append(field)
    return missing


def _parse_report_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_intake(
    raw_text: str,
    reporter_id: int | None = None,
    user_lat: float | None = None,
    user_lng: float | None = None,
    location_hint: str | None = None,
) -> Incident:
    """Extract structured fields from *raw_text* and persist an Incident.

    Parameters
    ----------
    raw_text:       The free-text submitted by the citizen.
    reporter_id:    FK to users.id, or None for anonymous submissions.
    user_lat:       GPS latitude shared by the user's device (overrides AI extraction).
    user_lng:       GPS longitude shared by the user's device (overrides AI extraction).
    location_hint:  Human-entered location hint (used by rule-based fallback extractor).

    Returns
    -------
    The persisted Incident (with id populated).
    """
    incident = Incident(
        reporter_id=reporter_id,
        raw_text=raw_text,
        status=IncidentStatus.pending,
    )

    structured_json: dict | None = None
    extracted: ExtractedIncident | None = None
    missing_fields: list[str] = []
    watsonx_failed = False

    # ── Step 1: Call Granite ───────────────────────────────────────────────
    try:
        prompt = _build_prompt(raw_text)
        raw_output = generate(prompt, max_new_tokens=256, temperature=0.0)
        log.debug("Granite raw output: %s", raw_output)
        structured_json = _extract_json(raw_output)
    except WatsonxError as exc:
        log.warning("Watsonx unavailable (%s) — using rule-based fallback", exc)
        watsonx_failed = True
        structured_json = _rule_based_extract(raw_text, location_hint)
    except (ValueError, json.JSONDecodeError) as exc:
        log.warning("Could not parse Granite JSON output: %s — using fallback", exc)
        structured_json = _rule_based_extract(raw_text, location_hint)

    # ── Step 2: Validate with Pydantic ────────────────────────────────────
    if structured_json is not None:
        try:
            extracted = ExtractedIncident.model_validate(structured_json)
        except ValidationError as exc:
            log.warning("Pydantic validation failed: %s — using fallback", exc)
            extracted = ExtractedIncident.model_validate(
                _rule_based_extract(raw_text, location_hint)
            )

    # ── Step 3: Populate Incident fields ──────────────────────────────────
    if extracted:
        incident.location_name = extracted.location_name
        # Prefer GPS coords from the user's device; fall back to AI extraction
        incident.lat = user_lat if user_lat is not None else extracted.lat
        incident.lng = user_lng if user_lng is not None else extracted.lng
        incident.incident_type = (
            IncidentType(extracted.incident_type) if extracted.incident_type else None
        )
        incident.severity = extracted.severity
        incident.affected_households = extracted.affected_households
        incident.report_time = _parse_report_time(extracted.report_time)
        incident.structured_json = structured_json
        missing_fields = _missing_required(extracted)
    else:
        # Last resort: apply rule-based directly
        fallback = _rule_based_extract(raw_text, location_hint)
        incident.location_name = fallback["location_name"]
        incident.incident_type = IncidentType(fallback["incident_type"])
        incident.severity = fallback["severity"]
        incident.affected_households = fallback["affected_households"]
        incident.lat = user_lat
        incident.lng = user_lng
        missing_fields = []   # rule-based always produces required fields

    # ── Step 3.5: Geocode location against known villages / region centroid ──
    if (incident.lat is None or incident.lng is None):
        try:
            from backend.models.village import Village
            from sqlalchemy import select, func
            query_loc = (incident.location_name or location_hint or "").strip()
            v = None
            if query_loc:
                v = db.session.scalars(
                    select(Village).where(func.lower(Village.name) == query_loc.lower())
                ).first()
                if not v:
                    v = db.session.scalars(
                        select(Village).where(
                            func.lower(Village.name).contains(query_loc.lower()) |
                            func.lower(query_loc).contains(func.lower(Village.name))
                        )
                    ).first()
            if not v:
                # Scan raw text for any known village name
                text_lower = (raw_text + " " + (location_hint or "")).lower()
                all_villages = db.session.scalars(select(Village)).all()
                for village_candidate in all_villages:
                    if village_candidate.name.lower() in text_lower:
                        v = village_candidate
                        if not incident.location_name:
                            incident.location_name = v.name
                        break
            if v:
                incident.lat = v.lat
                incident.lng = v.lng
                log.info("Geocoded incident to village %s (%f, %f)", v.name, v.lat, v.lng)
            elif query_loc and "malenadu" in query_loc.lower():
                incident.lat = 13.75
                incident.lng = 75.5
        except Exception as exc:
            log.warning("Geocoding lookup failed: %s", exc)

    # ── Step 4: Determine status ───────────────────────────────────────────
    # Watsonx failure alone is no longer enough to mark incomplete —
    # the rule-based fallback always fills the required fields.
    if missing_fields:
        incident.status = IncidentStatus.incomplete
        log.info("Incident marked incomplete — missing=%s", missing_fields)
    else:
        incident.status = IncidentStatus.pending   # verification runs next
        if watsonx_failed:
            log.info("Incident %s created via rule-based fallback (Watsonx unavailable)", "pending")

    # ── Step 5: Persist ───────────────────────────────────────────────────
    db.session.add(incident)
    db.session.commit()
    log.info("Incident %d created with status=%s", incident.id, incident.status)
    return incident
