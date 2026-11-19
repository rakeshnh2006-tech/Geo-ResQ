#!/usr/bin/env python3
"""
scripts/import_osm.py — Malenadu OSM Road-Network Import
=========================================================
Downloads the Karnataka OSM extract from Geofabrik, filters it to the
Malenadu bounding box, and bulk-upserts:

  • highway ways   → road_segments table
  • place/town nodes → villages table

Usage:
    python scripts/import_osm.py [--pbf /path/to/karnataka-latest.osm.pbf]
                                 [--db  mysql+pymysql://user:pw@host/db]
                                 [--dry-run]

The script is idempotent: re-running it upserts on OSM IDs without creating
duplicate rows.

Dependencies (must be installed):
    osmium      (python bindings for libosmium / pyosmium)
    sqlalchemy
    pymysql
    requests
    tqdm        (optional — progress bars)
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterator

import osmium
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("import_osm")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Malenadu bounding box (lat_min, lat_max, lon_min, lon_max)
BBOX = (13.0, 14.5, 75.0, 76.0)

# Geofabrik Karnataka extract
GEOFABRIK_URL = (
    "https://download.geofabrik.de/asia/india/karnataka-latest.osm.pbf"
)

# Highway tags we import as road segments
HIGHWAY_INCLUDE = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
    "track", "path",
}

# Place tags we import as villages / towns
PLACE_INCLUDE = {"city", "town", "village", "hamlet", "suburb", "locality"}

# Population threshold for is_town flag
TOWN_POPULATION_THRESHOLD = 5_000

# Batch size for DB inserts
BATCH_SIZE = 2_000

# ---------------------------------------------------------------------------
# Haversine distance (metres)
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _in_bbox(lat: float, lon: float) -> bool:
    lat_min, lat_max, lon_min, lon_max = BBOX
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max

# ---------------------------------------------------------------------------
# osmium handlers
# ---------------------------------------------------------------------------

class WayHandler(osmium.SimpleHandler):
    """Collect highway ways whose node endpoints fall inside the bounding box."""

    def __init__(self) -> None:
        super().__init__()
        self.segments: list[dict] = []

    def way(self, w: osmium.osm.Way) -> None:
        highway = w.tags.get("highway")
        if highway not in HIGHWAY_INCLUDE:
            return
        nodes = list(w.nodes)
        if len(nodes) < 2:
            return

        # Use first and last node as the edge endpoints
        try:
            start = nodes[0]
            end = nodes[-1]
            slat, slng = float(start.lat), float(start.lon)
            elat, elng = float(end.lat), float(end.lon)
        except (osmium.InvalidLocationError, ValueError):
            return

        # Include segment if either endpoint is inside bbox
        if not (_in_bbox(slat, slng) or _in_bbox(elat, elng)):
            return

        length = haversine_m(slat, slng, elat, elng)

        self.segments.append({
            "osm_way_id": w.id,
            "name": w.tags.get("name") or w.tags.get("ref"),
            "highway_type": highway,
            "start_node_id": start.ref,
            "end_node_id": end.ref,
            "start_lat": slat,
            "start_lng": slng,
            "end_lat": elat,
            "end_lng": elng,
            "length_m": round(length, 1),
            "blocked": 0,
        })


class NodeHandler(osmium.SimpleHandler):
    """Collect place nodes that fall inside the bounding box."""

    def __init__(self) -> None:
        super().__init__()
        self.villages: list[dict] = []

    def node(self, n: osmium.osm.Node) -> None:
        place = n.tags.get("place")
        if place not in PLACE_INCLUDE:
            return
        try:
            lat, lng = float(n.location.lat), float(n.location.lon)
        except (osmium.InvalidLocationError, ValueError):
            return
        if not _in_bbox(lat, lng):
            return

        name = n.tags.get("name:en") or n.tags.get("name") or n.tags.get("name:kn")
        if not name:
            return

        try:
            pop = int(n.tags.get("population", 0))
        except ValueError:
            pop = 0

        is_town = 1 if (pop >= TOWN_POPULATION_THRESHOLD or place in {"city", "town"}) else 0

        self.villages.append({
            "osm_node_id": n.id,
            "name": name[:255],
            "lat": lat,
            "lng": lng,
            "population": pop if pop > 0 else None,
            "is_town": is_town,
        })

# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def download_pbf(dest: Path) -> Path:
    """Stream-download the Geofabrik Karnataka PBF if not already present."""
    if dest.exists():
        log.info("PBF already present at %s — skipping download", dest)
        return dest

    log.info("Downloading %s → %s", GEOFABRIK_URL, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(GEOFABRIK_URL, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        last_log = 0.0
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):  # 1 MB chunks
                f.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_log >= 10:
                    pct = 100 * downloaded / total if total else 0
                    log.info("  downloaded %.0f MB / %.0f MB (%.0f%%)",
                             downloaded / 1e6, total / 1e6, pct)
                    last_log = now

    log.info("Download complete: %.0f MB", dest.stat().st_size / 1e6)
    return dest

# ---------------------------------------------------------------------------
# DB upsert helpers
# ---------------------------------------------------------------------------

ROAD_UPSERT = text("""
    INSERT INTO road_segments
        (osm_way_id, name, highway_type,
         start_node_id, end_node_id,
         start_lat, start_lng, end_lat, end_lng,
         length_m, blocked)
    VALUES
        (:osm_way_id, :name, :highway_type,
         :start_node_id, :end_node_id,
         :start_lat, :start_lng, :end_lat, :end_lng,
         :length_m, :blocked)
    ON DUPLICATE KEY UPDATE
        name           = VALUES(name),
        highway_type   = VALUES(highway_type),
        start_lat      = VALUES(start_lat),
        start_lng      = VALUES(start_lng),
        end_lat        = VALUES(end_lat),
        end_lng        = VALUES(end_lng),
        length_m       = VALUES(length_m)
""")

VILLAGE_UPSERT = text("""
    INSERT INTO villages
        (osm_node_id, name, lat, lng, population, is_town)
    VALUES
        (:osm_node_id, :name, :lat, :lng, :population, :is_town)
    ON DUPLICATE KEY UPDATE
        name       = VALUES(name),
        lat        = VALUES(lat),
        lng        = VALUES(lng),
        population = VALUES(population),
        is_town    = VALUES(is_town)
""")


def _batched(lst: list, n: int) -> Iterator[list]:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def upsert_roads(engine: Engine, segments: list[dict], dry_run: bool) -> None:
    if not segments:
        log.info("No road segments to insert.")
        return
    log.info("Upserting %d road segments (batch size %d)…", len(segments), BATCH_SIZE)
    if dry_run:
        log.info("[DRY RUN] skipping DB write for road_segments")
        return
    with engine.begin() as conn:
        for batch in _batched(segments, BATCH_SIZE):
            conn.execute(ROAD_UPSERT, batch)
    log.info("road_segments upsert done.")


def upsert_villages(engine: Engine, villages: list[dict], dry_run: bool) -> None:
    if not villages:
        log.info("No villages to insert.")
        return
    log.info("Upserting %d villages (batch size %d)…", len(villages), BATCH_SIZE)
    if dry_run:
        log.info("[DRY RUN] skipping DB write for villages")
        return
    with engine.begin() as conn:
        for batch in _batched(villages, BATCH_SIZE):
            conn.execute(VILLAGE_UPSERT, batch)
    log.info("villages upsert done.")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import OSM road network into GeoResQ MySQL")
    p.add_argument(
        "--pbf",
        default=None,
        help="Path to an existing .osm.pbf file. If omitted, downloads Karnataka from Geofabrik.",
    )
    p.add_argument(
        "--db",
        default=None,
        help="SQLAlchemy database URL. Defaults to DATABASE_URL env var.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and filter OSM data but do not write to the database.",
    )
    p.add_argument(
        "--osm-data-dir",
        default="osm_data",
        help="Directory to cache downloaded PBF files (default: osm_data/).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # ── Resolve DB URL ───────────────────────────────────────────────────────
    db_url = args.db or os.environ.get("DATABASE_URL")
    if not db_url and not args.dry_run:
        sys.exit("ERROR: DATABASE_URL not set. Pass --db or set DATABASE_URL env var.")

    engine: Engine | None = None
    if not args.dry_run:
        engine = create_engine(db_url, pool_pre_ping=True)
        log.info("Connected to database.")

    # ── Resolve PBF path ─────────────────────────────────────────────────────
    if args.pbf:
        pbf_path = Path(args.pbf)
        if not pbf_path.exists():
            sys.exit(f"ERROR: PBF file not found: {pbf_path}")
    else:
        pbf_path = Path(args.osm_data_dir) / "karnataka-latest.osm.pbf"
        download_pbf(pbf_path)

    pbf_str = str(pbf_path)

    # ── Pass 1: collect nodes (location cache needed for way endpoint coords) ─
    log.info("Pass 1 — collecting place nodes from %s …", pbf_str)
    node_handler = NodeHandler()
    # We need location info on ways, so enable the location cache
    node_handler.apply_file(pbf_str, locations=True, idx="flex_mem")
    log.info("  found %d place nodes in bbox", len(node_handler.villages))

    # ── Pass 2: collect highway ways ─────────────────────────────────────────
    log.info("Pass 2 — collecting highway ways from %s …", pbf_str)
    way_handler = WayHandler()
    way_handler.apply_file(pbf_str, locations=True, idx="flex_mem")
    log.info("  found %d highway segments in bbox", len(way_handler.segments))

    # ── Upsert ───────────────────────────────────────────────────────────────
    if args.dry_run:
        log.info("[DRY RUN] villages: %d  segments: %d",
                 len(node_handler.villages), len(way_handler.segments))
    else:
        upsert_villages(engine, node_handler.villages, dry_run=False)
        upsert_roads(engine, way_handler.segments, dry_run=False)

    log.info("Import complete.")


if __name__ == "__main__":
    main()
