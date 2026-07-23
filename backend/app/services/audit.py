from __future__ import annotations

import logging
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

import app.db.session as db_session_module
from app.db.models import AuditLog
from app.db.tenant import enforce_application_role, set_current_company

logger = logging.getLogger(__name__)
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "authorization",
    "cookie",
    "jwt",
    "token",
    "api_key",
    "apikey",
    "secret",
    "private_key",
)
JWT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    company_id: UUID
    action: str
    result: str
    actor_user_id: UUID | None = None
    actor_membership_id: UUID | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    metadata: Mapping[str, Any] | None = None


class AuditService:
    @classmethod
    def record(cls, scope: MutableMapping[str, Any], event: AuditEvent) -> None:
        state = scope.setdefault("state", {})
        state.setdefault("audit_events", []).append(event)

    @classmethod
    def sanitize_metadata(cls, value: Any, *, key: str = "") -> Any:
        normalized_key = key.lower().replace("-", "_")
        if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
            return "[REDACTED]"
        if isinstance(value, Mapping):
            return {
                str(item_key): cls.sanitize_metadata(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [cls.sanitize_metadata(item) for item in value]
        if isinstance(value, str):
            if value.lower().startswith("bearer ") or JWT_PATTERN.fullmatch(value):
                return "[REDACTED]"
            return value[:2000]
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:2000]

    @classmethod
    def flush(cls, scope: MutableMapping[str, Any]) -> None:
        state = scope.get("state", {})
        events: list[AuditEvent] = state.pop("audit_events", [])
        application = scope.get("app")
        if not events or (
            application is not None and getattr(application.state, "audit_enabled", True) is False
        ):
            return
        correlation_id = cls._correlation_id(state.get("correlation_id"))
        headers = dict(scope.get("headers", []))
        user_agent = headers.get(b"user-agent", b"").decode("latin-1")[:500] or None
        client = scope.get("client")
        ip_address = str(client[0])[:45] if client else None
        factory = (
            getattr(application.state, "audit_session_factory", None)
            if application is not None
            else None
        )
        factory = factory or db_session_module.SessionLocal

        for event in events:
            try:
                with factory() as session, session.begin():
                    enforce_application_role(session)
                    set_current_company(session, event.company_id)
                    session.add(
                        AuditLog(
                            company_id=event.company_id,
                            actor_user_id=event.actor_user_id,
                            actor_membership_id=event.actor_membership_id,
                            action=event.action[:120],
                            resource_type=event.resource_type[:120]
                            if event.resource_type
                            else None,
                            resource_id=event.resource_id[:255] if event.resource_id else None,
                            result=event.result[:32],
                            ip_address=ip_address,
                            user_agent=user_agent,
                            correlation_id=correlation_id,
                            event_metadata=cls.sanitize_metadata(event.metadata or {}),
                        )
                    )
            except SQLAlchemyError:
                logger.exception("Unable to persist audit event %s", event.action)

    @staticmethod
    def _correlation_id(value: Any) -> UUID:
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return uuid4()
