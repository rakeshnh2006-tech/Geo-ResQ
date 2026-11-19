"""
backend/models/incident_photo.py
Stores paths to photos uploaded as evidence for an incident.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app import db


class IncidentPhoto(db.Model):
    __tablename__ = "incident_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Relative URL path served by Flask static: /static/uploads/<filename>
    url_path: Mapped[str] = mapped_column(String(512), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    incident = relationship("Incident", back_populates="photos")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "filename": self.filename,
            "url": self.url_path,
            "uploaded_at": self.uploaded_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<IncidentPhoto id={self.id} incident={self.incident_id}>"
