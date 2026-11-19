from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app import db


class Briefing(db.Model):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generated_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Structured snapshot that was fed to Granite
    snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Granite-generated situation summary
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Path to the generated PDF (relative to media root)
    pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    generated_by = relationship("User", foreign_keys=[generated_by_id])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "generated_by": self.generated_by.full_name if self.generated_by else None,
            "summary_text": self.summary_text,
            "pdf_path": self.pdf_path,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Briefing id={self.id} generated_at={self.created_at}>"
