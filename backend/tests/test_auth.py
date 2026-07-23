from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import hash_password
from app.core.sessions import token_hash
from app.db.base import Base
from app.db.models import AuthSession, Company, Membership, RefreshToken, User
from app.db.seeds import seed_rbac
from app.db.session import get_db
from app.main import create_app

TEST_EMAIL = "unit-user@example.com"
TEST_PASSWORD = "UnitTest-Only-Password!42"

pytestmark = pytest.mark.unit


@pytest.fixture()
def auth_client() -> Iterator[tuple[TestClient, UUID, Session]]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    session: Session = TestingSession()
    roles = seed_rbac(session)

    company = Company(name="Acme Corp", status="active")
    user = User(
        email=TEST_EMAIL,
        password_hash=hash_password(TEST_PASSWORD),
        display_name="Acme Admin",
        status="active",
    )
    session.add_all([company, user])
    session.flush()
    session.add(
        Membership(
            company_id=company.id,
            user_id=user.id,
            role_id=roles["owner"].id,
            status="active",
            joined_at=datetime.now(UTC),
        )
    )
    session.commit()

    application = create_app()
    application.state.audit_enabled = False

    def override_get_db() -> Iterator[Session]:
        yield session

    application.dependency_overrides[get_db] = override_get_db

    try:
        assert session.bind is not None
        assert session.bind.dialect.name == "sqlite"
        with TestClient(application) as client:
            yield client, company.id, session
    finally:
        application.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_login_rejects_reserved_test_domain(
    auth_client: tuple[TestClient, UUID, Session],
) -> None:
    client, company_id, _session = auth_client

    response = client.post(
        "/v1/auth/login",
        json={
            "email": "unit-user@example.test",
            "password": TEST_PASSWORD,
            "company_id": str(company_id),
        },
    )

    assert response.status_code == 422


def test_login_returns_access_token(
    auth_client: tuple[TestClient, UUID, Session],
) -> None:
    client, company_id, _session = auth_client

    response = client.post(
        "/v1/auth/login",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "company_id": str(company_id),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["company_id"] == str(company_id)
    assert isinstance(payload["access_token"], str)
    assert payload["access_token"]
    assert settings.refresh_cookie_name not in payload
    assert client.cookies.get(settings.refresh_cookie_name)
    assert client.cookies.get(settings.csrf_cookie_name)


def test_refresh_token_is_hashed_and_rotated(
    auth_client: tuple[TestClient, UUID, Session],
) -> None:
    client, company_id, session = auth_client
    client.post(
        "/v1/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "company_id": str(company_id)},
    )
    old_refresh = client.cookies.get(settings.refresh_cookie_name)
    old_csrf = client.cookies.get(settings.csrf_cookie_name)
    assert old_refresh and old_csrf
    stored = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash(old_refresh))
    )
    assert stored is not None
    assert stored.token_hash != old_refresh

    response = client.post("/v1/auth/refresh", headers={"X-CSRF-Token": old_csrf})

    assert response.status_code == 200
    assert "refresh_token" not in response.json()
    assert client.cookies.get(settings.refresh_cookie_name) != old_refresh
    session.refresh(stored)
    assert stored.used_at is not None
    assert stored.replaced_by_id is not None


def test_reusing_rotated_refresh_token_revokes_session_family(
    auth_client: tuple[TestClient, UUID, Session],
) -> None:
    client, company_id, session = auth_client
    client.post(
        "/v1/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "company_id": str(company_id)},
    )
    old_refresh = client.cookies.get(settings.refresh_cookie_name)
    old_csrf = client.cookies.get(settings.csrf_cookie_name)
    assert old_refresh and old_csrf
    assert client.post("/v1/auth/refresh", headers={"X-CSRF-Token": old_csrf}).status_code == 200

    client.cookies.set(settings.refresh_cookie_name, old_refresh, path="/v1/auth")
    client.cookies.set(settings.csrf_cookie_name, old_csrf, path="/v1/auth")
    response = client.post("/v1/auth/refresh", headers={"X-CSRF-Token": old_csrf})

    assert response.status_code == 401
    assert response.json()["detail"] == "Refresh token reuse detected"
    auth_session = session.scalar(select(AuthSession))
    assert auth_session is not None
    assert auth_session.revoked_at is not None


def test_expired_refresh_session_is_rejected(
    auth_client: tuple[TestClient, UUID, Session],
) -> None:
    client, company_id, session = auth_client
    client.post(
        "/v1/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "company_id": str(company_id)},
    )
    csrf = client.cookies.get(settings.csrf_cookie_name)
    auth_session = session.scalar(select(AuthSession))
    assert csrf and auth_session is not None
    auth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()

    response = client.post("/v1/auth/refresh", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 401
    assert response.json()["detail"] == "Refresh session expired or revoked"


def test_logout_revokes_current_session(
    auth_client: tuple[TestClient, UUID, Session],
) -> None:
    client, company_id, session = auth_client
    client.post(
        "/v1/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "company_id": str(company_id)},
    )
    csrf = client.cookies.get(settings.csrf_cookie_name)
    assert csrf

    response = client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 204
    auth_session = session.scalar(select(AuthSession))
    assert auth_session is not None
    assert auth_session.revoked_at is not None


def test_authenticated_user_can_read_auth_context(
    auth_client: tuple[TestClient, UUID, Session],
) -> None:
    client, company_id, _session = auth_client
    login_response = client.post(
        "/v1/auth/login",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "company_id": str(company_id),
        },
    )
    access_token = login_response.json()["access_token"]

    response = client.get(
        "/v1/auth/context",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["company_id"] == str(company_id)


def test_authenticated_user_can_read_minimal_me_context(
    auth_client: tuple[TestClient, UUID, Session],
) -> None:
    client, company_id, _session = auth_client
    login_response = client.post(
        "/v1/auth/login",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "company_id": str(company_id),
        },
    )
    token = login_response.json()["access_token"]

    response = client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["company"]["id"] == str(company_id)
    assert payload["role"]["code"] == "owner"
    assert "company.manage" in payload["permissions"]
    assert set(payload) == {"user", "company", "membership", "role", "permissions"}


def test_login_rejects_suspended_company(
    auth_client: tuple[TestClient, UUID, Session],
) -> None:
    client, company_id, session = auth_client
    company = session.get(Company, company_id)
    assert company is not None
    company.status = "suspended"
    session.commit()

    response = client.post(
        "/v1/auth/login",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "company_id": str(company_id),
        },
    )

    assert response.status_code == 401
