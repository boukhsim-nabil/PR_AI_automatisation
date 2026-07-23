from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("company_id", "email_normalized"),
        UniqueConstraint("company_id", "id"),
        ForeignKeyConstraint(
            ["company_id", "created_by_membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="status_allowed",
        ),
        Index("ix_contacts_company_id_status", "company_id", "status"),
        Index("ix_contacts_company_id_archived_at", "company_id", "archived_at"),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    email_normalized: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_normalized: Mapped[str | None] = mapped_column(String(40), index=True)
    job_title: Mapped[str | None] = mapped_column(String(160))
    organization_name: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="fr", server_default="fr"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    consent_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    consent_whatsapp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_by_membership_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        ForeignKeyConstraint(
            ["company_id", "contact_id"],
            ["contacts.company_id", "contacts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "assigned_membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "created_by_membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('new', 'to_qualify', 'qualified', 'appointment_scheduled', "
            "'proposal_sent', 'won', 'lost', 'archived')",
            name="status_allowed",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name="priority_allowed",
        ),
        CheckConstraint(
            "urgency IN ('low', 'medium', 'high', 'critical')",
            name="urgency_allowed",
        ),
        CheckConstraint(
            "source IN ('manual', 'form', 'email', 'whatsapp', 'referral', 'api')",
            name="source_allowed",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        CheckConstraint(
            "estimated_budget IS NULL OR estimated_budget >= 0",
            name="estimated_budget_non_negative",
        ),
        CheckConstraint(
            "status <> 'lost' OR (lost_reason IS NOT NULL AND length(trim(lost_reason)) > 0)",
            name="lost_reason_required",
        ),
        Index("ix_leads_company_id_status", "company_id", "status"),
        Index("ix_leads_company_id_priority", "company_id", "priority"),
        Index("ix_leads_company_id_source", "company_id", "source"),
        Index("ix_leads_company_id_assigned", "company_id", "assigned_membership_id"),
        Index("ix_leads_company_id_created_at", "company_id", "created_at"),
        Index("ix_leads_company_id_archived_at", "company_id", "archived_at"),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    need_description: Mapped[str | None] = mapped_column(Text)
    estimated_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="MAD", server_default="MAD"
    )
    urgency: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium", server_default="medium"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    score: Mapped[int] = mapped_column(nullable=False, default=0, server_default=text("0"))
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium", server_default="medium"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="new", server_default="new"
    )
    assigned_membership_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    next_action: Mapped[str | None] = mapped_column(String(500))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lost_reason: Mapped[str | None] = mapped_column(String(1000))
    created_by_membership_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
