from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

import app.api.routes.platform as platform_routes
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
    tenant_login = integration_client.post(
        "/v1/auth/login",
        json={
            "email": owner_email,
            "password": "Invited-Owner-Only!5qL8",
            "company_id": body["company"]["id"],
        },
    )
    assert tenant_login.status_code == 200, tenant_login.text
    assert (
        integration_client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {tenant_login.json()['access_token']}"},
        ).status_code
        == 200
    )
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


def test_new_owner_invitation_rejects_weak_password_and_missing_confirmation(
    integration_client: TestClient,
    platform_admin: dict[str, str],
) -> None:
    headers = _platform_headers(integration_client, platform_admin)
    owner_email = f"weak-password-{uuid4().hex[:8]}@example.com"
    created = integration_client.post(
        "/v1/platform/companies", headers=headers, json=_company_payload(owner_email)
    )
    assert created.status_code == 201, created.text
    invitation_id = created.json()["invitation"]["id"]
    email_file = Path(__file__).resolve().parents[3] / ".local" / "emails" / f"{invitation_id}.json"
    raw_token = json.loads(email_file.read_text(encoding="utf-8"))["accept_url"].split("token=", 1)[
        1
    ]

    weak = integration_client.post(
        "/v1/invitations/accept",
        json={
            "token": raw_token,
            "first_name": "Weak",
            "last_name": "Password",
            "password": "short",
            "password_confirmation": "short",
            "accept_terms": True,
        },
    )
    assert weak.status_code == 422
    missing_confirmation = integration_client.post(
        "/v1/invitations/accept",
        json={
            "token": raw_token,
            "first_name": "No",
            "last_name": "Confirmation",
            "password": "Strong-Enough-Password!7",
            "accept_terms": True,
        },
    )
    assert missing_confirmation.status_code == 422
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
    old_headers = {"Authorization": f"Bearer {tenant_login.json()['access_token']}"}
    assert integration_client.get("/v1/auth/me", headers=old_headers).status_code == 403
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


def test_existing_user_is_attached_without_duplicate(
    integration_client: TestClient,
    migrated_engine: Engine,
    platform_admin: dict[str, str],
    integration_identity,
) -> None:
    headers = _platform_headers(integration_client, platform_admin)
    created = integration_client.post(
        "/v1/platform/companies",
        headers=headers,
        json=_company_payload(integration_identity.email),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    invitation_id = body["invitation"]["id"]
    email_file = Path(__file__).resolve().parents[3] / ".local" / "emails" / f"{invitation_id}.json"
    raw_token = json.loads(email_file.read_text(encoding="utf-8"))["accept_url"].split("token=", 1)[
        1
    ]
    accepted = integration_client.post(
        "/v1/invitations/accept",
        json={"token": raw_token, "password": integration_identity.password},
    )
    assert accepted.status_code == 200, accepted.text

    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE automation_migrator"))
        assert (
            connection.scalar(
                text("SELECT count(*) FROM users WHERE email = :email"),
                {"email": integration_identity.email},
            )
            == 1
        )
        assert (
            connection.scalar(
                text(
                    """
                SELECT roles.code
                FROM memberships
                JOIN roles ON roles.id = memberships.role_id
                JOIN users ON users.id = memberships.user_id
                WHERE memberships.company_id = :company_id AND users.email = :email
                """
                ),
                {"company_id": body["company"]["id"], "email": integration_identity.email},
            )
            == "owner"
        )
    email_file.unlink(missing_ok=True)


def test_company_creation_rolls_back_when_invitation_fails(
    integration_client: TestClient,
    migrated_engine: Engine,
    platform_admin: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _platform_headers(integration_client, platform_admin)
    name = f"Rollback Company {uuid4().hex[:8]}"

    def fail_invitation(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic invitation failure")

    monkeypatch.setattr(platform_routes, "create_owner_invitation", fail_invitation)
    with pytest.raises(RuntimeError, match="synthetic invitation failure"):
        integration_client.post(
            "/v1/platform/companies",
            headers=headers,
            json={**_company_payload(f"rollback-{uuid4().hex[:8]}@example.com"), "name": name},
        )
    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE automation_migrator"))
        assert (
            connection.scalar(
                text("SELECT count(*) FROM companies WHERE name = :name"), {"name": name}
            )
            == 0
        )


def test_platform_database_role_cannot_read_tenant_business_data(
    migrated_engine: Engine,
    platform_admin: dict[str, str],
) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        with migrated_engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE automation_platform_app"))
            connection.execute(
                text("SELECT set_config('app.current_platform_user_id', :user_id, true)"),
                {"user_id": platform_admin["user_id"]},
            )
            connection.execute(text("SELECT * FROM contacts LIMIT 1"))
