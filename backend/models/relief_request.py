from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, SmallInteger, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app import db


class NeedCategory(str, enum.Enum):
    food = "food"
    water = "water"
    medical = "medical"
    rescue = "rescue"


class ReliefRequest(db.Model):
    __tablename__ = "relief_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requester_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    need_category: Mapped[NeedCategory | None] = mapped_column(
        Enum(NeedCategory), nullable=True
    )
    # Urgency score 1–10 from Assessment Agent
    urgency_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Component weights used for urgency
    isolation_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    household_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    incident = relationship("Incident", back_populates="relief_requests")
    requester = relationship("User", foreign_keys=[requester_id])
    prioritization_score = relationship(
        "PrioritizationScore", back_populates="relief_request", uselist=False, cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "incident_id": self.incident_id,
            "need_category": self.need_category.value if self.need_category else None,
            "urgency_score": self.urgency_score,
            "raw_text": self.raw_text,
            "created_at": self.created_at.isoformat(),
        }
        # Embed incident location so the dashboard can show it without a second fetch
        if self.incident:
            d["location_name"] = self.incident.location_name
            d["incident_lat"] = self.incident.lat
            d["incident_lng"] = self.incident.lng
            d["incident_severity"] = self.incident.severity
            d["incident_type"] = (
                self.incident.incident_type.value if self.incident.incident_type else None
            )
        return d

    def __repr__(self) -> str:
        return f"<ReliefRequest id={self.id} need={self.need_category} urgency={self.urgency_score}>"
