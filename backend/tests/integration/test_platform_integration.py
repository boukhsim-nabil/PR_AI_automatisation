from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.sessions import token_hash
from app.db.models import (
    AuthSession,
)

pytestmark = pytest.mark.integration

PLATFORM_EMAIL = "platform-integration@example.com"
PLATFORM_PASSWORD = "Platform-Integration!8sQ4"


@pytest.fixture()
def platform_admin(migrated_engine: Engine) -> dict[str, str]:
    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE automation_migrator"))
        role_id = connection.scalar(
            text("SELECT id FROM platform_roles WHERE code = 'platform_super_admin'")
        )
        user_id = connection.scalar(
            text(
                """
                INSERT INTO users (email, password_hash, display_name, status)
                VALUES (:email, :password_hash, 'Platform Integration', 'active')
                ON CONFLICT (email) DO UPDATE SET password_hash = excluded.password_hash
                RETURNING id
                """
            ),
            {"email": PLATFORM_EMAIL, "password_hash": hash_password(PLATFORM_PASSWORD)},
        )
        connection.execute(
            text(
                """
                INSERT INTO platform_user_roles (user_id, platform_role_id)
                VALUES (:user_id, :role_id)
                ON CONFLICT DO NOTHING
                """
            ),
            {"user_id": user_id, "role_id": role_id},
        )
    yield {"email": PLATFORM_EMAIL, "password": PLATFORM_PASSWORD, "user_id": str(user_id)}
    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE automation_migrator"))
        connection.execute(
            text("DELETE FROM companies WHERE created_by_platform_user_id = :user_id"),
            {"user_id": user_id},
        )
        connection.execute(
            text("DELETE FROM company_invitations WHERE invited_by_platform_user_id = :user_id"),
            {"user_id": user_id},
        )
        connection.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})


def _platform_headers(client: TestClient, platform_admin: dict[str, str]) -> dict[str, str]:
    response = client.post(
        "/v1/platform-auth/login",
        json={"email": platform_admin["email"], "password": platform_admin["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _company_payload(owner_email: str) -> dict[str, object]:
    return {
        "name": f"Platform Test {uuid4().hex[:8]}",
        "sector": "Services",
        "plan_code": "trial",
        "trial_days": 21,
        "owner_first_name": "Owner",
        "owner_last_name": "Test",
        "owner_email": owner_email,
    }


def test_platform_access_is_separate_and_company_creation_is_transactional(
    integration_client: TestClient,
    migrated_engine: Engine,
    platform_admin: dict[str, str],
    integration_identity,
) -> None:
    assert integration_client.get("/v1/platform/summary").status_code == 401
    tenant_login = integration_client.post(
        "/v1/auth/login",
        json={
            "email": integration_identity.email,
            "password": integration_identity.password,
            "company_id": str(integration_identity.company_id),
        },
    )
    tenant_headers = {"Authorization": f"Bearer {tenant_login.json()['access_token']}"}
    assert integration_client.get("/v1/platform/summary", headers=tenant_headers).status_code in {
        401,
        403,
    }

    headers = _platform_headers(integration_client, platform_admin)
    owner_email = f"new-owner-{uuid4().hex[:8]}@example.com"
    response = integration_client.post(
        "/v1/platform/companies",
        headers=headers,
        json=_company_payload(owner_email),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["company"]["country"] == "MA"
    assert body["company"]["language"] == "fr"
    assert body["company"]["currency"] == "MAD"
    assert body["company"]["timezone"] == "Africa/Casablanca"
    assert body["invitation"]["email"] == owner_email
    assert "token" not in json.dumps(body).lower()

    with migrated_engine.connect() as connection:
        connection.execute(text("SET ROLE automation_migrator"))
        invitation_hash = connection.scalar(
            text("SELECT token_hash FROM company_invitations WHERE id = :id"),
            {"id": body["invitation"]["id"]},
        )
        assert invitation_hash is not None
        assert len(invitation_hash) == 64
        assert connection.scalar(
            text(
                """
                SELECT id FROM platform_audit_logs
                WHERE action = 'platform.company.created' AND company_id = :company_id
                """
            ),
            {"company_id": body["company"]["id"]},
        )


def test_owner_invitation_new_user_is_single_use_and_role_is_backend_imposed(
    integration_client: TestClient,
    migrated_engine: Engine,
    platform_admin: dict[str, str],
) -> None:
    headers = _platform_headers(integration_client, platform_admin)
    owner_email = f"invite-owner-{uuid4().hex[:8]}@example.com"
    created = integration_client.post(
        "/v1/platform/companies", headers=headers, json=_company_payload(owner_email)
    )
    assert created.status_code == 201, created.text
    body = created.json()
    invitation_id = body["invitation"]["id"]
    email_file = Path(__file__).resolve().parents[3] / ".local" / "emails" / f"{invitation_id}.json"
    message = json.loads(email_file.read_text(encoding="utf-8"))
    raw_token = message["accept_url"].split("token=", 1)[1]

    validated = integration_client.get("/v1/invitations/validate", params={"token": raw_token})
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    accepted = integration_client.post(
        "/v1/invitations/accept",
        json={
            "token": raw_token,
            "first_name": "Owner",
            "last_name": "Invitation",
            "password": "Invited-Owner-Only!5qL8",
            "password_confirmation": "Invited-Owner-Only!5qL8",
            "accept_terms": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    reused = integration_client.post(
        "/v1/invitations/accept",
        json={"token": raw_token, "password": "Invited-Owner-Only!5qL8"},
    )
    assert reused.status_code == 410

    with migrated_engine.connect() as connection:
        membership = connection.execute(
            text(
                """
                SELECT memberships.status, roles.code
                FROM memberships
                JOIN users ON users.id = memberships.user_id
                JOIN roles ON roles.id = memberships.role_id
                WHERE users.email = :email AND memberships.company_id = :company_id
                """
            ),
            {"email": owner_email, "company_id": body["company"]["id"]},
        ).one()
        assert membership == ("active", "owner")
        assert (
            connection.scalar(
                text("SELECT count(*) FROM users WHERE email = :email"), {"email": owner_email}
            )
            == 1
        )
    email_file.unlink(missing_ok=True)


def test_suspension_revokes_sessions_and_reactivation_does_not_restore_them(
    integration_client: TestClient,
    migrated_engine: Engine,
    platform_admin: dict[str, str],
    integration_identity,
) -> None:
    tenant_login = integration_client.post(
        "/v1/auth/login",
        json={
            "email": integration_identity.email,
            "password": integration_identity.password,
            "company_id": str(integration_identity.company_id),
        },
    )
    assert tenant_login.status_code == 200
    headers = _platform_headers(integration_client, platform_admin)
    suspended = integration_client.post(
        f"/v1/platform/companies/{integration_identity.company_id}/suspend",
        headers=headers,
        json={"reason": "Integration security suspension"},
    )
    assert suspended.status_code == 200, suspended.text
    assert (
        integration_client.post(
            "/v1/auth/login",
            json={
                "email": integration_identity.email,
                "password": integration_identity.password,
                "company_id": str(integration_identity.company_id),
            },
        ).status_code
        == 401
    )
    reactivated = integration_client.post(
        f"/v1/platform/companies/{integration_identity.company_id}/reactivate",
        headers=headers,
    )
    assert reactivated.status_code == 200
    with Session(migrated_engine) as db:
        assert (
            db.scalar(
                select(AuthSession.revoked_at).where(
                    AuthSession.company_id == integration_identity.company_id
                )
            )
            is not None
        )
    assert (
        integration_client.post(
            "/v1/auth/login",
            json={
                "email": integration_identity.email,
                "password": integration_identity.password,
                "company_id": str(integration_identity.company_id),
            },
        ).status_code
        == 200
    )


def test_expired_and_revoked_invitations_are_refused(
    integration_client: TestClient,
    migrated_engine: Engine,
    platform_admin: dict[str, str],
) -> None:
    for invitation_status in ("pending", "revoked"):
        raw_token = f"test-token-{uuid4().hex}"
        with migrated_engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE automation_migrator"))
            platform_user_id = connection.scalar(
                text("SELECT user_id FROM platform_user_roles LIMIT 1")
            )
            company_id = connection.scalar(
                text(
                    """
                    INSERT INTO companies (name, slug, status)
                    VALUES (:name, :slug, 'pending') RETURNING id
                    """
                ),
                {"name": "Expired Invite", "slug": f"expired-{uuid4().hex[:10]}"},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO company_invitations (
                        company_id, email_normalized, token_hash, status,
                        invited_by_platform_user_id, expires_at, revoked_at
                    )
                    VALUES (
                            :company_id, :email, :token_hash, :status,
                        :user_id, :expires_at, :revoked_at
                    )
                    """
                ),
                {
                    "company_id": company_id,
                    "email": f"expired-{uuid4().hex[:8]}@example.com",
                    "token_hash": token_hash(raw_token),
                    "status": invitation_status,
                    "user_id": platform_user_id,
                    "expires_at": datetime.now(UTC) - timedelta(minutes=1),
                    "revoked_at": datetime.now(UTC) if invitation_status == "revoked" else None,
                },
            )
        response = integration_client.post(
            "/v1/invitations/accept",
            json={"token": raw_token, "password": "Invitation-Invalid!2xR9"},
        )
        assert response.status_code == 410
