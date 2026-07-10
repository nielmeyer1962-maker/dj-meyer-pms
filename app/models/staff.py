from __future__ import annotations

import enum
from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, validates
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class StaffRole(enum.Enum):
    TAX = "TAX"
    SECRETARIAL = "SECRETARIAL"
    BOTH = "BOTH"


class Staff(UserMixin, db.Model):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Human identifier — NIEL, CANDI, TSEGO, etc. Unique and non-blank.
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Login identifier. Nullable (a staff row may predate having an email) but
    # UNIQUE so it can key authentication — Postgres permits many NULLs under a
    # unique constraint, so emailless rows don't collide. No @ shape check.
    email: Mapped[str | None] = mapped_column(String(200), unique=True)
    role: Mapped[StaffRole] = mapped_column(Enum(StaffRole), nullable=False)
    # werkzeug password hash. Nullable: a staff row without a hash simply cannot
    # log in yet (set via `flask staff set-password`). Never the raw password.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # Admin gate for the Settings blueprint and the client-archive action.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Soft delete via active=False is the recommended routine path. Hard delete
    # is supported by the obligation_instances.assignee_id ON DELETE SET NULL FK.
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Stored UTC; display in Africa/Johannesburg when shown to users
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @validates("code")
    def _validate_code(self, key: str, value: str) -> str:
        if not value or not value.strip() or value != value.strip():
            raise ValueError(
                "code is required, non-blank, and must not have surrounding whitespace"
            )
        return value

    @validates("full_name")
    def _validate_full_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("full_name is required and cannot be blank")
        return value

    # --- Flask-Login / auth ---

    @property
    def is_active(self) -> bool:
        """Flask-Login reads this; tie it to the soft-delete flag so an archived staff
        member can't hold a valid session login. (UserMixin's default is always True.)"""
        return self.active

    def set_password(self, raw_password: str) -> None:
        """Hash and store a password (werkzeug). The raw password is never persisted."""
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """True only if a hash is set AND it matches. A hashless staff can't log in."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self) -> str:
        return f"<Staff {self.code} {self.full_name!r} role={self.role.name}>"
