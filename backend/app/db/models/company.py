from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, String, text
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
    sector: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    default_language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="fr", server_default="fr"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active", index=True
    )
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
