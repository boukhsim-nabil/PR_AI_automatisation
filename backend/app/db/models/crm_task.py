from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CrmTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crm_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "lead_id"],
            ["leads.company_id", "leads.id"],
            ondelete="RESTRICT",
        ),
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
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="priority_allowed",
        ),
        CheckConstraint(
            "status IN ('todo', 'in_progress', 'completed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint(
            "lead_id IS NOT NULL OR contact_id IS NOT NULL",
            name="resource_required",
        ),
        CheckConstraint(
            "status <> 'completed' OR completed_at IS NOT NULL",
            name="completed_at_required",
        ),
        Index("ix_crm_tasks_company_status_due", "company_id", "status", "due_at"),
        Index(
            "ix_crm_tasks_company_assigned_status", "company_id", "assigned_membership_id", "status"
        ),
        Index("ix_crm_tasks_company_lead", "company_id", "lead_id"),
    )

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium", server_default="medium"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="todo", server_default="todo"
    )
    assigned_membership_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_membership_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
