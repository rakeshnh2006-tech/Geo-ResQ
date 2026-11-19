from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app import db


class VerificationStatus(str, enum.Enum):
    pending = "pending"
    passed = "passed"
    duplicate = "duplicate"
    incomplete = "incomplete"
    conflict = "conflict"


class Verification(db.Model):
    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    # Duplicate check
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True
    )
    duplicate_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Completeness check
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    missing_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Conflict check
    has_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    conflict_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Overall result
    status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus), nullable=False, default=VerificationStatus.pending
    )
    coordinator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    incident = relationship(
        "Incident",
        foreign_keys=[incident_id],
        back_populates="verification",
    )
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])

    def __repr__(self) -> str:
        return f"<Verification incident_id={self.incident_id} status={self.status}>"
