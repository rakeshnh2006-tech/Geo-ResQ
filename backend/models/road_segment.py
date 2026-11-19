from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app import db


class RoadSegment(db.Model):
    __tablename__ = "road_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    osm_way_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    highway_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Node endpoints (OSM node IDs)
    start_node_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    end_node_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Geometry centroids (for map rendering)
    start_lat: Mapped[float] = mapped_column(Float, nullable=False)
    start_lng: Mapped[float] = mapped_column(Float, nullable=False)
    end_lat: Mapped[float] = mapped_column(Float, nullable=False)
    end_lng: Mapped[float] = mapped_column(Float, nullable=False)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)  # metres
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "osm_way_id": self.osm_way_id,
            "name": self.name,
            "highway_type": self.highway_type,
            "start": {"lat": self.start_lat, "lng": self.start_lng},
            "end": {"lat": self.end_lat, "lng": self.end_lng},
            "blocked": self.blocked,
        }

    def __repr__(self) -> str:
        return f"<RoadSegment osm_way_id={self.osm_way_id} blocked={self.blocked}>"
