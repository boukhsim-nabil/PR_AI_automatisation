from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class PlatformRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_roles"
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class PlatformUserRole(TimestampMixin, Base):
    __tablename__ = "platform_user_roles"
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    platform_role_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("platform_roles.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class PlatformSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_sessions"
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    mfa_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class CompanyInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "company_invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','accepted','expired','revoked')", name="status_allowed"
        ),
        CheckConstraint("invitation_type = 'owner_invitation'", name="type_owner_only"),
        CheckConstraint("target_role_code = 'owner'", name="target_owner_only"),
        Index(
            "uq_company_invitations_active_owner",
            "company_id",
            "email_normalized",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    invitation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="owner_invitation"
    )
    target_role_code: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="owner"
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    invited_by_platform_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformAuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "platform_audit_logs"
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    company_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(120))
    resource_id: Mapped[str | None] = mapped_column(String(255))
    correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
