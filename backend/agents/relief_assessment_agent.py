"""
backend/agents/relief_assessment_agent.py
Relief Assessment Agent — ST-08
================================
Receives a free-text relief request linked to an incident.
Calls Granite to classify the need category and score urgency,
then applies a weighted formula combining:
  isolation status (40%)  — from AccessibilityResult
  incident severity (30%) — from parent Incident
  household count  (30%)  — from parent Incident

Need category: food | water | medical | rescue
Urgency score:  1–10 (float)

Formula
-------
urgency = (
    0.4 * isolation_score   +   # 1.0 if isolated, 0.0 if accessible
    0.3 * severity_score    +   # severity/5 (normalised to 0–1)
    0.3 * household_score       # min(households,500)/500
) * 10

The Granite call is used ONLY for need classification.  The number
itself is deterministic Python.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select

from backend.app import db
from backend.models.accessibility_result import AccessibilityResult
from backend.models.incident import Incident
from backend.models.relief_request import NeedCategory, ReliefRequest
from backend.utils.watsonx_client import WatsonxError, generate

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Need-category classification via Granite
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """\
Classify the following disaster relief request into exactly one category.
Valid categories: food, water, medical, rescue
Return ONLY the single category word, lowercase, nothing else.

Relief request:
\"\"\"
{raw_text}
\"\"\"

Category:
"""

_CATEGORY_MAP = {
    "food": NeedCategory.food,
    "water": NeedCategory.water,
    "medical": NeedCategory.medical,
    "rescue": NeedCategory.rescue,
}

# Keyword fallback — used when Watsonx is unavailable
_KEYWORD_CATEGORIES: list[tuple[NeedCategory, list[str]]] = [
    (NeedCategory.rescue,  ["rescue", "trapped", "stranded", "evacuate", "evacuation",
                            "missing", "buried", "collapsed", "washed away", "cut off"]),
    (NeedCategory.medical, ["medical", "medicine", "medicines", "doctor", "hospital",
                            "injured", "injury", "sick", "illness", "ambulance",
                            "first aid", "snake bite", "casualty", "casualties"]),
    (NeedCategory.water,   ["water", "drinking water", "clean water", "dehydrat",
                            "flood", "waterlogged"]),
    (NeedCategory.food,    ["food", "supplies", "supply", "hungry", "starving",
                            "ration", "grain", "rice", "meals"]),
]


def _keyword_classify(raw_text: str) -> NeedCategory:
    """Rule-based fallback when Granite is unavailable."""
    text = raw_text.lower()
    for category, keywords in _KEYWORD_CATEGORIES:
        if any(kw in text for kw in keywords):
            return category
    return NeedCategory.food   # safest default


def _classify_need(raw_text: str) -> NeedCategory:
    """Call Granite to classify need; falls back to keyword matching."""
    prompt = _CLASSIFY_PROMPT.format(raw_text=raw_text[:1500])
    try:
        result = generate(prompt, max_new_tokens=8, temperature=0.0)
        word = re.sub(r"[^a-z]", "", result.lower().strip().split()[0])
        granite_result = _CATEGORY_MAP.get(word)
        if granite_result:
            return granite_result
        log.warning("Granite returned unrecognised category %r — using keyword fallback", word)
    except (WatsonxError, IndexError, ValueError) as exc:
        log.warning("Need classification failed (%s) — using keyword fallback", exc)
    return _keyword_classify(raw_text)


# ---------------------------------------------------------------------------
# Urgency score formula
# ---------------------------------------------------------------------------

# Need-category weights (used in prioritization, not in urgency score itself)
NEED_WEIGHTS = {
    NeedCategory.rescue:  1.0,
    NeedCategory.medical: 0.9,
    NeedCategory.water:   0.7,
    NeedCategory.food:    0.5,
    None:                 0.5,
}


def _isolation_score(incident_id: int) -> float:
    """Return 1.0 if any village linked to the incident is isolated, else 0.0."""
    # Heuristic: check accessibility results for villages near the incident
    # location (linked via AccessibilityResult → village → incident lat/lng match).
    # For simplicity, we check whether ANY isolated village exists in the system.
    # A more precise version would geo-match; this is sufficient for MVP.
    incident = db.session.get(Incident, incident_id)
    if incident is None or incident.lat is None or incident.lng is None:
        return 0.0

    from backend.models.village import Village
    import math

    villages = db.session.scalars(select(Village)).all()
    for village in villages:
        dist = math.sqrt(
            (village.lat - incident.lat) ** 2 + (village.lng - incident.lng) ** 2
        )
        if dist > 1.0:   # roughly >100 km — skip distant villages
            continue
        result = db.session.scalar(
            select(AccessibilityResult)
            .where(AccessibilityResult.village_id == village.id)
            .order_by(AccessibilityResult.computed_at.desc())
            .limit(1)
        )
        if result and result.is_isolated:
            return 1.0
    return 0.0


def _severity_score(incident: Incident) -> float:
    if incident.severity is None:
        return 0.0
    return min(incident.severity, 5) / 5.0


def _household_score(incident: Incident) -> float:
    if incident.affected_households is None:
        return 0.0
    return min(incident.affected_households, 500) / 500.0


def compute_urgency(
    incident: Incident,
    isolation: float,
    severity: float,
    household: float,
) -> tuple[float, float, float, float]:
    """Return (urgency_score 1-10, isolation_w, severity_w, household_w)."""
    raw = 0.4 * isolation + 0.3 * severity + 0.3 * household
    score = max(1.0, min(10.0, raw * 10))
    return round(score, 2), round(isolation, 4), round(severity, 4), round(household, 4)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_relief_assessment(
    raw_text: str,
    incident_id: int,
    requester_id: int | None = None,
) -> ReliefRequest:
    """Classify need and score urgency; persist and return a ReliefRequest.

    Parameters
    ----------
    raw_text:    Free-text from the citizen relief request.
    incident_id: Parent incident (must exist).
    requester_id: FK to users.id or None for anonymous.
    """
    incident = db.session.get(Incident, incident_id)
    if incident is None:
        raise ValueError(f"Incident {incident_id} not found")

    # ── 1. Classify need via Granite ──────────────────────────────────────
    need_category = _classify_need(raw_text)

    # ── 2. Compute urgency score ──────────────────────────────────────────
    isolation  = _isolation_score(incident_id)
    severity   = _severity_score(incident)
    household  = _household_score(incident)
    urgency, iso_w, sev_w, hh_w = compute_urgency(incident, isolation, severity, household)

    # ── 3. Persist ────────────────────────────────────────────────────────
    relief = ReliefRequest(
        incident_id=incident_id,
        requester_id=requester_id,
        raw_text=raw_text,
        need_category=need_category,
        urgency_score=urgency,
        isolation_weight=iso_w,
        severity_weight=sev_w,
        household_weight=hh_w,
    )
    db.session.add(relief)
    db.session.commit()

    log.info(
        "ReliefRequest %d created: category=%s urgency=%.2f",
        relief.id, need_category, urgency,
    )
    return relief
