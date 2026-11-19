from __future__ import annotations

import enum
from datetime import datetime

import bcrypt
from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app import db, login_manager


class UserRole(str, enum.Enum):
    citizen = "citizen"
    coordinator = "coordinator"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), nullable=False, default=UserRole.citizen
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # ── password helpers ──────────────────────────────────────────────────────

    def set_password(self, plaintext: str) -> None:
        self.password_hash = bcrypt.hashpw(
            plaintext.encode(), bcrypt.gensalt()
        ).decode()

    def check_password(self, plaintext: str) -> bool:
        return bcrypt.checkpw(plaintext.encode(), self.password_hash.encode())

    # ── Flask-Login ───────────────────────────────────────────────────────────

    @property
    def is_coordinator(self) -> bool:
        return self.role == UserRole.coordinator

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))
