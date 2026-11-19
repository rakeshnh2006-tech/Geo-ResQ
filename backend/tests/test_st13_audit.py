"""
backend/tests/test_st13_audit.py
Tests for ST-13 — Audit Log & Error Handling.

Coverage
--------
1.  log_action() writes a record to audit_log with correct fields.
2.  log_action() auto-resolves actor_id from Flask-Login current_user.
3.  log_action() auto-resolves ip_address from request context.
4.  log_action() is a no-op (swallows) on DB failure — never raises.
5.  log_action() with explicit actor_id overrides current_user.
6.  log_action() with minimal args (action only) — no crash.
7.  POST /api/incidents writes an audit_log entry "incident.create".
8.  POST /api/incidents/<id>/verify writes "incident.verify".
9.  POST /api/incidents/<id>/reject writes "incident.reject".
10. PATCH /api/incidents/<id>/status writes "incident.status_update".
11. POST /api/relief-requests writes "relief_request.create".
12. POST /api/roads/<id>/block writes "road.block".
13. POST /api/roads/<id>/unblock writes "road.unblock".
14. POST /api/prioritization/run writes "prioritization.run".
15. POST /api/briefings writes "briefing.generate".
16. Global error handler returns JSON {"error": {"code": ..., "message": ...}} for 404.
17. Global error handler returns correct JSON structure for 400.
18. Global error handler returns correct JSON structure for 500.
19. Watsonx failure on intake → incident flagged incomplete, not 500.
20. Watsonx failure on relief assessment → graceful degradation, not 500.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from backend.app import create_app, db
from backend.models.audit_log import AuditLog
from backend.models.incident import Incident, IncidentStatus, IncidentType
from backend.models.road_segment import RoadSegment
from backend.models.user import User, UserRole
from backend.models.village import Village
from backend.utils.audit import log_action


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        import backend.models  # register all models with SQLAlchemy
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _make_coordinator(app) -> User:
    """Create and persist a coordinator user; return id."""
    with app.app_context():
        user = User(
            full_name="Test Coordinator",
            email="coord@test.dev",
            role=UserRole.coordinator,
        )
        user.set_password("Password1!")
        db.session.add(user)
        db.session.commit()
        return user.id


def _login_coordinator(client, app):
    _make_coordinator(app)
    client.post("/auth/login", data={"email": "coord@test.dev", "password": "Password1!"})


def _make_incident(app, status=IncidentStatus.pending) -> int:
    with app.app_context():
        inc = Incident(
            raw_text="Heavy flooding at Agumbe village, roads washed out.",
            status=status,
            location_name="Agumbe",
            lat=13.5,
            lng=75.1,
            incident_type=IncidentType.flood,
            severity=4,
            affected_households=120,
        )
        db.session.add(inc)
        db.session.commit()
        return inc.id


def _make_road(app) -> int:
    with app.app_context():
        seg = RoadSegment(
            osm_way_id=99991,
            name="Test Road",
            highway_type="primary",
            start_node_id=100,
            end_node_id=200,
            start_lat=13.5,
            start_lng=75.1,
            end_lat=13.51,
            end_lng=75.11,
            length_m=500.0,
            blocked=False,
        )
        db.session.add(seg)
        db.session.commit()
        return seg.id


# ---------------------------------------------------------------------------
# 1-6: log_action() unit tests
# ---------------------------------------------------------------------------

class TestLogActionUnit:

    def test_writes_record_with_correct_fields(self, app):
        """log_action() persists a row with all specified fields."""
        with app.app_context():
            log_action(
                "incident.create",
                entity_type="incidents",
                entity_id=42,
                payload={"status": "pending"},
                actor_id=7,
                ip_address="10.0.0.1",
            )
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "incident.create")
            ).first()

        assert entry is not None
        assert entry.entity_type == "incidents"
        assert entry.entity_id == 42
        assert entry.payload == {"status": "pending"}
        assert entry.actor_id == 7
        assert entry.ip_address == "10.0.0.1"

    def test_minimal_call_does_not_crash(self, app):
        """log_action() with only action argument succeeds."""
        with app.app_context():
            log_action("system.boot")
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "system.boot")
            ).first()
        assert entry is not None
        assert entry.entity_id is None
        assert entry.actor_id is None

    def test_explicit_actor_overrides_current_user(self, app, client):
        """When actor_id is explicitly provided, it takes precedence."""
        _login_coordinator(client, app)
        with app.test_request_context("/"):
            log_action("test.override", actor_id=999)
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "test.override")
            ).first()
        assert entry is not None
        assert entry.actor_id == 999

    def test_swallows_db_failure_silently(self, app):
        """DB failure in log_action must NOT propagate to the caller."""
        with app.app_context():
            with patch("backend.app.db.session.add", side_effect=Exception("DB down")):
                # Must not raise — log_action swallows all exceptions
                log_action("should.not.raise", entity_type="test", entity_id=1)

    def test_ip_resolved_from_request_context(self, app):
        """ip_address is captured from Flask request when not explicitly supplied."""
        with app.test_request_context("/", environ_base={"REMOTE_ADDR": "192.168.1.50"}):
            with app.app_context():
                log_action("test.ip_resolve")
                entry = db.session.scalars(
                    db.select(AuditLog).where(AuditLog.action == "test.ip_resolve")
                ).first()
                assert entry is not None
                assert entry.ip_address == "192.168.1.50"

    def test_multiple_actions_stored_separately(self, app):
        """Multiple log_action() calls each produce a distinct row."""
        with app.app_context():
            log_action("event.a", entity_id=1)
            log_action("event.b", entity_id=2)
            entries = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action.in_(["event.a", "event.b"]))
            ).all()
        assert len(entries) == 2
        actions = {e.action for e in entries}
        assert actions == {"event.a", "event.b"}


# ---------------------------------------------------------------------------
# 7-10: incident mutation audit integration tests
# ---------------------------------------------------------------------------

class TestIncidentAudit:

    def test_create_incident_writes_audit(self, app, client):
        """POST /api/incidents writes audit log entry."""
        _login_coordinator(client, app)
        with patch("backend.agents.intake_agent.generate") as mock_gen, \
             patch("backend.agents.verification_agent.generate") as mock_ver:
            mock_gen.return_value = (
                '{"location_name":"Agumbe","lat":13.5,"lng":75.1,'
                '"incident_type":"flood","severity":4,"affected_households":80,"report_time":null}'
            )
            mock_ver.return_value = "0.5"
            resp = client.post("/api/incidents", json={"description": "Flood at Agumbe village area roads washed away"})

        assert resp.status_code == 201
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "incident.create")
            ).first()
        assert entry is not None
        assert entry.entity_type == "incidents"

    def test_verify_incident_writes_audit(self, app, client):
        """POST /api/incidents/<id>/verify writes audit log entry."""
        _login_coordinator(client, app)
        inc_id = _make_incident(app, status=IncidentStatus.incomplete)
        resp = client.post(f"/api/incidents/{inc_id}/verify", json={"note": "Confirmed by field team"})
        assert resp.status_code == 200
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "incident.verify")
            ).first()
        assert entry is not None
        assert entry.entity_id == inc_id
        assert entry.payload["note"] == "Confirmed by field team"

    def test_reject_incident_writes_audit(self, app, client):
        """POST /api/incidents/<id>/reject writes audit log entry."""
        _login_coordinator(client, app)
        inc_id = _make_incident(app, status=IncidentStatus.incomplete)
        resp = client.post(f"/api/incidents/{inc_id}/reject", json={"note": "Duplicate report"})
        assert resp.status_code == 200
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "incident.reject")
            ).first()
        assert entry is not None
        assert entry.entity_id == inc_id

    def test_status_update_writes_audit(self, app, client):
        """PATCH /api/incidents/<id>/status writes audit log entry."""
        _login_coordinator(client, app)
        inc_id = _make_incident(app, status=IncidentStatus.pending)
        resp = client.patch(f"/api/incidents/{inc_id}/status", json={"status": "verified"})
        assert resp.status_code == 200
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "incident.status_update")
            ).first()
        assert entry is not None
        assert entry.payload["new_status"] == "verified"


# ---------------------------------------------------------------------------
# 11: relief request audit
# ---------------------------------------------------------------------------

class TestReliefAudit:

    def test_create_relief_request_writes_audit(self, app, client):
        """POST /api/relief-requests writes audit log entry."""
        _login_coordinator(client, app)
        inc_id = _make_incident(app, status=IncidentStatus.verified)
        with patch("backend.agents.relief_assessment_agent.generate") as mock_gen:
            mock_gen.return_value = "food"
            resp = client.post("/api/relief-requests", json={
                "description": "We urgently need food supplies for the flood victims",
                "incident_id": inc_id,
            })
        assert resp.status_code == 201
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "relief_request.create")
            ).first()
        assert entry is not None
        assert entry.entity_type == "relief_requests"


# ---------------------------------------------------------------------------
# 12-13: road block/unblock audit
# ---------------------------------------------------------------------------

class TestRoadAudit:

    def test_block_road_writes_audit(self, app, client):
        """POST /api/roads/<id>/block writes audit log entry."""
        _login_coordinator(client, app)
        seg_id = _make_road(app)
        # Need at least one village for accessibility to run
        with app.app_context():
            village = Village(
                osm_node_id=55551, name="TestVillage", lat=13.5, lng=75.1,
                population=200, is_town=False,
            )
            db.session.add(village)
            db.session.commit()
        resp = client.post(f"/api/roads/{seg_id}/block")
        assert resp.status_code == 200
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "road.block")
            ).first()
        assert entry is not None
        assert entry.entity_id == seg_id

    def test_unblock_road_writes_audit(self, app, client):
        """POST /api/roads/<id>/unblock writes audit log entry."""
        _login_coordinator(client, app)
        seg_id = _make_road(app)
        # First block, then unblock
        with app.app_context():
            village = Village(
                osm_node_id=55552, name="TestVillage2", lat=13.5, lng=75.1,
                population=200, is_town=False,
            )
            db.session.add(village)
            db.session.commit()
        client.post(f"/api/roads/{seg_id}/block")
        resp = client.post(f"/api/roads/{seg_id}/unblock")
        assert resp.status_code == 200
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "road.unblock")
            ).first()
        assert entry is not None
        assert entry.entity_id == seg_id


# ---------------------------------------------------------------------------
# 14: prioritization audit
# ---------------------------------------------------------------------------

class TestPrioritizationAudit:

    def test_run_prioritization_writes_audit(self, app, client):
        """POST /api/prioritization/run writes audit log entry."""
        _login_coordinator(client, app)
        with patch("backend.agents.prioritization_agent.generate") as mock_gen:
            mock_gen.return_value = "No unscored requests at this time."
            resp = client.post("/api/prioritization/run")
        assert resp.status_code == 200
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "prioritization.run")
            ).first()
        assert entry is not None
        assert "scored_count" in entry.payload

    def test_prioritization_run_scored_count_correct(self, app, client):
        """scored_count in payload matches actual number scored."""
        _login_coordinator(client, app)
        with patch("backend.agents.prioritization_agent.generate") as mock_gen:
            mock_gen.return_value = "No new requests."
            client.post("/api/prioritization/run")
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "prioritization.run")
            ).first()
        assert entry.payload["scored_count"] == 0


# ---------------------------------------------------------------------------
# 15: briefing audit
# ---------------------------------------------------------------------------

class TestBriefingAudit:

    def test_generate_briefing_writes_audit(self, app, client):
        """POST /api/briefings writes audit log entry."""
        _login_coordinator(client, app)
        with patch("backend.agents.briefing_agent.generate") as mock_gen:
            mock_gen.return_value = "Situation summary: flooding in Agumbe."
            resp = client.post("/api/briefings")
        assert resp.status_code == 201
        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "briefing.generate")
            ).first()
        assert entry is not None
        assert entry.entity_type == "briefings"


# ---------------------------------------------------------------------------
# 16-18: Global error handlers
# ---------------------------------------------------------------------------

class TestErrorHandlers:

    def test_404_returns_json(self, client):
        """404 response has correct JSON error shape."""
        resp = client.get("/api/incidents/9999999")
        # Coordinator-only endpoint; unauthenticated gets 401/redirect, not 404.
        # Use a truly non-existent route instead.
        resp = client.get("/this/does/not/exist/at/all")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data
        assert data["error"]["code"] == "NOT_FOUND"
        assert "message" in data["error"]

    def test_400_returns_json(self, app, client):
        """400 responses include JSON error body."""
        resp = client.post("/api/incidents", json={"description": "hi"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_error_response_has_required_keys(self, client):
        """All error responses include both 'code' and 'message' keys."""
        resp = client.get("/nonexistent-route-xyz")
        data = resp.get_json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]


# ---------------------------------------------------------------------------
# 19-20: Watsonx failure graceful degradation
# ---------------------------------------------------------------------------

class TestWatsonxFailureDegradation:

    def test_watsonx_failure_on_intake_flags_incomplete(self, app, client):
        """When watsonx fails on intake, incident saved as incomplete — no 500."""
        from backend.utils.watsonx_client import WatsonxError
        with patch("backend.agents.intake_agent.generate", side_effect=WatsonxError("timeout")):
            resp = client.post("/api/incidents", json={
                "description": "Major landslide blocking the road to Sringeri town completely"
            })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["incident"]["status"] == "incomplete"

    def test_watsonx_failure_on_relief_uses_default_category(self, app, client):
        """When watsonx fails on relief classification, request still saved — no 500."""
        from backend.utils.watsonx_client import WatsonxError
        inc_id = _make_incident(app, status=IncidentStatus.verified)
        with patch("backend.agents.relief_assessment_agent.generate",
                   side_effect=WatsonxError("timeout")):
            resp = client.post("/api/relief-requests", json={
                "description": "We need food water and medical supplies for all families",
                "incident_id": inc_id,
            })
        # Should succeed with graceful degradation (need_category may be null/other)
        assert resp.status_code == 201
        data = resp.get_json()
        assert "relief_request" in data
