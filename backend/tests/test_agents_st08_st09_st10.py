"""
backend/tests/test_agents_st08_st09_st10.py
Tests for ST-08 (Relief Assessment), ST-09 (Prioritization), ST-10 (Briefing).
All Granite / watsonx calls are mocked.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from backend.agents.relief_assessment_agent import (
    NEED_WEIGHTS,
    _classify_need,
    _household_score,
    _severity_score,
    compute_urgency,
    run_relief_assessment,
)
from backend.agents.prioritization_agent import (
    _compute_score,
    get_ranked_requests,
    run_prioritization,
    score_relief_request,
)
from backend.agents.briefing_agent import (
    DISCLAIMER,
    _build_summary_prompt,
    _render_html,
    generate_briefing,
)
from backend.app import create_app, db
from backend.models.incident import Incident, IncidentStatus, IncidentType
from backend.models.prioritization_score import PrioritizationScore
from backend.models.relief_request import NeedCategory, ReliefRequest
from backend.models.briefing import Briefing


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


def _make_incident(app, severity=4, households=100, status=IncidentStatus.verified):
    with app.app_context():
        inc = Incident(
            raw_text="Flood at Hornadu",
            status=status,
            location_name="Hornadu",
            lat=13.3876, lng=75.1951,
            incident_type=IncidentType.flood,
            severity=severity,
            affected_households=households,
            structured_json={"location_name": "Hornadu", "incident_type": "flood", "severity": severity},
        )
        db.session.add(inc)
        db.session.commit()
        return inc.id


# ---------------------------------------------------------------------------
# ST-08 — Relief Assessment unit tests
# ---------------------------------------------------------------------------

class TestReliefAssessmentFormulas:
    def test_severity_score_max(self):
        inc = Incident(severity=5)
        assert _severity_score(inc) == pytest.approx(1.0)

    def test_severity_score_zero(self):
        inc = Incident(severity=None)
        assert _severity_score(inc) == 0.0

    def test_severity_score_mid(self):
        inc = Incident(severity=3)
        assert _severity_score(inc) == pytest.approx(0.6)

    def test_household_score_capped(self):
        inc = Incident(affected_households=1000)
        assert _household_score(inc) == pytest.approx(1.0)

    def test_household_score_zero(self):
        inc = Incident(affected_households=None)
        assert _household_score(inc) == 0.0

    def test_household_score_250(self):
        inc = Incident(affected_households=250)
        assert _household_score(inc) == pytest.approx(0.5)

    def test_compute_urgency_fully_isolated_max_severity(self):
        inc = Incident(severity=5, affected_households=500)
        score, iso_w, sev_w, hh_w = compute_urgency(inc, 1.0, 1.0, 1.0)
        assert score == pytest.approx(10.0)

    def test_compute_urgency_minimum(self):
        inc = Incident(severity=None, affected_households=None)
        score, _, _, _ = compute_urgency(inc, 0.0, 0.0, 0.0)
        assert score == pytest.approx(1.0)   # clamped to 1

    def test_need_weights_rescue_highest(self):
        assert NEED_WEIGHTS[NeedCategory.rescue] > NEED_WEIGHTS[NeedCategory.food]

    def test_classify_need_mocked(self):
        with patch("backend.agents.relief_assessment_agent.generate", return_value="medical"):
            result = _classify_need("We need a doctor urgently")
        assert result == NeedCategory.medical

    def test_classify_need_watsonx_failure_uses_fallback(self):
        from backend.utils.watsonx_client import WatsonxError
        with patch("backend.agents.relief_assessment_agent.generate",
                   side_effect=WatsonxError("fail")):
            result = _classify_need("we need food supplies")
        # Keyword fallback kicks in — always returns a NeedCategory, never None
        assert result is not None
        assert result == NeedCategory.food


class TestRunReliefAssessment:
    def test_creates_relief_request(self, app):
        inc_id = _make_incident(app)
        with patch("backend.agents.relief_assessment_agent.generate", return_value="food"):
            with app.app_context():
                relief = run_relief_assessment(
                    "We need food supplies for 50 families", inc_id
                )
                rid = relief.id
                cat = relief.need_category
                score = relief.urgency_score

        assert rid is not None
        assert cat == NeedCategory.food
        assert 1.0 <= score <= 10.0

    def test_missing_incident_raises(self, app):
        with patch("backend.agents.relief_assessment_agent.generate", return_value="water"):
            with app.app_context():
                with pytest.raises(ValueError, match="not found"):
                    run_relief_assessment("Need water", 99999)


# ---------------------------------------------------------------------------
# ST-09 — Prioritization unit tests
# ---------------------------------------------------------------------------

class TestComputeScore:
    def test_isolated_rescue_max_severity(self):
        composite, iso_c, sev_c, hh_c, need_c = _compute_score(
            is_isolated=True,
            severity=5,
            affected_households=500,
            need_category=NeedCategory.rescue,
        )
        # 0.4*1 + 0.3*1 + 0.2*1 + 0.1*1 = 1.0
        assert composite == pytest.approx(1.0)
        assert iso_c == 1.0
        assert sev_c == 1.0
        assert hh_c == 1.0
        assert need_c == 1.0

    def test_not_isolated_food_zero_severity(self):
        composite, _, _, _, _ = _compute_score(
            is_isolated=False,
            severity=None,
            affected_households=None,
            need_category=NeedCategory.food,
        )
        # 0.4*0 + 0.3*0 + 0.2*0 + 0.1*0.5 = 0.05
        assert composite == pytest.approx(0.05)

    def test_severity_normalised_correctly(self):
        _, _, sev_c, _, _ = _compute_score(
            is_isolated=False, severity=3, affected_households=None,
            need_category=None,
        )
        assert sev_c == pytest.approx(0.6)

    def test_households_capped_at_500(self):
        _, _, _, hh_c, _ = _compute_score(
            is_isolated=False, severity=None, affected_households=1000,
            need_category=None,
        )
        assert hh_c == pytest.approx(1.0)


class TestRunPrioritization:
    def test_scores_unscored_requests(self, app):
        inc_id = _make_incident(app)
        with patch("backend.agents.relief_assessment_agent.generate", return_value="rescue"):
            with patch("backend.agents.prioritization_agent.generate",
                       return_value="High priority rescue needed."):
                with app.app_context():
                    relief = run_relief_assessment(
                        "Rescue needed immediately for 20 families", inc_id
                    )
                    scores = run_prioritization()
                    assert len(scores) == 1
                    assert scores[0].relief_request_id == relief.id

    def test_does_not_score_already_scored(self, app):
        inc_id = _make_incident(app)
        with patch("backend.agents.relief_assessment_agent.generate", return_value="water"):
            with patch("backend.agents.prioritization_agent.generate",
                       return_value="Water priority."):
                with app.app_context():
                    relief = run_relief_assessment("Need water for 100 people", inc_id)
                    run_prioritization()
                    # Second run should score 0 new
                    new_scores = run_prioritization()
                    assert new_scores == []

    def test_get_ranked_requests_order(self, app):
        """Higher composite score appears first."""
        inc_id = _make_incident(app, severity=5, households=500)
        inc_id_low = _make_incident(app, severity=1, households=10)
        with patch("backend.agents.relief_assessment_agent.generate", return_value="rescue"):
            with patch("backend.agents.prioritization_agent.generate", return_value="Rationale."):
                with app.app_context():
                    run_relief_assessment("Rescue critically needed!", inc_id)
                    run_relief_assessment("Minor food request", inc_id_low)
                    run_prioritization()
                    ranked = get_ranked_requests()

        assert ranked[0]["composite_score"] >= ranked[-1]["composite_score"]


# ---------------------------------------------------------------------------
# ST-10 — Briefing unit tests
# ---------------------------------------------------------------------------

class TestBriefingHelpers:
    def test_disclaimer_present_in_html(self):
        snapshot = {
            "generated_at": "2024-08-01T10:00:00",
            "incident_counts": {"total": 5, "verified": 3, "pending": 2},
            "isolated_village_count": 1,
            "isolated_villages": [{"name": "Hornadu", "id": 1}],
            "top_relief_requests": [],
        }
        html = _render_html(snapshot, "Test summary", "Priya")
        assert DISCLAIMER in html
        # Disclaimer must NOT be in a script tag or generated by LLM
        assert "DISCLAIMER" in html

    def test_disclaimer_not_empty(self):
        assert len(DISCLAIMER) > 50

    def test_summary_prompt_includes_counts(self):
        snapshot = {
            "generated_at": "2024-08-01T10:00:00",
            "incident_counts": {"total": 10, "verified": 7, "pending": 3},
            "isolated_village_count": 2,
            "isolated_villages": [{"name": "Hornadu", "id": 1}, {"name": "Kalasa", "id": 2}],
            "top_relief_requests": [
                {"relief_id": 1, "score": 0.9, "category": "rescue",
                 "location": "Hornadu", "severity": 5}
            ],
        }
        prompt = _build_summary_prompt(snapshot)
        assert "10" in prompt   # total incidents
        assert "Hornadu" in prompt
        assert "rescue" in prompt

    def test_render_html_relief_rows(self):
        snapshot = {
            "generated_at": "2024-08-01T10:00:00",
            "incident_counts": {"total": 1, "verified": 1, "pending": 0},
            "isolated_village_count": 0,
            "isolated_villages": [],
            "top_relief_requests": [
                {"relief_id": 1, "score": 0.75, "category": "food",
                 "location": "Kalasa", "severity": 3}
            ],
        }
        html = _render_html(snapshot, "Summary text.", "Test Coord")
        assert "food" in html
        assert "Kalasa" in html
        assert "0.750" in html


class TestGenerateBriefing:
    def test_briefing_persisted(self, app):
        with patch("backend.agents.briefing_agent.generate",
                   return_value="Good situation summary."):
            with app.app_context():
                b = generate_briefing(generated_by_id=None)
                b_id = b.id
                summary = b.summary_text

        assert b_id is not None
        assert "Good situation summary." in summary

        with app.app_context():
            persisted = db.session.get(Briefing, b_id)
            assert persisted is not None

    def test_disclaimer_in_persisted_snapshot(self, app):
        """Briefing summary_text must NOT contain the disclaimer — it's in HTML only."""
        with patch("backend.agents.briefing_agent.generate",
                   return_value="Situation looks manageable."):
            with app.app_context():
                b = generate_briefing()
                # The LLM output is the summary_text; disclaimer is separate
                assert DISCLAIMER not in b.summary_text

    def test_watsonx_failure_still_persists_briefing(self, app):
        from backend.utils.watsonx_client import WatsonxError
        with patch("backend.agents.briefing_agent.generate",
                   side_effect=WatsonxError("unavailable")):
            with app.app_context():
                b = generate_briefing()
                b_id = b.id
                has_fallback = "unavailable" in b.summary_text or "AI summary" in b.summary_text

        assert b_id is not None
        assert has_fallback
