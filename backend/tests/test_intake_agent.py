"""
backend/tests/test_intake_agent.py
Tests for ST-05 — Incident Intake Agent.
watsonx.ai is mocked throughout; no external calls are made.
"""
from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from backend.agents.intake_agent import (
    ExtractedIncident,
    _build_prompt,
    _extract_json,
    _missing_required,
    _parse_report_time,
    run_intake,
)
from backend.app import create_app, db
from backend.models.incident import Incident, IncidentStatus, IncidentType
from backend.models.user import User, UserRole


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


# ---------------------------------------------------------------------------
# ExtractedIncident validation
# ---------------------------------------------------------------------------

class TestExtractedIncident:
    def test_valid_full(self):
        e = ExtractedIncident.model_validate({
            "location_name": "Kalasa",
            "lat": 13.34,
            "lng": 75.36,
            "incident_type": "flood",
            "severity": 4,
            "affected_households": 120,
            "report_time": "2024-08-01T10:00:00",
        })
        assert e.location_name == "Kalasa"
        assert e.severity == 4
        assert e.incident_type == "flood"

    def test_severity_out_of_range_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ExtractedIncident.model_validate({"severity": 6})

    def test_incident_type_normalised(self):
        e = ExtractedIncident.model_validate({"incident_type": "rockslide"})
        assert e.incident_type == "landslide"

    def test_unknown_type_becomes_other(self):
        e = ExtractedIncident.model_validate({"incident_type": "volcano"})
        assert e.incident_type == "other"

    def test_nulls_allowed(self):
        e = ExtractedIncident.model_validate({})
        assert e.location_name is None
        assert e.severity is None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_extract_json_finds_object(self):
        raw = 'some text {"key": "value", "num": 1} trailing'
        result = _extract_json(raw)
        assert result == {"key": "value", "num": 1}

    def test_extract_json_raises_on_no_object(self):
        with pytest.raises(ValueError, match="No JSON"):
            _extract_json("no braces here")

    def test_extract_json_nested(self):
        raw = '{"a": {"b": 1}, "c": null}'
        result = _extract_json(raw)
        assert result["a"]["b"] == 1

    def test_missing_required_all_missing(self):
        e = ExtractedIncident.model_validate({})
        missing = _missing_required(e)
        assert set(missing) == {"location_name", "incident_type", "severity"}

    def test_missing_required_none_missing(self):
        e = ExtractedIncident.model_validate({
            "location_name": "X", "incident_type": "flood", "severity": 3
        })
        assert _missing_required(e) == []

    def test_parse_report_time_iso(self):
        dt = _parse_report_time("2024-08-01T10:00:00")
        assert dt.year == 2024 and dt.month == 8

    def test_parse_report_time_date_only(self):
        dt = _parse_report_time("2024-08-01")
        assert dt.day == 1

    def test_parse_report_time_none(self):
        assert _parse_report_time(None) is None

    def test_parse_report_time_invalid_returns_none(self):
        assert _parse_report_time("not-a-date") is None

    def test_build_prompt_contains_raw_text(self):
        prompt = _build_prompt("There is flooding at Hornadu village.")
        assert "Hornadu" in prompt
        assert "JSON:" in prompt

    def test_build_prompt_truncates_long_text(self):
        long_text = "x" * 5000
        prompt = _build_prompt(long_text)
        assert len(prompt) < 5000 + 500   # prompt template adds some overhead


# ---------------------------------------------------------------------------
# run_intake — full pipeline with mocked watsonx
# ---------------------------------------------------------------------------

GOOD_RESPONSE = json.dumps({
    "location_name": "Hornadu",
    "lat": 13.3876,
    "lng": 75.1951,
    "incident_type": "flood",
    "severity": 4,
    "affected_households": 85,
    "report_time": "2024-08-01T08:30:00",
})

INCOMPLETE_RESPONSE = json.dumps({
    "location_name": "Kalasa",
    "lat": None,
    "lng": None,
    "incident_type": None,
    "severity": None,
    "affected_households": None,
    "report_time": None,
})


class TestRunIntake:
    def test_successful_extraction(self, app):
        with patch("backend.agents.intake_agent.generate", return_value=GOOD_RESPONSE):
            incident = run_intake("Flooding in Hornadu, 85 households affected, severity 4")

        assert incident.id is not None
        assert incident.location_name == "Hornadu"
        assert incident.incident_type == IncidentType.flood
        assert incident.severity == 4
        assert incident.affected_households == 85
        assert incident.lat == pytest.approx(13.3876)
        assert incident.status == IncidentStatus.pending

    def test_incomplete_extraction_sets_status(self, app):
        with patch("backend.agents.intake_agent.generate", return_value=INCOMPLETE_RESPONSE):
            incident = run_intake("Something happened somewhere")

        assert incident.status == IncidentStatus.incomplete

    def test_watsonx_failure_uses_fallback(self, app):
        from backend.utils.watsonx_client import WatsonxError
        with patch("backend.agents.intake_agent.generate",
                   side_effect=WatsonxError("service down")):
            incident = run_intake("Flooding at Balehonnur")

        # Rule-based fallback fills required fields → status is pending, not incomplete
        assert incident.status == IncidentStatus.pending
        assert incident.id is not None   # still persisted

    def test_bad_json_uses_fallback(self, app):
        with patch("backend.agents.intake_agent.generate", return_value="not json at all"):
            incident = run_intake("Roads blocked near Mudigere")

        # Rule-based fallback fills required fields → status is pending, not incomplete
        assert incident.status == IncidentStatus.pending

    def test_reporter_id_saved(self, app):
        with patch("backend.agents.intake_agent.generate", return_value=GOOD_RESPONSE):
            incident = run_intake("Flood at Kalasa", reporter_id=42)

        assert incident.reporter_id == 42

    def test_anonymous_submission(self, app):
        with patch("backend.agents.intake_agent.generate", return_value=GOOD_RESPONSE):
            incident = run_intake("Flood at Sringeri")

        assert incident.reporter_id is None

    def test_raw_text_saved(self, app):
        raw = "Landslide on the road to Kottigehara, 3 households cut off"
        with patch("backend.agents.intake_agent.generate", return_value=GOOD_RESPONSE):
            incident = run_intake(raw)

        assert incident.raw_text == raw


# ---------------------------------------------------------------------------
# POST /api/incidents endpoint
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(app):
    return app.test_client()


class TestIncidentEndpoint:
    def test_create_incident_success(self, client):
        with patch("backend.routes.api_incidents.run_intake") as mock_intake:
            # Return a fake Incident-like object
            fake = Incident(
                id=1,
                raw_text="test",
                status=IncidentStatus.pending,
                location_name="Shimoga",
                lat=14.0027, lng=75.5681,
            )
            fake.id = 1
            from datetime import datetime
            fake.created_at = datetime(2024, 8, 1, 10, 0)
            fake.report_time = None
            fake.incident_type = IncidentType.flood
            fake.severity = 3
            fake.affected_households = 50
            mock_intake.return_value = fake

            resp = client.post("/api/incidents",
                               json={"description": "Flood at Shimoga village, 50 households affected"},
                               content_type="application/json")

        assert resp.status_code == 201
        data = resp.get_json()
        assert data["incident"]["id"] == 1
        # Status is "verified" after auto-verification runs in the endpoint
        assert data["incident"]["status"] in ("pending", "verified", "incomplete")

    def test_create_incident_short_description(self, client):
        resp = client.post("/api/incidents",
                           json={"description": "short"},
                           content_type="application/json")
        assert resp.status_code == 400
        assert "VALIDATION_ERROR" in resp.get_json()["error"]["code"]

    def test_create_incident_empty_body(self, client):
        resp = client.post("/api/incidents",
                           json={},
                           content_type="application/json")
        assert resp.status_code == 400

    def test_list_incidents_requires_coordinator(self, client, app):
        # Anonymous
        resp = client.get("/api/incidents")
        assert resp.status_code in (302, 401, 403)

    def test_list_incidents_as_coordinator(self, client, app):
        with app.app_context():
            u = User(email="c@test.dev", full_name="C", role=UserRole.coordinator)
            u.set_password("Password1!")
            db.session.add(u)
            db.session.commit()

        client.post("/auth/login", data={"email": "c@test.dev", "password": "Password1!"})
        resp = client.get("/api/incidents")
        assert resp.status_code == 200
        assert "incidents" in resp.get_json()
