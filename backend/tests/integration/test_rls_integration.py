from typing import Protocol
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, select, text, update
from sqlalchemy.exc import DBAPIError

from app.db.models import Membership

pytestmark = pytest.mark.integration


class IntegrationIdentity(Protocol):
    company_id: UUID
    other_company_id: UUID
    membership_id: UUID
    other_membership_id: UUID


def _set_app_tenant(connection, company_id: UUID | None = None) -> None:
    connection.execute(text("SET LOCAL ROLE automation_app"))
    if company_id is not None:
        connection.execute(
            text("SELECT set_config('app.current_company_id', :company_id, true)"),
            {"company_id": str(company_id)},
        )


def test_tenant_reads_its_own_membership(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_tenant(connection, integration_identity.company_id)
        membership_ids = (
            connection.execute(select(Membership.id).order_by(Membership.id)).scalars().all()
        )

    assert membership_ids == [integration_identity.membership_id]


def test_tenant_never_reads_another_tenants_membership(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_tenant(connection, integration_identity.company_id)
        other_membership = connection.execute(
            select(Membership.id).where(Membership.id == integration_identity.other_membership_id)
        ).scalar_one_or_none()

    assert other_membership is None


def test_query_without_tenant_context_returns_no_memberships(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_tenant(connection)
        membership_ids = connection.execute(select(Membership.id)).scalars().all()

    assert membership_ids == []


def test_cross_tenant_update_is_rejected(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    connection = migrated_engine.connect()
    transaction = connection.begin()
    try:
        _set_app_tenant(connection, integration_identity.company_id)
        with pytest.raises(DBAPIError, match="row-level security"):
            connection.execute(
                update(Membership)
                .where(Membership.id == integration_identity.membership_id)
                .values(company_id=integration_identity.other_company_id)
            )
    finally:
        transaction.rollback()
        connection.close()


def test_transaction_local_tenant_does_not_leak_through_pool(
    test_database_url: str,
    integration_identity: IntegrationIdentity,
) -> None:
    single_connection_engine = create_engine(
        test_database_url,
        pool_size=1,
        max_overflow=0,
        connect_args={"connect_timeout": 5},
    )
    try:
        with single_connection_engine.begin() as connection:
            first_backend_pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            _set_app_tenant(connection, integration_identity.company_id)
            assert connection.execute(select(Membership.id)).scalars().all() == [
                integration_identity.membership_id
            ]

        with single_connection_engine.begin() as connection:
            second_backend_pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            _set_app_tenant(connection)
            assert connection.execute(select(Membership.id)).scalars().all() == []

        assert first_backend_pid == second_backend_pid
    finally:
        single_connection_engine.dispose()


def test_database_roles_are_separated(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        roles = dict(
            connection.execute(
                text(
                    "SELECT rolname, rolbypassrls FROM pg_roles "
                    "WHERE rolname IN ('automation_app', 'automation_migrator')"
                )
            ).all()
        )

    assert roles == {"automation_app": False, "automation_migrator": True}


def test_all_company_scoped_tables_force_rls(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        tenant_tables = connection.execute(
            text(
                """
                SELECT columns.table_name, classes.relrowsecurity,
                       classes.relforcerowsecurity,
                       pg_get_userbyid(classes.relowner) AS owner
                FROM information_schema.columns AS columns
                JOIN pg_class AS classes ON classes.relname = columns.table_name
                JOIN pg_namespace AS namespaces ON namespaces.oid = classes.relnamespace
                WHERE columns.table_schema = 'public'
                  AND columns.column_name = 'company_id'
                  AND namespaces.nspname = 'public'
                ORDER BY columns.table_name
                """
            )
        ).all()

    assert tenant_tables == [
        ("audit_logs", True, True, "automation_migrator"),
        ("auth_sessions", True, True, "automation_migrator"),
        ("company_invitations", True, True, "automation_migrator"),
        ("contacts", True, True, "automation_migrator"),
        ("conversation_notes", True, True, "automation_migrator"),
        ("conversation_participants", True, True, "automation_migrator"),
        ("conversation_tag_links", True, True, "automation_migrator"),
        ("conversation_tags", True, True, "automation_migrator"),
        ("conversations", True, True, "automation_migrator"),
        ("crm_activities", True, True, "automation_migrator"),
        ("crm_tasks", True, True, "automation_migrator"),
        ("leads", True, True, "automation_migrator"),
        ("memberships", True, True, "automation_migrator"),
        ("message_attachments", True, True, "automation_migrator"),
        ("messages", True, True, "automation_migrator"),
        ("platform_audit_logs", True, True, "automation_migrator"),
    ]
