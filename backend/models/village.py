from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app import db


class Village(db.Model):
    __tablename__ = "villages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    osm_node_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Is this a "town" (population > 5000) used as a connectivity target?
    is_town: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "osm_node_id": self.osm_node_id,
            "name": self.name,
            "lat": self.lat,
            "lng": self.lng,
            "population": self.population,
            "is_town": self.is_town,
        }

    def __repr__(self) -> str:
        return f"<Village id={self.id} name={self.name} is_town={self.is_town}>"
