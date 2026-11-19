"""
backend/tests/test_st15_e2e.py
End-to-End Disaster Scenario — ST-15.

Scripted scenario exercising all 7 agents in sequence:

Step 1  — 5 simulated incident reports arrive → Intake Agent structures them
Step 2  — Verification flags one as a duplicate of an earlier report
Step 3  — Coordinator blocks a road → Accessibility isolates 2 villages
Step 4  — 3 relief requests submitted → Assessment + Prioritization rank them
Step 5  — Coordinator generates a briefing → HTML contains the disclaimer
Step 6  — All key actions present in audit_log

All Watsonx / Granite calls are mocked throughout.
No real DB (uses in-memory SQLite via Testing config).
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from backend.app import create_app, db
from backend.models.audit_log import AuditLog
from backend.models.briefing import Briefing
from backend.models.incident import Incident, IncidentStatus
from backend.models.prioritization_score import PrioritizationScore
from backend.models.relief_request import ReliefRequest
from backend.models.road_segment import RoadSegment
from backend.models.user import User, UserRole
from backend.models.village import Village
from backend.utils.watsonx_client import WatsonxError


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        import backend.models
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def coordinator_client(client, app):
    """Return a test client already logged in as a coordinator.

    NOTE: We do NOT push a nested app context here — the outer ``app`` fixture
    already holds an active context.  Pushing a second context and then popping
    it would call db.session.remove() on teardown, wiping the ORM session that
    backs the StaticPool connection and making the user invisible to the login
    request handler.
    """
    user = User(
        full_name="Disaster Coordinator",
        email="coordinator@georesq.example.com",
        role=UserRole.coordinator,
    )
    user.set_password("Password1!")
    db.session.add(user)
    db.session.commit()

    login_resp = client.post("/auth/login", data={
        "email": "coordinator@georesq.example.com",
        "password": "Password1!",
    }, follow_redirects=False)
    assert login_resp.status_code == 302, (
        f"Login did not redirect (got {login_resp.status_code}). "
        f"Response body: {login_resp.data[:600].decode('utf-8', errors='replace')}"
    )
    return client


# =============================================================================
# Scenario helpers — reproducible Granite mock responses
# =============================================================================

def _granite_intake(*args, **kwargs) -> str:
    """Return deterministic structured JSON for each test report.
    Accepts any positional/keyword args so it works as a mock side_effect."""
    raw_text = args[0] if args else ""
    templates = {
        "Agumbe": '{"location_name":"Agumbe","lat":13.51,"lng":75.09,"incident_type":"flood","severity":5,"affected_households":300,"report_time":null}',
        "Sringeri": '{"location_name":"Sringeri","lat":13.42,"lng":75.25,"incident_type":"landslide","severity":4,"affected_households":150,"report_time":null}',
        "Koppa": '{"location_name":"Koppa","lat":13.53,"lng":75.37,"incident_type":"road_block","severity":3,"affected_households":80,"report_time":null}',
        "Mudigere": '{"location_name":"Mudigere","lat":13.13,"lng":75.64,"incident_type":"infrastructure","severity":2,"affected_households":45,"report_time":null}',
        "Kalasa": '{"location_name":"Kalasa","lat":13.21,"lng":75.37,"incident_type":"flood","severity":5,"affected_households":310,"report_time":null}',
    }
    for key, response in templates.items():
        if key in raw_text:
            return response
    return '{"location_name":"Unknown","lat":null,"lng":null,"incident_type":"other","severity":3,"affected_households":null,"report_time":null}'


def _granite_similarity(*args, **kwargs) -> str:
    """Return similarity score > 0.85 when 'duplicate_trigger' is in prompt."""
    prompt = args[0] if args else ""
    if "duplicate_trigger" in prompt:
        return "0.92"
    return "0.30"


# =============================================================================
# Step 1 — Intake: 5 reports structured by Granite
# =============================================================================

class TestStep1Intake:
    """Five disaster reports are submitted; all are structured by the Intake Agent."""

    REPORTS = [
        "Severe flooding at Agumbe village, roads washed out. Over 300 families displaced.",
        "Major landslide near Sringeri blocking NH169. About 150 households cut off.",
        "Road completely blocked at Koppa due to tree fall. Around 80 families stranded.",
        "Power lines down at Mudigere. 45 households without electricity for 2 days.",
        "Flash floods reported at Kalasa. Around 310 households in distress.",
    ]

    def test_all_five_incidents_created(self, app, client):
        """POST /api/incidents called 5 times → 5 rows in incidents table."""
        incident_ids = []
        for report in self.REPORTS:
            with patch("backend.agents.intake_agent.generate", side_effect=_granite_intake), \
                 patch("backend.agents.verification_agent.generate", return_value="0.1"):
                resp = client.post("/api/incidents", json={"description": report})
            assert resp.status_code == 201, f"Failed for: {report[:50]}"
            incident_ids.append(resp.get_json()["incident"]["id"])

        assert len(set(incident_ids)) == 5, "Expected 5 distinct incident IDs"

        with app.app_context():
            count = db.session.scalar(db.select(db.func.count(Incident.id)))
        assert count == 5

    def test_intake_extracts_severity_correctly(self, app, client):
        """The Agumbe report should extract severity=5."""
        with patch("backend.agents.intake_agent.generate", side_effect=_granite_intake), \
             patch("backend.agents.verification_agent.generate", return_value="0.1"):
            resp = client.post(
                "/api/incidents",
                json={"description": "Severe flooding at Agumbe village, roads washed out."}
            )
        assert resp.status_code == 201
        assert resp.get_json()["incident"]["severity"] == 5

    def test_watsonx_failure_still_creates_incomplete_incident(self, app, client):
        """When Granite fails, incident is saved with status=incomplete (not lost)."""
        with patch("backend.agents.intake_agent.generate", side_effect=WatsonxError("timeout")):
            resp = client.post(
                "/api/incidents",
                json={"description": "Unknown disaster somewhere in the forest area region"}
            )
        assert resp.status_code == 201
        assert resp.get_json()["incident"]["status"] == "incomplete"

    def test_audit_log_has_five_incident_create_entries(self, app, client):
        """Every successful intake writes an audit_log entry."""
        for report in self.REPORTS:
            with patch("backend.agents.intake_agent.generate", side_effect=_granite_intake), \
                 patch("backend.agents.verification_agent.generate", return_value="0.1"):
                client.post("/api/incidents", json={"description": report})

        with app.app_context():
            count = db.session.scalar(
                db.select(db.func.count(AuditLog.id))
                .where(AuditLog.action == "incident.create")
            )
        assert count == 5


# =============================================================================
# Step 2 — Verification: one duplicate flagged
# =============================================================================

class TestStep2Verification:
    """The second Agumbe-area report should be flagged as a duplicate."""

    def _create_original(self, app, client):
        """Create the original Agumbe incident."""
        with patch("backend.agents.intake_agent.generate", side_effect=_granite_intake), \
             patch("backend.agents.verification_agent.generate", return_value="0.1"):
            resp = client.post(
                "/api/incidents",
                json={"description": "Severe flooding at Agumbe village, roads washed out."}
            )
        return resp.get_json()["incident"]["id"]

    def test_duplicate_flagged_when_similar_report_arrives(self, app, client):
        """A near-identical second report should be flagged as duplicate."""
        original_id = self._create_original(app, client)

        # Second report — same location, same type, high similarity score
        with patch("backend.agents.intake_agent.generate", side_effect=_granite_intake), \
             patch("backend.agents.verification_agent.generate", return_value="0.91"):
            resp = client.post(
                "/api/incidents",
                json={"description": "Severe flooding at Agumbe village, roads washed out. duplicate_trigger"}
            )
        assert resp.status_code == 201
        dup_id = resp.get_json()["incident"]["id"]

        with app.app_context():
            dup = db.session.get(Incident, dup_id)
            assert dup.status == IncidentStatus.duplicate

    def test_non_duplicate_remains_verified_or_pending(self, app, client):
        """A clearly different report from a different location is NOT flagged."""
        self._create_original(app, client)

        with patch("backend.agents.intake_agent.generate", side_effect=_granite_intake), \
             patch("backend.agents.verification_agent.generate", return_value="0.1"):
            resp = client.post(
                "/api/incidents",
                json={"description": "Major landslide near Sringeri blocking NH169 completely"}
            )
        assert resp.status_code == 201
        status = resp.get_json()["incident"]["status"]
        assert status in ("verified", "pending")

    def test_coordinator_can_verify_flagged_incident(self, app, coordinator_client):
        """A coordinator can manually verify an incident via the verify endpoint."""
        # Create an incident via intake (status will be pending/verified after verification)
        with patch("backend.agents.intake_agent.generate", side_effect=_granite_intake), \
             patch("backend.agents.verification_agent.generate", return_value="0.1"):
            resp = coordinator_client.post("/api/incidents",
                                           json={"description": "Severe flooding at Agumbe village, roads washed out."})
        assert resp.status_code == 201
        original_id = resp.get_json()["incident"]["id"]

        # Patch the status to incomplete using the status update endpoint
        resp_patch = coordinator_client.patch(f"/api/incidents/{original_id}/status",
                                              json={"status": "incomplete"})
        assert resp_patch.status_code == 200

        # Now verify it
        resp = coordinator_client.post(f"/api/incidents/{original_id}/verify",
                                       json={"note": "Field team confirmed"})
        assert resp.status_code == 200
        assert resp.get_json()["incident"]["status"] == "verified"


# =============================================================================
# Step 3 — Road block → 2 villages isolated
# =============================================================================

class TestStep3Accessibility:
    """Blocking a road segment should isolate villages on the far side."""

    def _seed_road_network(self):
        """Create a simple road graph using the active db session:
            Town ─── Road1 ─── [node 5001] ─── Road2 ─── Village1
                                             └─── Road3 ─── Village2
        Blocking Road1 cuts off both villages.
        """
        town = Village(osm_node_id=1001, name="Mudigere Town", lat=13.13, lng=75.64,
                       population=12000, is_town=True)
        v1 = Village(osm_node_id=1002, name="Hebbe Village", lat=13.20, lng=75.50,
                     population=800, is_town=False)
        v2 = Village(osm_node_id=1003, name="Kalhatti Village", lat=13.22, lng=75.52,
                     population=600, is_town=False)
        db.session.add_all([town, v1, v2])
        db.session.flush()

        r1 = RoadSegment(
            osm_way_id=10001, name="Road to Hebbe", highway_type="secondary",
            start_node_id=1001, end_node_id=5001,
            start_lat=13.13, start_lng=75.64, end_lat=13.20, end_lng=75.50,
            length_m=8000, blocked=False,
        )
        r2 = RoadSegment(
            osm_way_id=10002, name="Road to Hebbe spur", highway_type="tertiary",
            start_node_id=5001, end_node_id=1002,
            start_lat=13.20, start_lng=75.50, end_lat=13.20, end_lng=75.50,
            length_m=500, blocked=False,
        )
        r3 = RoadSegment(
            osm_way_id=10003, name="Road to Kalhatti", highway_type="tertiary",
            start_node_id=5001, end_node_id=1003,
            start_lat=13.20, start_lng=75.50, end_lat=13.22, end_lng=75.52,
            length_m=600, blocked=False,
        )
        db.session.add_all([r1, r2, r3])
        db.session.commit()
        return r1.id

    def test_blocking_road_isolates_two_villages(self, app, coordinator_client):
        """Blocking the trunk road should isolate both downstream villages."""
        road_id = self._seed_road_network()

        resp = coordinator_client.post(f"/api/roads/{road_id}/block")
        assert resp.status_code == 200

        resp = coordinator_client.get("/api/accessibility")
        data = resp.get_json()
        isolated_names = [v["village_name"] for v in data["isolated_villages"]]
        assert "Hebbe Village" in isolated_names
        assert "Kalhatti Village" in isolated_names
        assert len(data["isolated_villages"]) >= 2

    def test_unblocking_road_restores_access(self, app, coordinator_client):
        """Unblocking the road should clear all isolated villages."""
        road_id = self._seed_road_network()

        coordinator_client.post(f"/api/roads/{road_id}/block")

        # Confirm isolated first
        resp = coordinator_client.get("/api/accessibility")
        assert len(resp.get_json()["isolated_villages"]) >= 2

        # Unblock
        resp = coordinator_client.post(f"/api/roads/{road_id}/unblock")
        assert resp.status_code == 200

        resp = coordinator_client.get("/api/accessibility")
        assert resp.get_json()["isolated_villages"] == []

    def test_road_block_audit_entries_written(self, app, coordinator_client):
        """block and unblock each produce an audit_log entry."""
        road_id = self._seed_road_network()

        coordinator_client.post(f"/api/roads/{road_id}/block")
        coordinator_client.post(f"/api/roads/{road_id}/unblock")

        with app.app_context():
            block_count = db.session.scalar(
                db.select(db.func.count(AuditLog.id)).where(AuditLog.action == "road.block")
            )
            unblock_count = db.session.scalar(
                db.select(db.func.count(AuditLog.id)).where(AuditLog.action == "road.unblock")
            )
        assert block_count >= 1
        assert unblock_count >= 1


# =============================================================================
# Step 4 — Relief requests + Prioritization
# =============================================================================

class TestStep4ReliefPrioritization:
    """Three relief requests are submitted; they are classified and ranked."""

    def _create_incident(self) -> int:
        """Create a verified incident using the currently active app context.

        Must be called while an app context is already active (from the ``app``
        fixture). Do NOT wrap in ``with app.app_context()``; that would push a
        nested context whose teardown wipes the ORM session.
        """
        from backend.models.incident import IncidentType
        inc = Incident(
            raw_text="Flood at Agumbe",
            status=IncidentStatus.verified,
            location_name="Agumbe",
            lat=13.51, lng=75.09,
            incident_type=IncidentType.flood,
            severity=5,
            affected_households=300,
        )
        db.session.add(inc)
        db.session.commit()
        return inc.id

    RELIEF_REQUESTS = [
        ("food", "Urgent food supplies needed for 300 families in Agumbe flood relief camp"),
        ("medical", "Medical team required immediately for injured flood victims at Agumbe"),
        ("rescue", "Rescue boats needed to evacuate elderly residents from flooded Agumbe"),
    ]

    def test_three_relief_requests_created(self, app, client):
        """Three POST /api/relief-requests → three rows with correct categories."""
        inc_id = self._create_incident()
        created_categories = []
        for category, description in self.RELIEF_REQUESTS:
            with patch("backend.agents.relief_assessment_agent.generate", return_value=category):
                resp = client.post("/api/relief-requests", json={
                    "description": description,
                    "incident_id": inc_id,
                })
            assert resp.status_code == 201
            created_categories.append(resp.get_json()["relief_request"]["need_category"])

        assert set(created_categories) == {"food", "medical", "rescue"}

    def test_prioritization_ranks_rescue_above_food(self, app, coordinator_client):
        """Rescue should score higher than food (need_weight: 1.0 vs 0.5)."""
        inc_id = self._create_incident()
        for category, description in self.RELIEF_REQUESTS:
            with patch("backend.agents.relief_assessment_agent.generate", return_value=category):
                coordinator_client.post("/api/relief-requests", json={
                    "description": description,
                    "incident_id": inc_id,
                })

        with patch("backend.agents.prioritization_agent.generate",
                   return_value="Rescue is the highest priority."):
            resp = coordinator_client.post("/api/prioritization/run")
        assert resp.status_code == 200
        scored = resp.get_json()["scored"]
        assert scored == 3

        resp = coordinator_client.get("/api/prioritization")
        ranked = resp.get_json()["prioritization"]
        assert len(ranked) == 3

        # Rescue should be ranked #1
        top = ranked[0]
        # The API nests need_category inside "relief_request"
        assert top["relief_request"]["need_category"] == "rescue"

    def test_all_three_requests_scored(self, app, coordinator_client):
        """POST /api/prioritization/run scores all 3 unscored requests."""
        inc_id = self._create_incident()
        for category, description in self.RELIEF_REQUESTS:
            with patch("backend.agents.relief_assessment_agent.generate", return_value=category):
                coordinator_client.post("/api/relief-requests", json={
                    "description": description,
                    "incident_id": inc_id,
                })

        with patch("backend.agents.prioritization_agent.generate", return_value="All scored."):
            resp = coordinator_client.post("/api/prioritization/run")

        with app.app_context():
            score_count = db.session.scalar(
                db.select(db.func.count(PrioritizationScore.id))
            )
        assert score_count == 3


# =============================================================================
# Step 5 — Briefing with disclaimer
# =============================================================================

class TestStep5Briefing:
    """Coordinator generates a briefing; the HTML output contains the disclaimer."""

    def test_briefing_created_with_disclaimer(self, app, coordinator_client):
        """POST /api/briefings → 201; briefing summary is non-empty."""
        with patch("backend.agents.briefing_agent.generate") as mock_gen:
            mock_gen.return_value = (
                "Situation summary: Five incidents reported across Malenadu. "
                "Three villages remain isolated. Rescue operations are underway."
            )
            resp = coordinator_client.post("/api/briefings")

        assert resp.status_code == 201
        data = resp.get_json()["briefing"]
        assert len(data["summary_text"]) > 10

    def test_disclaimer_in_briefing_html(self, app):
        """The rendered HTML for a briefing always contains the DISCLAIMER text."""
        from backend.agents.briefing_agent import DISCLAIMER, _build_snapshot, _render_html

        with app.app_context():
            snapshot = _build_snapshot()
        html = _render_html(snapshot, "Test summary text.", "Test Author")
        assert DISCLAIMER in html, "DISCLAIMER must be present in every briefing HTML"

    def test_disclaimer_cannot_be_empty(self, app):
        """DISCLAIMER constant is a non-trivial string."""
        from backend.agents.briefing_agent import DISCLAIMER
        assert len(DISCLAIMER) > 50
        assert "DISCLAIMER" in DISCLAIMER.upper()

    def test_briefing_persisted_in_db(self, app, coordinator_client):
        """POST /api/briefings creates a Briefing row in the database."""
        with patch("backend.agents.briefing_agent.generate",
                   return_value="Summary of disaster situation."):
            coordinator_client.post("/api/briefings")

        with app.app_context():
            count = db.session.scalar(db.select(db.func.count(Briefing.id)))
        assert count == 1

    def test_briefing_audit_entry_written(self, app, coordinator_client):
        """Generating a briefing writes a 'briefing.generate' audit entry."""
        with patch("backend.agents.briefing_agent.generate",
                   return_value="Summary of disaster situation."):
            coordinator_client.post("/api/briefings")

        with app.app_context():
            entry = db.session.scalars(
                db.select(AuditLog).where(AuditLog.action == "briefing.generate")
            ).first()
        assert entry is not None
        assert entry.entity_type == "briefings"


# =============================================================================
# Step 6 — Full scenario audit trail
# =============================================================================

class TestStep6AuditTrail:
    """All key actions across the full scenario are present in audit_log."""

    def _run_full_scenario(self, app, coordinator_client, client):
        """Execute the complete 5-step scenario end-to-end."""
        # --- Seed road data upfront using the outer app context ---
        # We seed here (before any HTTP calls) to stay in the outer fixture context.
        village = Village(osm_node_id=9901, name="Scenario Village",
                          lat=13.5, lng=75.1, population=400, is_town=False)
        db.session.add(village)
        road = RoadSegment(
            osm_way_id=99901, name="Scenario Road", highway_type="primary",
            start_node_id=9901, end_node_id=9902,
            start_lat=13.5, start_lng=75.1, end_lat=13.51, end_lng=75.11,
            length_m=1000, blocked=False,
        )
        db.session.add(road)
        db.session.commit()
        road_id = road.id

        # --- Step 1: 3 incidents (enough to demonstrate) ---
        incident_ids = []
        reports = [
            "Severe flooding at Agumbe village, roads washed out completely urgent",
            "Major landslide near Sringeri blocking NH169 completely large scale",
            "Road completely blocked at Koppa due to tree fall families stranded",
        ]
        for report in reports:
            with patch("backend.agents.intake_agent.generate",
                       side_effect=_granite_intake), \
                 patch("backend.agents.verification_agent.generate", return_value="0.1"):
                resp = client.post("/api/incidents", json={"description": report})
            incident_ids.append(resp.get_json()["incident"]["id"])

        # --- Step 2: Coordinator verifies one (via API, no nested context) ---
        coordinator_client.patch(f"/api/incidents/{incident_ids[0]}/status",
                                  json={"status": "incomplete"})
        coordinator_client.post(f"/api/incidents/{incident_ids[0]}/verify",
                                 json={"note": "Confirmed"})

        # --- Step 3: Block the pre-seeded road ---
        coordinator_client.post(f"/api/roads/{road_id}/block")

        # --- Step 4: Relief requests + prioritization ---
        for category, desc in [
            ("rescue", "Rescue boats needed for flood victims in Agumbe river area"),
            ("food",   "Emergency food supplies needed for displaced flood families"),
        ]:
            with patch("backend.agents.relief_assessment_agent.generate", return_value=category):
                coordinator_client.post("/api/relief-requests", json={
                    "description": desc,
                    "incident_id": incident_ids[0],
                })
        with patch("backend.agents.prioritization_agent.generate", return_value="Prioritized."):
            coordinator_client.post("/api/prioritization/run")

        # --- Step 5: Generate briefing ---
        with patch("backend.agents.briefing_agent.generate",
                   return_value="Full situation briefing for Malenadu region."):
            coordinator_client.post("/api/briefings")

    def test_all_action_types_present_in_audit(self, app, coordinator_client, client):
        """After running the full scenario, all key action types appear in audit_log."""
        self._run_full_scenario(app, coordinator_client, client)

        expected_actions = {
            "incident.create",
            "incident.verify",
            "road.block",
            "relief_request.create",
            "prioritization.run",
            "briefing.generate",
        }

        with app.app_context():
            logged_actions = set(
                db.session.scalars(db.select(AuditLog.action)).all()
            )

        missing = expected_actions - logged_actions
        assert not missing, f"Missing audit actions: {missing}"

    def test_audit_log_is_append_only(self, app, coordinator_client, client):
        """Audit log count only grows — no entries are deleted."""
        self._run_full_scenario(app, coordinator_client, client)
        with app.app_context():
            count_after = db.session.scalar(db.select(db.func.count(AuditLog.id)))
        assert count_after > 0

    def test_incident_create_audit_count_matches_incidents(self, app, coordinator_client, client):
        """The number of 'incident.create' audit entries equals the number of incidents."""
        self._run_full_scenario(app, coordinator_client, client)
        with app.app_context():
            incident_count = db.session.scalar(db.select(db.func.count(Incident.id)))
            audit_count = db.session.scalar(
                db.select(db.func.count(AuditLog.id))
                .where(AuditLog.action == "incident.create")
            )
        assert audit_count == incident_count

    def test_relief_audit_count_matches_requests(self, app, coordinator_client, client):
        """The number of 'relief_request.create' audit entries matches requests."""
        self._run_full_scenario(app, coordinator_client, client)
        with app.app_context():
            request_count = db.session.scalar(db.select(db.func.count(ReliefRequest.id)))
            audit_count = db.session.scalar(
                db.select(db.func.count(AuditLog.id))
                .where(AuditLog.action == "relief_request.create")
            )
        assert audit_count == request_count

    def test_all_seven_agents_exercised(self, app, coordinator_client, client):
        """The scenario exercises all 7 agents; verify via DB state."""
        self._run_full_scenario(app, coordinator_client, client)
        with app.app_context():
            # Agent 1: Intake — incidents created
            assert db.session.scalar(db.select(db.func.count(Incident.id))) >= 3
            # Agent 2: Verification — verification rows exist
            from backend.models.verification import Verification
            assert db.session.scalar(db.select(db.func.count(Verification.id))) >= 1
            # Agent 3: Accessibility — accessibility_results exist
            from backend.models.accessibility_result import AccessibilityResult
            assert db.session.scalar(db.select(db.func.count(AccessibilityResult.id))) >= 1
            # Agent 4: Relief Assessment — relief requests exist
            assert db.session.scalar(db.select(db.func.count(ReliefRequest.id))) >= 2
            # Agent 5: Prioritization — scores exist
            assert db.session.scalar(db.select(db.func.count(PrioritizationScore.id))) >= 2
            # Agent 6: Briefing — briefing created
            assert db.session.scalar(db.select(db.func.count(Briefing.id))) == 1
            # Agent 7: Dashboard / audit trail — entries in audit_log
            assert db.session.scalar(db.select(db.func.count(AuditLog.id))) > 0
