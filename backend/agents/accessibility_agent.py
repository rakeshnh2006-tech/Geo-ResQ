"""
backend/agents/accessibility_agent.py
Accessibility Agent — ST-07
============================
Builds an undirected NetworkX graph from the road_segments table.
When a road segment is marked blocked=True it is excluded from the graph.
BFS from every village checks whether any path exists to at least one
"town" node (is_town=True, population > 5 000).

If no path exists the village is considered *isolated* and an
AccessibilityResult row is written (or updated) for it.

The graph is rebuilt each time run_accessibility() is called.  This is
acceptable for disaster-report volumes and avoids a separate graph database.

Public API
----------
run_accessibility()          — full scan of all villages; returns summary dict
get_isolated_villages()      — query DB for current isolated villages (no recompute)
block_road(segment_id)       — mark segment blocked + rerun accessibility
unblock_road(segment_id)     — unmark blocked + rerun accessibility
"""
from __future__ import annotations

import logging
from datetime import datetime

import networkx as nx
from sqlalchemy import select

from backend.app import db
from backend.models.accessibility_result import AccessibilityResult
from backend.models.road_segment import RoadSegment
from backend.models.village import Village

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def _build_graph() -> tuple[nx.Graph, list[RoadSegment]]:
    """Return (graph, blocked_segments).

    Nodes  = OSM node IDs (integers)
    Edges  = unblocked road segments; weight = length_m (or 1 if unknown)
    """
    segments = db.session.scalars(select(RoadSegment)).all()
    G = nx.Graph()

    blocked: list[RoadSegment] = []
    for seg in segments:
        if seg.blocked:
            blocked.append(seg)
            continue
        weight = seg.length_m if seg.length_m else 1.0
        G.add_edge(
            seg.start_node_id,
            seg.end_node_id,
            weight=weight,
            segment_id=seg.id,
        )

    log.debug("Graph built: %d nodes, %d edges, %d blocked segments",
              G.number_of_nodes(), G.number_of_edges(), len(blocked))
    return G, blocked


# ---------------------------------------------------------------------------
# BFS isolation check
# ---------------------------------------------------------------------------

def _town_node_ids() -> set[int]:
    """Return the set of OSM node IDs that belong to towns."""
    towns = db.session.scalars(
        select(Village).where(Village.is_town == True)  # noqa: E712
    ).all()
    return {t.osm_node_id for t in towns}


def _is_isolated(
    village_node: int,
    town_nodes: set[int],
    G: nx.Graph,
) -> bool:
    """Return True if no path exists from village_node to any town node."""
    if not town_nodes:
        return False   # no towns defined — treat all as accessible
    if village_node in town_nodes:
        return False   # the node itself is a town — always accessible
    if village_node not in G:
        return True    # disconnected node (no edges at all)
    # BFS: check if any town node is reachable from village_node
    reachable = nx.node_connected_component(G, village_node)
    return not bool(reachable & town_nodes)


def _blocking_segment_ids_for_village(
    village_node: int,
    blocked_segments: list[RoadSegment],
) -> list[int]:
    """Return IDs of blocked segments whose endpoints include the village node."""
    return [
        s.id for s in blocked_segments
        if s.start_node_id == village_node or s.end_node_id == village_node
    ]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_accessibility() -> dict:
    """Recompute isolation for every village.

    Writes / updates AccessibilityResult rows.
    Returns a summary dict with counts.
    """
    G, blocked_segments = _build_graph()
    town_nodes = _town_node_ids()

    villages = db.session.scalars(select(Village)).all()

    isolated_count = 0
    accessible_count = 0

    for village in villages:
        node_id = village.osm_node_id
        isolated = _is_isolated(node_id, town_nodes, G)

        blocking_ids = (
            _blocking_segment_ids_for_village(node_id, blocked_segments)
            if isolated else []
        )

        # Upsert AccessibilityResult (one row per village, most-recent)
        existing = db.session.scalar(
            select(AccessibilityResult)
            .where(AccessibilityResult.village_id == village.id)
            .order_by(AccessibilityResult.computed_at.desc())
            .limit(1)
        )

        if existing:
            existing.is_isolated = isolated
            existing.blocking_segment_ids = blocking_ids if blocking_ids else None
            from datetime import timezone
            existing.computed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            result = AccessibilityResult(
                village_id=village.id,
                is_isolated=isolated,
                blocking_segment_ids=blocking_ids if blocking_ids else None,
            )
            db.session.add(result)

        if isolated:
            isolated_count += 1
        else:
            accessible_count += 1

    db.session.commit()

    summary = {
        "total_villages": len(villages),
        "isolated": isolated_count,
        "accessible": accessible_count,
    }
    log.info("Accessibility run complete: %s", summary)
    return summary


def get_isolated_villages() -> list[AccessibilityResult]:
    """Return current AccessibilityResult rows where is_isolated=True."""
    return db.session.scalars(
        select(AccessibilityResult).where(AccessibilityResult.is_isolated == True)  # noqa: E712
    ).all()


def block_road(segment_id: int) -> dict:
    """Mark a road segment blocked and rerun accessibility."""
    seg = db.session.get(RoadSegment, segment_id)
    if seg is None:
        raise ValueError(f"RoadSegment {segment_id} not found")
    seg.blocked = True
    db.session.commit()
    log.info("Road segment %d marked blocked", segment_id)
    return run_accessibility()


def unblock_road(segment_id: int) -> dict:
    """Unmark a road segment and rerun accessibility."""
    seg = db.session.get(RoadSegment, segment_id)
    if seg is None:
        raise ValueError(f"RoadSegment {segment_id} not found")
    seg.blocked = False
    db.session.commit()
    log.info("Road segment %d unblocked", segment_id)
    return run_accessibility()
