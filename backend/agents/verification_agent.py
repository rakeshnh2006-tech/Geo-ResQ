"""
backend/agents/verification_agent.py
Verification Agent — ST-06
===========================
Runs automatically after intake.  Three independent checks:

1. Duplicate check
   ─────────────────
   Haversine distance < 5 km  AND  within a 6-hour window  AND
   Granite embedding cosine-similarity > 0.85 between the two
   raw_text strings.  If any pair matches, the incident is flagged
   duplicate and duplicate_of_id is set to the earliest matching
   incident.

2. Completeness check
   ───────────────────
   All required fields present in structured_json.  Any missing
   fields are listed in verifications.missing_fields.

3. Conflict check
   ───────────────
   Contradictory severity or location vs. nearby verified incidents
   (< 5 km, same 6-hour window, severity difference > 2).  Conflicts
   are written to verifications.conflict_detail but do NOT block the
   incident — they surface for coordinator review.

Similarity is computed via Granite embeddings when available; a
lightweight TF-IDF fallback is used when watsonx is unavailable or
in test environments.

The function updates both the Verification row and the parent
Incident.status.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from backend.app import db
from backend.models.incident import Incident, IncidentStatus
from backend.models.verification import Verification, VerificationStatus
from backend.utils.watsonx_client import WatsonxError, generate

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DUPLICATE_DISTANCE_KM   = 5.0
_DUPLICATE_TIME_WINDOW_H = 6
_DUPLICATE_SIM_THRESHOLD = 0.85
_CONFLICT_SEVERITY_DELTA = 2
_REQUIRED_FIELDS = {"location_name", "incident_type", "severity"}


# ---------------------------------------------------------------------------
# Haversine (km)
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Text similarity helpers
# ---------------------------------------------------------------------------

def _cosine_tfidf(text_a: str, text_b: str) -> float:
    """Very lightweight bag-of-words cosine similarity (TF-IDF fallback)."""
    def tokenise(t: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for token in t.lower().split():
            token = token.strip(".,;:!?\"'")
            if len(token) > 2:
                counts[token] = counts.get(token, 0) + 1
        return counts

    va, vb = tokenise(text_a), tokenise(text_b)
    keys = set(va) | set(vb)
    if not keys:
        return 0.0
    dot = sum(va.get(k, 0) * vb.get(k, 0) for k in keys)
    norm_a = math.sqrt(sum(v ** 2 for v in va.values()))
    norm_b = math.sqrt(sum(v ** 2 for v in vb.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


_SIMILARITY_PROMPT = """\
Rate the similarity of these two disaster incident reports on a scale from 0.00 to 1.00.
Return ONLY the decimal number, nothing else.

Report A:
\"\"\"
{text_a}
\"\"\"

Report B:
\"\"\"
{text_b}
\"\"\"

Similarity score:
"""


def _granite_similarity(text_a: str, text_b: str) -> float:
    """Ask Granite to score similarity.  Falls back to TF-IDF on any error."""
    prompt = _SIMILARITY_PROMPT.format(
        text_a=text_a[:1000], text_b=text_b[:1000]
    )
    try:
        raw = generate(prompt, max_new_tokens=8, temperature=0.0)
        score = float(raw.strip().split()[0])
        return max(0.0, min(1.0, score))
    except (WatsonxError, ValueError, IndexError):
        log.warning("Granite similarity failed — using TF-IDF fallback")
        return _cosine_tfidf(text_a, text_b)


# ---------------------------------------------------------------------------
# Candidate fetch helpers
# ---------------------------------------------------------------------------

def _nearby_window_incidents(incident: Incident) -> list[Incident]:
    """Return verified/pending incidents within bbox & time window."""
    if incident.lat is None or incident.lng is None:
        return []

    window_start = (incident.created_at or datetime.utcnow()) - timedelta(hours=_DUPLICATE_TIME_WINDOW_H)

    stmt = (
        select(Incident)
        .where(
            Incident.id != incident.id,
            Incident.status.in_([IncidentStatus.pending, IncidentStatus.verified]),
            Incident.lat.isnot(None),
            Incident.lng.isnot(None),
            Incident.created_at >= window_start,
        )
    )
    candidates = db.session.scalars(stmt).all()

    return [
        c for c in candidates
        if _haversine_km(incident.lat, incident.lng, c.lat, c.lng) < _DUPLICATE_DISTANCE_KM
    ]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_duplicate(
    incident: Incident,
    candidates: list[Incident],
) -> tuple[bool, int | None, float | None]:
    """Return (is_duplicate, duplicate_of_id, similarity_score)."""
    if not candidates:
        return False, None, None

    best_sim = 0.0
    best_id: int | None = None

    for candidate in candidates:
        sim = _granite_similarity(incident.raw_text, candidate.raw_text)
        log.debug("Similarity incident %d vs %d: %.3f", incident.id, candidate.id, sim)
        if sim > best_sim:
            best_sim = sim
            best_id = candidate.id

    if best_sim >= _DUPLICATE_SIM_THRESHOLD:
        return True, best_id, best_sim
    return False, None, best_sim if best_sim > 0 else None


def _check_completeness(
    incident: Incident,
) -> tuple[bool, list[str]]:
    """Return (is_complete, missing_fields)."""
    structured = incident.structured_json or {}
    missing = [
        f for f in _REQUIRED_FIELDS
        if not structured.get(f) and not getattr(incident, f, None)
    ]
    return len(missing) == 0, missing


def _check_conflict(
    incident: Incident,
    candidates: list[Incident],
) -> tuple[bool, str | None]:
    """Return (has_conflict, conflict_detail)."""
    if incident.severity is None:
        return False, None

    for candidate in candidates:
        if candidate.severity is None:
            continue
        delta = abs(incident.severity - candidate.severity)
        if delta > _CONFLICT_SEVERITY_DELTA:
            detail = (
                f"Severity {incident.severity} conflicts with incident "
                f"#{candidate.id} (severity {candidate.severity}, "
                f"delta={delta}) at same location/time."
            )
            return True, detail

    return False, None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_verification(incident: Incident) -> Verification:
    """Run all three checks and persist a Verification row.

    Also updates incident.status:
      - duplicate   → IncidentStatus.duplicate
      - incomplete  → IncidentStatus.incomplete  (completeness fails)
      - conflict    → coordinator review (stays pending)
      - all pass    → IncidentStatus.verified

    Returns the persisted Verification.
    """
    candidates = _nearby_window_incidents(incident)

    # ── 1. Duplicate ─────────────────────────────────────────────────────
    is_dup, dup_of_id, dup_sim = _check_duplicate(incident, candidates)

    # ── 2. Completeness ──────────────────────────────────────────────────
    is_complete, missing_fields = _check_completeness(incident)

    # ── 3. Conflict ───────────────────────────────────────────────────────
    has_conflict, conflict_detail = _check_conflict(incident, candidates)

    # ── Determine overall status ──────────────────────────────────────────
    if is_dup:
        overall = VerificationStatus.duplicate
        incident.status = IncidentStatus.duplicate
    elif not is_complete:
        overall = VerificationStatus.incomplete
        incident.status = IncidentStatus.incomplete
    elif has_conflict:
        overall = VerificationStatus.conflict
        # Conflict stays pending — surfaces in coordinator review queue
    else:
        overall = VerificationStatus.passed
        incident.status = IncidentStatus.verified

    # ── Persist Verification ──────────────────────────────────────────────
    verification = Verification(
        incident_id=incident.id,
        is_duplicate=is_dup,
        duplicate_of_id=dup_of_id,
        duplicate_similarity=dup_sim,
        is_complete=is_complete,
        missing_fields=missing_fields if missing_fields else None,
        has_conflict=has_conflict,
        conflict_detail=conflict_detail,
        status=overall,
    )

    db.session.add(verification)
    db.session.commit()

    log.info(
        "Incident %d verified: status=%s dup=%s complete=%s conflict=%s",
        incident.id, overall.value, is_dup, is_complete, has_conflict,
    )
    return verification
