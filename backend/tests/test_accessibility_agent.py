"""
backend/tests/test_accessibility_agent.py
Tests for ST-07 — Accessibility Agent.
Pure-Python graph tests + DB integration tests (SQLite in-memory).
"""
from __future__ import annotations

import os

import networkx as nx
import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from backend.agents.accessibility_agent import (
    _blocking_segment_ids_for_village,
    _is_isolated,
    block_road,
    get_isolated_villages,
    run_accessibility,
    unblock_road,
)
from backend.app import create_app, db
from backend.models.road_segment import RoadSegment
from backend.models.village import Village
from backend.models.accessibility_result import AccessibilityResult


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


def _add_village(app, osm_node_id, name, is_town=False, pop=None):
    with app.app_context():
        v = Village(
            osm_node_id=osm_node_id,
            name=name,
            lat=13.0 + osm_node_id * 0.01,
            lng=75.0 + osm_node_id * 0.01,
            population=pop,
            is_town=is_town,
        )
        db.session.add(v)
        db.session.commit()
        return v.id


def _add_segment(app, osm_way_id, start_node, end_node, blocked=False):
    with app.app_context():
        s = RoadSegment(
            osm_way_id=osm_way_id,
            start_node_id=start_node,
            end_node_id=end_node,
            start_lat=13.0, start_lng=75.0,
            end_lat=13.1, end_lng=75.1,
            length_m=5000.0,
            blocked=blocked,
        )
        db.session.add(s)
        db.session.commit()
        return s.id


# ---------------------------------------------------------------------------
# Pure-function unit tests
# ---------------------------------------------------------------------------

class TestIsIsolated:
    def _graph(self, edges):
        G = nx.Graph()
        G.add_edges_from(edges)
        return G

    def test_node_reachable_to_town(self):
        # village=1 → 2 → town=3
        G = self._graph([(1, 2), (2, 3)])
        assert _is_isolated(1, {3}, G) is False

    def test_node_isolated_no_path(self):
        # village=1 connected only to 2; town=3 is in a separate component
        G = self._graph([(1, 2), (3, 4)])
        assert _is_isolated(1, {3, 4}, G) is True

    def test_node_not_in_graph(self):
        G = self._graph([(2, 3)])
        assert _is_isolated(99, {3}, G) is True

    def test_no_towns_defined_never_isolated(self):
        G = self._graph([(1, 2)])
        assert _is_isolated(1, set(), G) is False

    def test_village_is_a_town(self):
        # Village node IS the town node — always accessible
        G = self._graph([(1, 2)])
        assert _is_isolated(1, {1}, G) is False

    def test_multiple_towns_one_reachable(self):
        # village=5 can reach town=6; town=10 is unreachable
        G = self._graph([(5, 6)])
        assert _is_isolated(5, {6, 10}, G) is False


class TestBlockingSegmentIds:
    def _seg(self, id_, start, end):
        from types import SimpleNamespace
        return SimpleNamespace(id=id_, start_node_id=start, end_node_id=end)

    def test_returns_matching_segments(self):
        segs = [self._seg(1, 100, 200), self._seg(2, 300, 400)]
        result = _blocking_segment_ids_for_village(100, segs)
        assert result == [1]

    def test_end_node_match(self):
        segs = [self._seg(5, 10, 20)]
        result = _blocking_segment_ids_for_village(20, segs)
        assert result == [5]

    def test_no_match(self):
        segs = [self._seg(1, 100, 200)]
        result = _blocking_segment_ids_for_village(999, segs)
        assert result == []


# ---------------------------------------------------------------------------
# DB integration tests
# ---------------------------------------------------------------------------

class TestRunAccessibility:
    def test_all_villages_accessible_no_blocked_roads(self, app):
        """Linear chain: village → road → town — all accessible."""
        town_v_id = _add_village(app, 1001, "Shimoga", is_town=True, pop=274000)
        village_v_id = _add_village(app, 1002, "Kalasa", is_town=False)
        _add_segment(app, 2001, 1001, 1002, blocked=False)   # connects them

        with app.app_context():
            summary = run_accessibility()

        assert summary["total_villages"] == 2
        assert summary["isolated"] == 0
        assert summary["accessible"] == 2

    def test_blocking_road_isolates_village(self, app):
        """Block the only road to a village — it becomes isolated."""
        _add_village(app, 1001, "Shimoga", is_town=True, pop=274000)
        _add_village(app, 1002, "Hornadu", is_town=False)
        seg_id = _add_segment(app, 2001, 1001, 1002, blocked=False)

        # First confirm accessible
        with app.app_context():
            summary = run_accessibility()
        assert summary["isolated"] == 0

        # Now block the road
        with app.app_context():
            summary = block_road(seg_id)

        assert summary["isolated"] == 1
        assert summary["accessible"] == 1

    def test_unblocking_road_restores_access(self, app):
        """Unblock a road — village becomes accessible again."""
        _add_village(app, 1001, "Shimoga", is_town=True, pop=274000)
        _add_village(app, 1002, "Hornadu", is_town=False)
        seg_id = _add_segment(app, 2001, 1001, 1002, blocked=True)

        with app.app_context():
            summary = block_road(seg_id)   # already blocked; rerun
        assert summary["isolated"] == 1

        with app.app_context():
            summary = unblock_road(seg_id)
        assert summary["isolated"] == 0

    def test_village_with_no_roads_is_isolated(self, app):
        """Village not in the graph at all — isolated."""
        _add_village(app, 1001, "Shimoga", is_town=True, pop=274000)
        _add_village(app, 9999, "RemoteHamlet", is_town=False)
        # No road added for RemoteHamlet

        with app.app_context():
            summary = run_accessibility()

        assert summary["isolated"] == 1   # RemoteHamlet

    def test_get_isolated_villages(self, app):
        """get_isolated_villages returns only isolated rows."""
        _add_village(app, 1001, "Shimoga", is_town=True, pop=274000)
        _add_village(app, 1002, "Hornadu", is_town=False)
        seg_id = _add_segment(app, 2001, 1001, 1002, blocked=False)

        with app.app_context():
            run_accessibility()
            isolated = get_isolated_villages()
        assert isolated == []

        with app.app_context():
            block_road(seg_id)
            isolated = get_isolated_villages()
        assert len(isolated) == 1

    def test_block_nonexistent_segment_raises(self, app):
        with app.app_context():
            with pytest.raises(ValueError, match="not found"):
                block_road(99999)

    def test_accessibility_result_persisted(self, app):
        """AccessibilityResult rows are written to the DB."""
        _add_village(app, 1001, "Shimoga", is_town=True, pop=274000)
        _add_village(app, 1002, "Kalasa", is_town=False)
        _add_segment(app, 2001, 1001, 1002, blocked=False)

        with app.app_context():
            run_accessibility()
            count = db.session.query(AccessibilityResult).count()
        assert count == 2

    def test_rerun_updates_existing_rows(self, app):
        """Running accessibility twice does not duplicate rows."""
        _add_village(app, 1001, "Shimoga", is_town=True, pop=274000)
        _add_village(app, 1002, "Kalasa", is_town=False)
        _add_segment(app, 2001, 1001, 1002, blocked=False)

        with app.app_context():
            run_accessibility()
            run_accessibility()
            count = db.session.query(AccessibilityResult).count()
        assert count == 2   # still 2, not 4

    def test_alternate_path_prevents_isolation(self, app):
        """Village connected via two roads — blocking one still leaves access."""
        _add_village(app, 1001, "Shimoga",    is_town=True)
        _add_village(app, 1002, "Chikmagalur", is_town=True)
        _add_village(app, 1003, "Kalasa",      is_town=False)
        _add_segment(app, 2001, 1001, 1003, blocked=False)   # road A
        _add_segment(app, 2002, 1002, 1003, blocked=False)   # road B
        seg_a = _add_segment(app, 2003, 1001, 1003, blocked=False)  # road C (extra)

        with app.app_context():
            # Block road between 1001-1003 (via seg 2001)
            # We'll block the segment added as 2001
            from sqlalchemy import select as sa_select
            with app.app_context():
                seg = db.session.scalar(
                    sa_select(RoadSegment).where(RoadSegment.osm_way_id == 2001)
                )
                seg.blocked = True
                db.session.commit()
                summary = run_accessibility()

        # Kalasa still reachable via Chikmagalur (road B)
        assert summary["isolated"] == 0
