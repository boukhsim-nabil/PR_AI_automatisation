from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import configure_mappers

from app.db.base import Base
from app.db.models import Company, Membership, User


def test_identity_mappers_are_configured() -> None:
    configure_mappers()

    assert {"companies", "users", "memberships"} <= set(Base.metadata.tables)


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
