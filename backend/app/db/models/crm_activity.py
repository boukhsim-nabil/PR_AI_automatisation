from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

ACTIVITY_METADATA_TYPE = JSON().with_variant(JSONB(), "postgresql")


class CrmActivity(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "crm_activities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "contact_id"],
            ["contacts.company_id", "contacts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "lead_id"],
            ["leads.company_id", "leads.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "actor_membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "activity_type IN ('note', 'call', 'email', 'whatsapp', 'meeting', 'task', "
            "'status_change', 'assignment', 'system')",
            name="activity_type_allowed",
        ),
        CheckConstraint(
            "contact_id IS NOT NULL OR lead_id IS NOT NULL",
            name="resource_required",
        ),
        Index("ix_crm_activities_company_lead_occurred", "company_id", "lead_id", "occurred_at"),
        Index(
            "ix_crm_activities_company_contact_occurred",
            "company_id",
            "contact_id",
            "occurred_at",
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    lead_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    actor_membership_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    activity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    activity_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        ACTIVITY_METADATA_TYPE,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now(), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
