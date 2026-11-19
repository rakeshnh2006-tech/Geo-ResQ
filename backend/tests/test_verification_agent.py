"""
backend/tests/test_verification_agent.py
Tests for ST-06 — Verification Agent.
Granite similarity calls are mocked throughout.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from backend.agents.verification_agent import (
    _check_completeness,
    _check_conflict,
    _check_duplicate,
    _cosine_tfidf,
    _haversine_km,
    run_verification,
)
from backend.app import create_app, db
from backend.models.incident import Incident, IncidentStatus, IncidentType
from backend.models.verification import Verification, VerificationStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        import backend.models
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _make_incident(app, **kwargs) -> Incident:
    defaults = dict(
        raw_text="Flood at Hornadu village, 85 households affected.",
        status=IncidentStatus.pending,
        location_name="Hornadu",
        lat=13.3876,
        lng=75.1951,
        incident_type=IncidentType.flood,
        severity=4,
        affected_households=85,
        structured_json={
            "location_name": "Hornadu",
            "incident_type": "flood",
            "severity": 4,
        },
        created_at=datetime(2024, 8, 1, 10, 0),
    )
    defaults.update(kwargs)
    with app.app_context():
        inc = Incident(**defaults)
        db.session.add(inc)
        db.session.commit()
        return db.session.get(Incident, inc.id)


# ---------------------------------------------------------------------------
# Unit tests — pure functions
# ---------------------------------------------------------------------------

class TestHaversineKm:
    def test_zero_distance(self):
        assert _haversine_km(13.0, 75.0, 13.0, 75.0) == pytest.approx(0.0, abs=0.01)

    def test_known_pair_within_5km(self):
        # Kalasa (13.3419, 75.3611) to point ~2 km away
        d = _haversine_km(13.3419, 75.3611, 13.3600, 75.3611)
        assert d < 5.0

    def test_known_pair_beyond_5km(self):
        # Shimoga → Chikmagalur ≈ 79 km
        d = _haversine_km(14.0027, 75.5681, 13.3153, 75.7754)
        assert d > 5.0


class TestCosineTfidf:
    def test_identical_texts(self):
        t = "flooding at hornadu village road blocked"
        assert _cosine_tfidf(t, t) == pytest.approx(1.0)

    def test_completely_different_texts(self):
        a = "flood water rising in hornadu"
        b = "bridge collapse shimoga infrastructure"
        sim = _cosine_tfidf(a, b)
        assert sim < 0.5

    def test_empty_strings(self):
        assert _cosine_tfidf("", "") == 0.0

    def test_partial_overlap(self):
        a = "flood at hornadu village"
        b = "flood near hornadu town"
        sim = _cosine_tfidf(a, b)
        assert 0.3 < sim < 1.0


class TestCheckCompleteness:
    def test_complete_incident(self):
        inc = Incident(
            raw_text="x",
            location_name="Hornadu",
            incident_type=IncidentType.flood,
            severity=4,
            structured_json={"location_name": "Hornadu", "incident_type": "flood", "severity": 4},
        )
        is_complete, missing = _check_completeness(inc)
        assert is_complete is True
        assert missing == []

    def test_missing_severity(self):
        inc = Incident(
            raw_text="x",
            location_name="Hornadu",
            incident_type=IncidentType.flood,
            severity=None,
            structured_json={"location_name": "Hornadu", "incident_type": "flood"},
        )
        is_complete, missing = _check_completeness(inc)
        assert is_complete is False
        assert "severity" in missing

    def test_all_missing(self):
        inc = Incident(raw_text="x", structured_json={})
        is_complete, missing = _check_completeness(inc)
        assert is_complete is False
        assert len(missing) == 3


class TestCheckConflict:
    def _inc(self, severity):
        return Incident(raw_text="x", severity=severity)

    def test_no_conflict_similar_severity(self):
        inc = self._inc(4)
        candidate = self._inc(3)
        has_conflict, detail = _check_conflict(inc, [candidate])
        assert has_conflict is False

    def test_conflict_large_delta(self):
        inc = self._inc(5)
        candidate = self._inc(1)
        has_conflict, detail = _check_conflict(inc, [candidate])
        assert has_conflict is True
        assert "delta=4" in detail

    def test_no_conflict_no_candidates(self):
        inc = self._inc(4)
        has_conflict, _ = _check_conflict(inc, [])
        assert has_conflict is False

    def test_no_conflict_severity_none(self):
        inc = Incident(raw_text="x", severity=None)
        candidate = self._inc(5)
        has_conflict, _ = _check_conflict(inc, [candidate])
        assert has_conflict is False


class TestCheckDuplicate:
    def test_no_candidates(self):
        inc = Incident(raw_text="flood at hornadu")
        is_dup, dup_id, sim = _check_duplicate(inc, [])
        assert is_dup is False
        assert dup_id is None

    def test_high_similarity_flags_duplicate(self):
        inc = Incident(raw_text="flood at hornadu village, 50 houses")
        candidate = Incident(id=99, raw_text="flood at hornadu village, 50 houses")
        with patch("backend.agents.verification_agent._granite_similarity", return_value=0.95):
            is_dup, dup_id, sim = _check_duplicate(inc, [candidate])
        assert is_dup is True
        assert dup_id == 99
        assert sim == pytest.approx(0.95)

    def test_low_similarity_not_duplicate(self):
        inc = Incident(raw_text="flood at hornadu")
        candidate = Incident(id=10, raw_text="landslide near shimoga bridge")
        with patch("backend.agents.verification_agent._granite_similarity", return_value=0.3):
            is_dup, dup_id, sim = _check_duplicate(inc, [candidate])
        assert is_dup is False


# ---------------------------------------------------------------------------
# run_verification integration tests
# ---------------------------------------------------------------------------

class TestRunVerification:
    def test_clean_incident_becomes_verified(self, app):
        inc = _make_incident(app)
        with patch("backend.agents.verification_agent._granite_similarity", return_value=0.1):
            with app.app_context():
                inc = db.session.get(Incident, inc.id)
                v = run_verification(inc)
                v_status = v.status
                inc_status = db.session.get(Incident, inc.id).status

        assert v_status == VerificationStatus.passed
        assert inc_status == IncidentStatus.verified

    def test_incomplete_incident_stays_incomplete(self, app):
        inc = _make_incident(
            app,
            location_name=None,
            incident_type=None,
            severity=None,
            structured_json={},
        )
        with app.app_context():
            inc = db.session.get(Incident, inc.id)
            v = run_verification(inc)
            v_status = v.status
            v_complete = v.is_complete
            inc_status = db.session.get(Incident, inc.id).status

        assert v_status == VerificationStatus.incomplete
        assert v_complete is False
        assert inc_status == IncidentStatus.incomplete

    def test_duplicate_incident_flagged(self, app):
        existing = _make_incident(
            app,
            raw_text="Flooding at Hornadu, 85 households.",
            created_at=datetime(2024, 8, 1, 9, 30),
        )
        new_inc = _make_incident(
            app,
            raw_text="Flood in Hornadu village, many families affected.",
            created_at=datetime(2024, 8, 1, 10, 0),
        )

        with patch("backend.agents.verification_agent._granite_similarity", return_value=0.92):
            with app.app_context():
                new_inc = db.session.get(Incident, new_inc.id)
                v = run_verification(new_inc)
                v_status = v.status
                v_is_dup = v.is_duplicate
                inc_status = db.session.get(Incident, new_inc.id).status

        assert v_status == VerificationStatus.duplicate
        assert v_is_dup is True
        assert inc_status == IncidentStatus.duplicate

    def test_conflict_incident_stays_pending(self, app):
        _make_incident(
            app,
            severity=1,
            created_at=datetime(2024, 8, 1, 9, 0),
        )
        new_inc = _make_incident(
            app,
            severity=5,
            raw_text="Major catastrophic flood, all roads blocked.",
            created_at=datetime(2024, 8, 1, 10, 0),
        )

        with patch("backend.agents.verification_agent._granite_similarity", return_value=0.3):
            with app.app_context():
                new_inc = db.session.get(Incident, new_inc.id)
                v = run_verification(new_inc)
                v_status = v.status
                v_conflict = v.has_conflict
                inc_status = db.session.get(Incident, new_inc.id).status

        assert v_status == VerificationStatus.conflict
        assert v_conflict is True
        assert inc_status == IncidentStatus.pending

    def test_verification_row_persisted(self, app):
        inc = _make_incident(app)
        with patch("backend.agents.verification_agent._granite_similarity", return_value=0.1):
            with app.app_context():
                inc = db.session.get(Incident, inc.id)
                v = run_verification(inc)
                v_id = v.id

        with app.app_context():
            persisted = db.session.get(Verification, v_id)
            assert persisted is not None
            assert persisted.incident_id == inc.id
