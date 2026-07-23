import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import configure_mappers

from app.db.base import Base
from app.db.models import (
    AuditLog,
    Company,
    Contact,
    CrmActivity,
    CrmTask,
    Lead,
    Membership,
    Permission,
    Role,
    RolePermission,
    User,
)

pytestmark = pytest.mark.unit


def test_identity_mappers_are_configured() -> None:
    configure_mappers()

    assert {
        "companies",
        "users",
        "memberships",
        "roles",
        "permissions",
        "role_permissions",
        "audit_logs",
        "contacts",
        "crm_activities",
        "crm_tasks",
        "leads",
    } <= set(Base.metadata.tables)


def test_all_identity_tables_have_audit_timestamps() -> None:
    for model in (Company, User, Membership):
        assert "created_at" in model.__table__.c
        assert "updated_at" in model.__table__.c


def test_membership_is_scoped_to_a_company_uuid() -> None:
    company_id = Membership.__table__.c.company_id
    foreign_keys = {foreign_key.target_fullname for foreign_key in company_id.foreign_keys}

    assert company_id.nullable is False
    assert company_id.type.as_uuid is True
    assert foreign_keys == {"companies.id"}


def test_user_can_have_only_one_membership_per_company() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in Membership.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("company_id", "user_id") in unique_columns


def test_membership_role_has_a_real_foreign_key() -> None:
    role_id = Membership.__table__.c.role_id
    foreign_keys = {foreign_key.target_fullname for foreign_key in role_id.foreign_keys}

    assert foreign_keys == {"roles.id"}


def test_rbac_models_have_a_composite_role_permission_key() -> None:
    assert {column.name for column in RolePermission.__table__.primary_key.columns} == {
        "role_id",
        "permission_id",
    }
    for model in (Role, Permission):
        unique_columns = {
            tuple(column.name for column in constraint.columns)
            for constraint in model.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert ("code",) in unique_columns


def test_audit_log_contains_required_minimal_fields() -> None:
    assert {
        "id",
        "company_id",
        "actor_user_id",
        "actor_membership_id",
        "action",
        "resource_type",
        "resource_id",
        "result",
        "ip_address",
        "user_agent",
        "correlation_id",
        "metadata",
        "created_at",
    } <= {column.name for column in AuditLog.__table__.c}


def test_crm_models_are_tenant_scoped_and_traceable() -> None:
    for model in (Contact, Lead):
        columns = model.__table__.c
        assert columns.company_id.nullable is False
        assert columns.created_by_membership_id.nullable is False
        assert columns.id.type.as_uuid is True
        assert {"created_at", "updated_at", "archived_at"} <= set(columns.keys())
        unique_columns = {
            tuple(column.name for column in constraint.columns)
            for constraint in model.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        if model is Contact:
            assert ("company_id", "email_normalized") in unique_columns


def test_operational_crm_history_and_tasks_are_tenant_scoped() -> None:
    assert CrmActivity.__table__.c.company_id.nullable is False
    assert "updated_at" not in CrmActivity.__table__.c
    assert CrmTask.__table__.c.company_id.nullable is False
    assert {"created_at", "updated_at", "completed_at"} <= set(CrmTask.__table__.c.keys())
