from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app import db


class AccessibilityResult(db.Model):
    __tablename__ = "accessibility_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    village_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("villages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # True when no path to any town exists
    is_isolated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # List of blocked road segment IDs that caused the isolation
    blocking_segment_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    village = relationship("Village")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "village_id": self.village_id,
            "village_name": self.village.name if self.village else None,
            "lat": self.village.lat if self.village else None,
            "lng": self.village.lng if self.village else None,
            "is_isolated": self.is_isolated,
            "blocking_segment_ids": self.blocking_segment_ids,
            "computed_at": self.computed_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<AccessibilityResult village_id={self.village_id} isolated={self.is_isolated}>"
