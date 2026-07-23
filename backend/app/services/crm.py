from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Contact, CrmActivity, CrmTask, Lead, Membership
from app.services.audit import AuditService


def normalize_email(value: str | None) -> str | None:
    return value.strip().casefold() if value else None


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    prefix = "+" if value.strip().startswith("+") else ""
    digits = re.sub(r"\D", "", value)
    return f"{prefix}{digits}" if digits else None


def get_contact(db: Session, company_id: UUID, contact_id: UUID) -> Contact:
    contact = db.scalar(
        select(Contact).where(Contact.id == contact_id, Contact.company_id == company_id)
    )
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


def get_lead(db: Session, company_id: UUID, lead_id: UUID) -> Lead:
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id))
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return lead


def get_task(db: Session, company_id: UUID, task_id: UUID) -> CrmTask:
    task = db.scalar(select(CrmTask).where(CrmTask.id == task_id, CrmTask.company_id == company_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def ensure_active_membership(
    db: Session,
    company_id: UUID,
    membership_id: UUID | None,
) -> None:
    if membership_id is None:
        return
    found = db.scalar(
        select(Membership.id).where(
            Membership.id == membership_id,
            Membership.company_id == company_id,
            Membership.status == "active",
        )
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Assigned membership must be active and belong to the current company",
        )


def ensure_contact_accepts_lead(contact: Contact) -> None:
    if contact.status == "archived" or contact.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived contact must be restored before creating a lead",
        )


def ensure_lead_modifiable(lead: Lead) -> None:
    if lead.status == "archived" or lead.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived lead cannot be modified without explicit restoration",
        )


def add_activity(
    db: Session,
    *,
    company_id: UUID,
    contact_id: UUID | None,
    lead_id: UUID | None,
    actor_membership_id: UUID | None,
    activity_type: str,
    subject: str,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> CrmActivity:
    activity = CrmActivity(
        company_id=company_id,
        contact_id=contact_id,
        lead_id=lead_id,
        actor_membership_id=actor_membership_id,
        activity_type=activity_type,
        subject=subject,
        description=description,
        activity_metadata=AuditService.sanitize_metadata(metadata or {}),
        occurred_at=occurred_at or datetime.now(UTC),
    )
    db.add(activity)
    db.flush()
    return activity


def flush_or_conflict(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A contact with this email already exists for this company",
        ) from exc
