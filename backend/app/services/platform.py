from __future__ import annotations

import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.sessions import token_hash
from app.db.models import Company, CompanyInvitation
from app.services.audit import AuditService


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:140] or "company"


class EmailSender:
    def send_owner_invitation(
        self, *, invitation_id: UUID, email: str, company_name: str, token: str
    ) -> None:
        raise NotImplementedError


class DevelopmentFileEmailSender(EmailSender):
    def __init__(self) -> None:
        self.outbox = Path(__file__).resolve().parents[3] / ".local" / "emails"

    def send_owner_invitation(
        self, *, invitation_id: UUID, email: str, company_name: str, token: str
    ) -> None:
        self.outbox.mkdir(parents=True, exist_ok=True)
        payload = {
            "to": email,
            "subject": f"Invitation Owner — {company_name}",
            "accept_url": f"http://localhost:3000/invitations/accept?token={token}",
        }
        (self.outbox / f"{invitation_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def create_owner_invitation(
    db: Session,
    *,
    company: Company,
    email: str,
    invited_by: UUID,
    sender: EmailSender | None = None,
    expires_hours: int = 72,
) -> CompanyInvitation:
    normalized = normalize_email(email)
    existing = db.scalar(
        select(CompanyInvitation).where(
            CompanyInvitation.company_id == company.id,
            CompanyInvitation.email_normalized == normalized,
            CompanyInvitation.status == "pending",
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Active owner invitation already exists")
    raw_token = secrets.token_urlsafe(48)
    invitation = CompanyInvitation(
        company_id=company.id,
        email_normalized=normalized,
        token_hash=token_hash(raw_token),
        invited_by_platform_user_id=invited_by,
        expires_at=datetime.now(UTC) + timedelta(hours=expires_hours),
    )
    db.add(invitation)
    db.flush()
    (sender or DevelopmentFileEmailSender()).send_owner_invitation(
        invitation_id=invitation.id,
        email=normalized,
        company_name=company.name,
        token=raw_token,
    )
    return invitation


def platform_audit(
    db: Session,
    *,
    correlation_id: UUID,
    action: str,
    result: str,
    actor_user_id: UUID | None = None,
    company_id: UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    clean_metadata = AuditService.sanitize_metadata(metadata or {})
    db.execute(
        text(
            """
            SELECT platform_write_audit(
                :actor_user_id,
                :company_id,
                :action,
                :result,
                :resource_type,
                :resource_id,
                :correlation_id,
                CAST(:metadata AS jsonb)
            )
            """
        ),
        {
            "actor_user_id": actor_user_id,
            "company_id": company_id,
            "action": action,
            "result": result,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "correlation_id": correlation_id,
            "metadata": json.dumps(clean_metadata),
        },
    )
