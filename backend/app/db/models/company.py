from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.membership import Membership


SETTINGS_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(
        String(160), nullable=False, unique=True, default=lambda: f"company-{uuid4().hex}"
    )
    sector: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Africa/Casablanca", server_default="Africa/Casablanca"
    )
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="fr", server_default="fr"
    )
    country: Mapped[str] = mapped_column(
        String(2), nullable=False, default="MA", server_default="MA"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="MAD", server_default="MAD"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending", index=True
    )
    onboarding_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_started", server_default="not_started"
    )
    plan_code: Mapped[str] = mapped_column(
        String(64), nullable=False, default="trial", server_default="trial"
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_platform_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(String(1000))
    plan_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    settings: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(SETTINGS_TYPE),
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
