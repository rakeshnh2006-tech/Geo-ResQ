"""
backend/tests/test_import_osm.py
Tests for scripts/import_osm.py — pure-Python, no PBF file or DB needed.
"""
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub out osmium before importing the script so the test can run without
# the pyosmium native extension installed in this environment.
# ---------------------------------------------------------------------------
_osmium_stub = types.ModuleType("osmium")

class _SimpleHandler:
    def apply_file(self, path, locations=False, idx=""):
        pass

_osmium_stub.SimpleHandler = _SimpleHandler
_osmium_stub.InvalidLocationError = Exception

_osm_stub = types.ModuleType("osmium.osm")
_osmium_stub.osm = _osm_stub
sys.modules.setdefault("osmium", _osmium_stub)
sys.modules.setdefault("osmium.osm", _osm_stub)

# Now safe to import
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.import_osm import (
    BBOX,
    HIGHWAY_INCLUDE,
    PLACE_INCLUDE,
    TOWN_POPULATION_THRESHOLD,
    _batched,
    _in_bbox,
    haversine_m,
    upsert_roads,
    upsert_villages,
)


class TestHaversine(unittest.TestCase):
    def test_zero_distance(self):
        self.assertAlmostEqual(haversine_m(13.0, 75.0, 13.0, 75.0), 0.0, places=1)

    def test_known_distance(self):
        # Shimoga → Chikmagalur straight-line haversine ≈ ~79 km
        d = haversine_m(14.0027, 75.5681, 13.3153, 75.7754)
        self.assertGreater(d, 70_000)
        self.assertLess(d, 110_000)

    def test_symmetry(self):
        d1 = haversine_m(13.0, 75.0, 14.0, 76.0)
        d2 = haversine_m(14.0, 76.0, 13.0, 75.0)
        self.assertAlmostEqual(d1, d2, places=3)


class TestInBbox(unittest.TestCase):
    lat_min, lat_max, lon_min, lon_max = BBOX

    def test_inside(self):
        self.assertTrue(_in_bbox(13.5, 75.5))

    def test_outside_lat(self):
        self.assertFalse(_in_bbox(12.9, 75.5))
        self.assertFalse(_in_bbox(14.6, 75.5))

    def test_outside_lon(self):
        self.assertFalse(_in_bbox(13.5, 74.9))
        self.assertFalse(_in_bbox(13.5, 76.1))

    def test_on_boundary(self):
        self.assertTrue(_in_bbox(13.0, 75.0))
        self.assertTrue(_in_bbox(14.5, 76.0))


class TestBatched(unittest.TestCase):
    def test_exact_multiple(self):
        result = list(_batched(list(range(6)), 2))
        self.assertEqual(result, [[0, 1], [2, 3], [4, 5]])

    def test_remainder(self):
        result = list(_batched(list(range(5)), 2))
        self.assertEqual(result, [[0, 1], [2, 3], [4]])

    def test_empty(self):
        self.assertEqual(list(_batched([], 10)), [])

    def test_larger_than_list(self):
        result = list(_batched([1, 2], 100))
        self.assertEqual(result, [[1, 2]])


class TestUpsertDryRun(unittest.TestCase):
    """upsert_* with dry_run=True must never touch the engine."""

    def test_roads_dry_run_no_db_call(self):
        engine = MagicMock()
        segments = [{"osm_way_id": 1, "name": "Test Rd"}]
        upsert_roads(engine, segments, dry_run=True)
        engine.begin.assert_not_called()

    def test_villages_dry_run_no_db_call(self):
        engine = MagicMock()
        villages = [{"osm_node_id": 1, "name": "Testpur"}]
        upsert_villages(engine, villages, dry_run=True)
        engine.begin.assert_not_called()

    def test_roads_empty_no_db_call(self):
        engine = MagicMock()
        upsert_roads(engine, [], dry_run=False)
        engine.begin.assert_not_called()

    def test_villages_empty_no_db_call(self):
        engine = MagicMock()
        upsert_villages(engine, [], dry_run=False)
        engine.begin.assert_not_called()


class TestUpsertWithEngine(unittest.TestCase):
    """upsert_* with real data must call engine.begin() and conn.execute()."""

    def _make_engine(self):
        conn = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=conn)
        cm.__exit__ = MagicMock(return_value=False)
        engine = MagicMock()
        engine.begin.return_value = cm
        return engine, conn

    def test_roads_calls_execute(self):
        engine, conn = self._make_engine()
        segments = [
            {
                "osm_way_id": 99,
                "name": "Test Rd",
                "highway_type": "primary",
                "start_node_id": 1,
                "end_node_id": 2,
                "start_lat": 13.5,
                "start_lng": 75.5,
                "end_lat": 13.6,
                "end_lng": 75.6,
                "length_m": 1000.0,
                "blocked": 0,
            }
        ]
        upsert_roads(engine, segments, dry_run=False)
        engine.begin.assert_called_once()
        conn.execute.assert_called_once()

    def test_villages_calls_execute(self):
        engine, conn = self._make_engine()
        villages = [
            {
                "osm_node_id": 42,
                "name": "Testpur",
                "lat": 13.4,
                "lng": 75.3,
                "population": 2000,
                "is_town": 0,
            }
        ]
        upsert_villages(engine, villages, dry_run=False)
        engine.begin.assert_called_once()
        conn.execute.assert_called_once()


class TestConstants(unittest.TestCase):
    def test_bbox_values(self):
        lat_min, lat_max, lon_min, lon_max = BBOX
        self.assertEqual(lat_min, 13.0)
        self.assertEqual(lat_max, 14.5)
        self.assertEqual(lon_min, 75.0)
        self.assertEqual(lon_max, 76.0)

    def test_highway_include_contains_primary(self):
        self.assertIn("primary", HIGHWAY_INCLUDE)
        self.assertIn("secondary", HIGHWAY_INCLUDE)
        self.assertNotIn("footway", HIGHWAY_INCLUDE)

    def test_place_include_contains_village(self):
        self.assertIn("village", PLACE_INCLUDE)
        self.assertIn("town", PLACE_INCLUDE)

    def test_town_threshold(self):
        self.assertEqual(TOWN_POPULATION_THRESHOLD, 5_000)


if __name__ == "__main__":
    unittest.main()
