from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app import db


class PrioritizationScore(db.Model):
    __tablename__ = "prioritization_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    relief_request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("relief_requests.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True
    )
    # Deterministic composite score (0.0–1.0)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Score components
    isolation_component: Mapped[float] = mapped_column(Float, nullable=False)
    severity_component: Mapped[float] = mapped_column(Float, nullable=False)
    household_component: Mapped[float] = mapped_column(Float, nullable=False)
    need_component: Mapped[float] = mapped_column(Float, nullable=False)
    # Granite-generated rationale (natural language only — not used for the number)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    relief_request = relationship("ReliefRequest", back_populates="prioritization_score")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "relief_request_id": self.relief_request_id,
            "composite_score": round(self.composite_score, 4),
            "components": {
                "isolation": self.isolation_component,
                "severity": self.severity_component,
                "household": self.household_component,
                "need": self.need_component,
            },
            "rationale": self.rationale,
            "computed_at": self.computed_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<PrioritizationScore relief_request_id={self.relief_request_id} score={self.composite_score:.3f}>"
