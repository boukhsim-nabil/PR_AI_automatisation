from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.authorization import get_active_membership, require_permission
from app.db.base import Base
from app.db.models import Company, Membership, Permission, Role, RolePermission, User
from app.db.seeds import seed_rbac
from app.db.seeds.rbac import PERMISSION_DEFINITIONS, ROLE_PERMISSION_CODES
from app.middleware.tenant_security import AuthContext

pytestmark = pytest.mark.unit


@dataclass(frozen=True, slots=True)
class RbacFixture:
    session: Session
    auth: AuthContext
    viewer_role_id: UUID


@pytest.fixture()
def rbac_fixture() -> Iterator[RbacFixture]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    roles = seed_rbac(session)

    company = Company(name="Unit Tenant", status="active")
    user = User(email="rbac-unit@example.com", status="active")
    session.add_all([company, user])
    session.flush()
    membership = Membership(
        company_id=company.id,
        user_id=user.id,
        role_id=roles["owner"].id,
        status="active",
    )
    session.add(membership)
    session.commit()

    try:
        yield RbacFixture(
            session=session,
            auth=AuthContext(
                user_id=user.id,
                company_id=company.id,
                membership_id=membership.id,
                role_id=roles["viewer"].id,
            ),
            viewer_role_id=roles["viewer"].id,
        )
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_rbac_seed_is_idempotent(rbac_fixture: RbacFixture) -> None:
    session = rbac_fixture.session
    seed_rbac(session)
    seed_rbac(session)
    session.commit()

    assert session.scalar(select(func.count()).select_from(Role)) == 6
    permission_count = session.scalar(select(func.count()).select_from(Permission))
    assert permission_count == len(PERMISSION_DEFINITIONS)
    assert session.scalar(select(func.count()).select_from(RolePermission)) == sum(
        len(codes) for codes in ROLE_PERMISSION_CODES.values()
    )


def test_database_membership_role_wins_over_forged_jwt_role(
    rbac_fixture: RbacFixture,
) -> None:
    access = get_active_membership(rbac_fixture.auth, rbac_fixture.session)

    assert rbac_fixture.auth.role_id == rbac_fixture.viewer_role_id
    assert access.role is not None
    assert access.role.code == "owner"
    assert "members.manage" in access.permissions


def test_inactive_membership_is_always_rejected(rbac_fixture: RbacFixture) -> None:
    membership = rbac_fixture.session.get(Membership, rbac_fixture.auth.membership_id)
    assert membership is not None
    membership.status = "inactive"
    rbac_fixture.session.flush()

    with pytest.raises(HTTPException) as error:
        get_active_membership(rbac_fixture.auth, rbac_fixture.session)

    assert error.value.status_code == 403
    assert error.value.detail == "Active membership required"


def test_require_permission_denies_missing_permission(
    rbac_fixture: RbacFixture,
) -> None:
    access = get_active_membership(rbac_fixture.auth, rbac_fixture.session)
    restricted_access = type(access)(
        user=access.user,
        company=access.company,
        membership=access.membership,
        role=access.role,
        permissions=frozenset({"company.read"}),
    )
    dependency = require_permission("company.manage")
    request = Request({"type": "http", "state": {}})

    with pytest.raises(HTTPException) as error:
        dependency(request, restricted_access)

    assert error.value.status_code == 403
    assert error.value.detail == "Permission denied"
