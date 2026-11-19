from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app import db


class IncidentType(str, enum.Enum):
    flood = "flood"
    landslide = "landslide"
    road_block = "road_block"
    infrastructure = "infrastructure"
    medical = "medical"
    other = "other"


class IncidentStatus(str, enum.Enum):
    pending = "pending"
    verified = "verified"
    duplicate = "duplicate"
    incomplete = "incomplete"
    rejected = "rejected"


class Incident(db.Model):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Raw text submitted by the reporter
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Granite-extracted structured fields
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    incident_type: Mapped[IncidentType | None] = mapped_column(
        Enum(IncidentType), nullable=True
    )
    severity: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 1–5
    affected_households: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Granite raw extraction
    structured_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus), nullable=False, default=IncidentStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    reporter = relationship("User", foreign_keys=[reporter_id])
    verification = relationship(
        "Verification",
        back_populates="incident",
        foreign_keys="[Verification.incident_id]",
        uselist=False,
        cascade="all, delete-orphan",
    )
    relief_requests = relationship(
        "ReliefRequest", back_populates="incident", cascade="all, delete-orphan"
    )
    photos = relationship(
        "IncidentPhoto", back_populates="incident", cascade="all, delete-orphan",
        order_by="IncidentPhoto.uploaded_at",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "raw_text": self.raw_text,
            "location_name": self.location_name,
            "lat": self.lat,
            "lng": self.lng,
            "incident_type": self.incident_type.value if self.incident_type else None,
            "severity": self.severity,
            "affected_households": self.affected_households,
            "report_time": self.report_time.isoformat() if self.report_time else None,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "photo_count": len(self.photos) if self.photos else 0,
        }

    def __repr__(self) -> str:
        return f"<Incident id={self.id} status={self.status} type={self.incident_type}>"
