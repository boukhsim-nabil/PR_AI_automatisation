from typing import Protocol
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AuthSession, Membership

pytestmark = pytest.mark.integration


class IntegrationIdentity(Protocol):
    company_id: UUID
    other_company_id: UUID
    membership_id: UUID
    other_membership_id: UUID
    email: str
    password: str
    other_email: str
    other_password: str


def _login(client: TestClient, identity: IntegrationIdentity):
    return client.post(
        "/v1/auth/login",
        json={
            "email": identity.email,
            "password": identity.password,
            "company_id": str(identity.company_id),
        },
    )


def _login_other_tenant(client: TestClient, identity: IntegrationIdentity):
    return client.post(
        "/v1/auth/login",
        json={
            "email": identity.other_email,
            "password": identity.other_password,
            "company_id": str(identity.other_company_id),
        },
    )


def test_valid_login_returns_access_token(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
) -> None:
    response = _login(integration_client, integration_identity)

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["company_id"] == str(integration_identity.company_id)
    assert payload["access_token"]


def test_inactive_membership_is_rejected(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        membership = session.get(Membership, integration_identity.membership_id)
        assert membership is not None
        membership.status = "inactive"
        session.commit()

    response = _login(integration_client, integration_identity)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials or inactive membership"}


def test_cross_tenant_access_is_rejected(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
) -> None:
    login_response = _login(integration_client, integration_identity)
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    response = integration_client.get(
        "/v1/auth/context",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Company-ID": str(integration_identity.other_company_id),
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-tenant access denied"}


def test_me_returns_minimal_current_rbac_context(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
) -> None:
    login_response = _login(integration_client, integration_identity)
    token = login_response.json()["access_token"]

    response = integration_client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["email"] == integration_identity.email
    assert payload["company"]["id"] == str(integration_identity.company_id)
    assert payload["membership"]["status"] == "active"
    assert payload["role"]["code"] == "owner"
    assert "company.manage" in payload["permissions"]
    assert "password_hash" not in str(payload)


def test_permission_dependency_uses_database_role_assignment(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
) -> None:
    owner_login = _login(integration_client, integration_identity)
    owner_token = owner_login.json()["access_token"]
    owner_response = integration_client.get(
        "/v1/test/crm-delete",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    viewer_login = _login_other_tenant(integration_client, integration_identity)
    viewer_token = viewer_login.json()["access_token"]
    viewer_response = integration_client.get(
        "/v1/test/crm-delete",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert owner_response.status_code == 200
    assert viewer_response.status_code == 403
    assert viewer_response.json() == {"detail": "Permission denied"}


def test_refresh_rotation_and_reuse_revoke_the_session_family(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    assert _login(integration_client, integration_identity).status_code == 200
    old_refresh = integration_client.cookies.get(settings.refresh_cookie_name)
    old_csrf = integration_client.cookies.get(settings.csrf_cookie_name)
    assert old_refresh and old_csrf

    rotated = integration_client.post("/v1/auth/refresh", headers={"X-CSRF-Token": old_csrf})
    assert rotated.status_code == 200
    assert integration_client.cookies.get(settings.refresh_cookie_name) != old_refresh

    integration_client.cookies.set(settings.refresh_cookie_name, old_refresh, path="/v1/auth")
    integration_client.cookies.set(settings.csrf_cookie_name, old_csrf, path="/v1/auth")
    reused = integration_client.post("/v1/auth/refresh", headers={"X-CSRF-Token": old_csrf})

    assert reused.status_code == 401
    assert reused.json()["detail"] == "Refresh token reuse detected"
    with Session(migrated_engine) as session:
        auth_session = session.scalar(
            select(AuthSession).where(
                AuthSession.membership_id == integration_identity.membership_id
            )
        )
        assert auth_session is not None
        assert auth_session.revoked_at is not None


def test_refresh_requires_active_membership_and_csrf(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    assert _login(integration_client, integration_identity).status_code == 200
    csrf = integration_client.cookies.get(settings.csrf_cookie_name)
    assert csrf
    assert integration_client.post("/v1/auth/refresh").status_code == 403

    with Session(migrated_engine) as session:
        membership = session.get(Membership, integration_identity.membership_id)
        assert membership is not None
        membership.status = "inactive"
        session.commit()

    response = integration_client.post("/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 401
    assert response.json()["detail"] == "Inactive membership"


def test_logout_all_revokes_every_session_for_current_membership(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    assert _login(integration_client, integration_identity).status_code == 200
    assert _login(integration_client, integration_identity).status_code == 200
    csrf = integration_client.cookies.get(settings.csrf_cookie_name)
    assert csrf

    response = integration_client.post("/v1/auth/logout-all", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 204
    with Session(migrated_engine) as session:
        sessions = session.scalars(
            select(AuthSession).where(
                AuthSession.membership_id == integration_identity.membership_id
            )
        ).all()
        assert len(sessions) == 2
        assert all(auth_session.revoked_at is not None for auth_session in sessions)
