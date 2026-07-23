from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

import pytest
from alembic.config import Config
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import app.db.session as db_session_module
from alembic import command
from app.api.authorization import MembershipAuthorization, require_permission
from app.core.security import hash_password
from app.db.models import Company, Membership, Role, User
from app.db.seeds import seed_rbac
from app.main import create_app

EXPECTED_TEST_DATABASE = "automation_test"
EXPECTED_TEST_USER = "automation_test"
EXPECTED_TEST_HOST = "127.0.0.1"
EXPECTED_TEST_PORT = 55432
INTEGRATION_EMAIL = "integration-user@example.com"
INTEGRATION_PASSWORD = "Integration-Only!9xK4pQ"
OTHER_INTEGRATION_EMAIL = "integration-user-beta@example.com"
OTHER_INTEGRATION_PASSWORD = "Integration-Beta-Only!7mN2"


@dataclass(frozen=True, slots=True)
class IntegrationIdentity:
    company_id: UUID
    other_company_id: UUID
    membership_id: UUID
    other_membership_id: UUID
    email: str
    password: str
    other_email: str
    other_password: str


def _guard_test_database_url(raw_url: str) -> str:
    try:
        url = make_url(raw_url)
    except Exception as exc:
        pytest.fail(f"TEST_DATABASE_URL is invalid: {exc}", pytrace=False)

    actual = (url.database, url.username, url.host, url.port or 5432)
    expected = (
        EXPECTED_TEST_DATABASE,
        EXPECTED_TEST_USER,
        EXPECTED_TEST_HOST,
        EXPECTED_TEST_PORT,
    )
    if not url.drivername.startswith("postgresql") or actual != expected:
        pytest.fail(
            "Unsafe TEST_DATABASE_URL. Integration tests only accept "
            "postgresql://automation_test@127.0.0.1:55432/automation_test.",
            pytrace=False,
        )

    development_url = make_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://automation:automation_dev_password@127.0.0.1:5432/automation",
        )
    )
    if url.render_as_string(hide_password=False) == development_url.render_as_string(
        hide_password=False
    ):
        pytest.fail(
            "TEST_DATABASE_URL points to DATABASE_URL; refusing to run integration tests.",
            pytrace=False,
        )

    return raw_url


@pytest.fixture(scope="session")
def test_database_url() -> str:
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.fail(
            "TEST_DATABASE_URL is required for integration tests. See backend/TESTING.md.",
            pytrace=False,
        )
    return _guard_test_database_url(raw_url)


@pytest.fixture(scope="session")
def migrated_engine(test_database_url: str) -> Iterator[Engine]:
    backend_dir = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(backend_dir / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", test_database_url.replace("%", "%%"))

    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_database_url
    try:
        command.upgrade(alembic_config, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url

    engine = create_engine(
        test_database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    with Session(engine) as session:
        seed_rbac(session)
        session.commit()
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE memberships, users, companies CASCADE"))
        engine.dispose()


@pytest.fixture()
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    connection = migrated_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def integration_identity(migrated_engine: Engine) -> Iterator[IntegrationIdentity]:
    with Session(migrated_engine, expire_on_commit=False) as session:
        owner_role = session.scalar(select(Role).where(Role.code == "owner"))
        viewer_role = session.scalar(select(Role).where(Role.code == "viewer"))
        assert owner_role is not None
        assert viewer_role is not None
        company = Company(name="Integration Tenant Alpha", status="active")
        other_company = Company(name="Integration Tenant Beta", status="active")
        user = User(
            email=INTEGRATION_EMAIL,
            password_hash=hash_password(INTEGRATION_PASSWORD),
            display_name="Integration User",
            status="active",
        )
        other_user = User(
            email=OTHER_INTEGRATION_EMAIL,
            password_hash=hash_password(OTHER_INTEGRATION_PASSWORD),
            display_name="Integration User Beta",
            status="active",
        )
        session.add_all([company, other_company, user, other_user])
        session.flush()

        membership = Membership(
            company_id=company.id,
            user_id=user.id,
            role_id=owner_role.id,
            status="active",
            joined_at=datetime.now(UTC),
        )
        other_membership = Membership(
            company_id=other_company.id,
            user_id=other_user.id,
            role_id=viewer_role.id,
            status="active",
            joined_at=datetime.now(UTC),
        )
        session.add_all([membership, other_membership])
        session.commit()

        identity = IntegrationIdentity(
            company_id=company.id,
            other_company_id=other_company.id,
            membership_id=membership.id,
            other_membership_id=other_membership.id,
            email=INTEGRATION_EMAIL,
            password=INTEGRATION_PASSWORD,
            other_email=OTHER_INTEGRATION_EMAIL,
            other_password=OTHER_INTEGRATION_PASSWORD,
        )

    try:
        yield identity
    finally:
        with Session(migrated_engine) as session:
            session.execute(
                delete(Company).where(
                    Company.id.in_([identity.company_id, identity.other_company_id])
                )
            )
            session.execute(
                delete(User).where(User.email.in_([INTEGRATION_EMAIL, OTHER_INTEGRATION_EMAIL]))
            )
            session.commit()


@pytest.fixture()
def integration_client(
    migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    testing_session_factory = sessionmaker(
        bind=migrated_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db_session_module, "SessionLocal", testing_session_factory)
    application = create_app()

    @application.get("/v1/test/crm-delete")
    def crm_delete_probe(
        _access: Annotated[
            MembershipAuthorization,
            Depends(require_permission("crm.delete")),
        ],
    ) -> dict[str, bool]:
        return {"allowed": True}

    with TestClient(application) as client:
        yield client
