import json
from typing import Protocol
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import AuditLog

pytestmark = pytest.mark.integration


class IntegrationIdentity(Protocol):
    company_id: UUID
    other_company_id: UUID
    membership_id: UUID
    email: str
    password: str
    other_email: str
    other_password: str


def _login(client: TestClient, identity: IntegrationIdentity, password: str | None = None):
    return client.post(
        "/v1/auth/login",
        json={
            "email": identity.email,
            "password": password or identity.password,
            "company_id": str(identity.company_id),
        },
        headers={"X-Correlation-ID": str(uuid4())},
    )


def test_login_audit_and_list_endpoint_are_tenant_scoped(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        session.add(
            AuditLog(
                company_id=integration_identity.other_company_id,
                action="tenant.beta.event",
                result="success",
                correlation_id=uuid4(),
                event_metadata={},
            )
        )
        session.commit()

    login_response = _login(integration_client, integration_identity)
    token = login_response.json()["access_token"]
    correlation_id = login_response.headers["x-correlation-id"]
    response = integration_client.get(
        "/v1/audit-logs?action=auth.login&result=success&limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["company_id"] == str(integration_identity.company_id)
    assert payload["items"][0]["correlation_id"] == correlation_id
    assert "tenant.beta.event" not in json.dumps(payload)


def test_failed_login_audit_contains_no_credentials(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    secret = "Wrong-Password-Never-Log!"
    response = _login(integration_client, integration_identity, password=secret)
    assert response.status_code == 401

    with Session(migrated_engine) as session:
        audit_log = session.scalar(
            select(AuditLog)
            .where(
                AuditLog.company_id == integration_identity.company_id,
                AuditLog.action == "auth.login",
                AuditLog.result == "failure",
            )
            .order_by(AuditLog.created_at.desc())
        )
        assert audit_log is not None
        serialized = json.dumps(audit_log.event_metadata)
        assert secret not in serialized
        assert "token" not in serialized.lower()


def test_application_role_cannot_update_or_delete_audit_events(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with Session(migrated_engine) as session:
        audit_log = AuditLog(
            company_id=integration_identity.company_id,
            action="resource.future_update",
            result="success",
            correlation_id=uuid4(),
            event_metadata={"resource": "safe"},
        )
        session.add(audit_log)
        session.commit()
        audit_id = audit_log.id

    connection = migrated_engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(text("SET LOCAL ROLE automation_app"))
        connection.execute(
            text("SELECT set_config('app.current_company_id', :company_id, true)"),
            {"company_id": str(integration_identity.company_id)},
        )
        with pytest.raises(DBAPIError):
            connection.execute(
                update(AuditLog).where(AuditLog.id == audit_id).values(result="altered")
            )
    finally:
        transaction.rollback()
        connection.close()


def test_security_and_session_actions_are_audited(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    login_response = _login(integration_client, integration_identity)
    token = login_response.json()["access_token"]
    csrf = integration_client.cookies.get("automation_csrf_token")
    assert csrf
    assert (
        integration_client.post("/v1/auth/refresh", headers={"X-CSRF-Token": csrf}).status_code
        == 200
    )
    assert (
        integration_client.get(
            "/v1/auth/context",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Company-ID": str(integration_identity.other_company_id),
            },
        ).status_code
        == 403
    )
    rotated_csrf = integration_client.cookies.get("automation_csrf_token")
    assert rotated_csrf
    assert (
        integration_client.post(
            "/v1/auth/logout", headers={"X-CSRF-Token": rotated_csrf}
        ).status_code
        == 204
    )

    viewer_login = integration_client.post(
        "/v1/auth/login",
        json={
            "email": integration_identity.other_email,
            "password": integration_identity.other_password,
            "company_id": str(integration_identity.other_company_id),
        },
    )
    viewer_token = viewer_login.json()["access_token"]
    assert (
        integration_client.get(
            "/v1/test/crm-delete",
            headers={"Authorization": f"Bearer {viewer_token}"},
        ).status_code
        == 403
    )

    with Session(migrated_engine) as session:
        tenant_a_actions = set(
            session.scalars(
                select(AuditLog.action).where(
                    AuditLog.company_id == integration_identity.company_id
                )
            )
        )
        tenant_b_actions = set(
            session.scalars(
                select(AuditLog.action).where(
                    AuditLog.company_id == integration_identity.other_company_id
                )
            )
        )

    assert {
        "auth.login",
        "auth.refresh",
        "auth.logout",
        "security.cross_tenant",
    } <= tenant_a_actions
    assert "authorization.permission_denied" in tenant_b_actions
