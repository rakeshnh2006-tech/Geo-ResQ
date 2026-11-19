"""
backend/agents/prioritization_agent.py
Prioritization Agent — ST-09
==============================
Deterministic composite score — NO LLM for the number itself.

Formula (matches plan spec):
  score = 0.4*(isolated?) + 0.3*(severity/5) + 0.2*(min(households,500)/500)
          + 0.1*(need_weight)

need_weight per category:
  rescue: 1.0 | medical: 0.9 | water: 0.7 | food: 0.5 | unknown: 0.5

Granite is called ONLY to write a natural-language rationale string.

Public API
----------
run_prioritization()         — score all un-scored ReliefRequests
get_ranked_requests()        — return all PrioritizationScore rows, ranked
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from backend.agents.relief_assessment_agent import NEED_WEIGHTS
from backend.app import db
from backend.models.incident import Incident
from backend.models.prioritization_score import PrioritizationScore
from backend.models.relief_request import NeedCategory, ReliefRequest
from backend.utils.watsonx_client import WatsonxError, generate

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Score components
# ---------------------------------------------------------------------------

def _compute_score(
    is_isolated: bool,
    severity: int | None,
    affected_households: int | None,
    need_category: NeedCategory | None,
) -> tuple[float, float, float, float, float]:
    """Return (composite, isolation_c, severity_c, household_c, need_c)."""
    isolation_c  = 1.0 if is_isolated else 0.0
    severity_c   = (min(severity, 5) / 5.0) if severity is not None else 0.0
    household_c  = (min(affected_households, 500) / 500.0) if affected_households else 0.0
    need_c       = NEED_WEIGHTS.get(need_category, 0.5)

    composite = (
        0.4 * isolation_c +
        0.3 * severity_c  +
        0.2 * household_c +
        0.1 * need_c
    )
    return (
        round(composite, 4),
        round(isolation_c, 4),
        round(severity_c, 4),
        round(household_c, 4),
        round(need_c, 4),
    )


# ---------------------------------------------------------------------------
# Granite rationale
# ---------------------------------------------------------------------------

_RATIONALE_PROMPT = """\
You are a disaster-response coordinator assistant.
Write a concise 2–3 sentence explanation for why the following relief \
request has been prioritized with a score of {score:.2f} out of 1.0.

Context:
- Village isolated: {isolated}
- Incident severity: {severity}/5
- Affected households: {households}
- Need category: {category}

Rationale:
"""


def _generate_rationale(
    score: float,
    is_isolated: bool,
    severity: int | None,
    households: int | None,
    category: str | None,
) -> str | None:
    prompt = _RATIONALE_PROMPT.format(
        score=score,
        isolated="Yes" if is_isolated else "No",
        severity=severity or "unknown",
        households=households or "unknown",
        category=category or "unknown",
    )
    try:
        return generate(prompt, max_new_tokens=120, temperature=0.3)
    except WatsonxError as exc:
        log.warning("Rationale generation failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Isolation lookup helper
# ---------------------------------------------------------------------------

def _incident_is_isolated(incident: Incident) -> bool:
    """Return True if any nearby village is currently isolated."""
    from backend.models.accessibility_result import AccessibilityResult
    from backend.models.village import Village
    import math

    if incident.lat is None or incident.lng is None:
        return False

    villages = db.session.scalars(select(Village)).all()
    for v in villages:
        dist = math.sqrt((v.lat - incident.lat) ** 2 + (v.lng - incident.lng) ** 2)
        if dist > 1.0:
            continue
        result = db.session.scalar(
            select(AccessibilityResult)
            .where(AccessibilityResult.village_id == v.id)
            .order_by(AccessibilityResult.computed_at.desc())
            .limit(1)
        )
        if result and result.is_isolated:
            return True
    return False


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def score_relief_request(relief: ReliefRequest) -> PrioritizationScore:
    """Compute and persist a PrioritizationScore for a single ReliefRequest."""
    incident = db.session.get(Incident, relief.incident_id)
    is_isolated = _incident_is_isolated(incident) if incident else False

    composite, iso_c, sev_c, hh_c, need_c = _compute_score(
        is_isolated=is_isolated,
        severity=incident.severity if incident else None,
        affected_households=incident.affected_households if incident else None,
        need_category=relief.need_category,
    )

    rationale = _generate_rationale(
        score=composite,
        is_isolated=is_isolated,
        severity=incident.severity if incident else None,
        households=incident.affected_households if incident else None,
        category=relief.need_category.value if relief.need_category else None,
    )

    ps = PrioritizationScore(
        relief_request_id=relief.id,
        composite_score=composite,
        isolation_component=iso_c,
        severity_component=sev_c,
        household_component=hh_c,
        need_component=need_c,
        rationale=rationale,
    )
    db.session.add(ps)
    db.session.commit()
    log.info("PrioritizationScore for relief %d: %.4f", relief.id, composite)
    return ps


def run_prioritization() -> list[PrioritizationScore]:
    """Score all ReliefRequests that do not yet have a PrioritizationScore."""
    # Find relief requests without a score
    scored_ids = db.session.scalars(
        select(PrioritizationScore.relief_request_id)
    ).all()
    stmt = select(ReliefRequest)
    if scored_ids:
        stmt = stmt.where(ReliefRequest.id.notin_(scored_ids))

    unscored = db.session.scalars(stmt).all()
    scores = []
    for relief in unscored:
        scores.append(score_relief_request(relief))
    log.info("Prioritization run: scored %d requests", len(scores))
    return scores


def get_ranked_requests() -> list[dict]:
    """Return all relief requests ranked by composite score descending."""
    rows = db.session.scalars(
        select(PrioritizationScore)
        .order_by(PrioritizationScore.composite_score.desc())
    ).all()
    result = []
    for ps in rows:
        relief = db.session.get(ReliefRequest, ps.relief_request_id)
        result.append({
            **ps.to_dict(),
            "relief_request": relief.to_dict() if relief else None,
        })
    return result
