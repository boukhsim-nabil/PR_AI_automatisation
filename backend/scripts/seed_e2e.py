import os
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import (
    Company,
    Contact,
    Lead,
    Membership,
    PlatformRole,
    PlatformUserRole,
    User,
)
from app.db.seeds import seed_rbac
from app.db.session import SessionLocal

E2E_COMPANY_ID = UUID("11111111-1111-4111-8111-111111111111")
E2E_USER_ID = UUID("22222222-2222-4222-8222-222222222222")
E2E_OWNER_MEMBERSHIP_ID = UUID("12121212-1212-4121-8121-121212121212")
E2E_EMAIL = "e2e-user@example.com"
E2E_VIEWER_ID = UUID("33333333-3333-4333-8333-333333333333")
E2E_VIEWER_MEMBERSHIP_ID = UUID("34343434-3434-4343-8343-343434343434")
E2E_VIEWER_EMAIL = "e2e-viewer@example.com"
E2E_SALES_ID = UUID("abababab-abab-4bab-8bab-abababababab")
E2E_SALES_MEMBERSHIP_ID = UUID("acacacac-acac-4cac-8cac-acacacacacac")
E2E_SALES_EMAIL = "e2e-sales@example.com"
E2E_SALES_PASSWORD = "Local-Only-Sales-Password-42!"
E2E_CONTACT_ID = UUID("77777777-7777-4777-8777-777777777777")
E2E_LEAD_ID = UUID("88888888-8888-4888-8888-888888888888")

E2E_FOREIGN_COMPANY_ID = UUID("44444444-4444-4444-8444-444444444444")
E2E_FOREIGN_USER_ID = UUID("55555555-5555-4555-8555-555555555555")
E2E_FOREIGN_MEMBERSHIP_ID = UUID("45454545-4545-4454-8454-454545454545")
E2E_FOREIGN_CONTACT_ID = UUID("99999999-9999-4999-8999-999999999999")
E2E_FOREIGN_LEAD_ID = UUID("66666666-6666-4666-8666-666666666666")
E2E_PLATFORM_ADMIN_ID = UUID("aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa")
E2E_PLATFORM_ADMIN_EMAIL = "e2e-platform-admin@example.com"


def _required_password(name: str) -> str:
    value = os.getenv(name, "")
    if len(value) < 16:
        raise RuntimeError(f"{name} must be a synthetic value of at least 16 characters")
    return value


def seed() -> None:
    password = _required_password("E2E_PASSWORD")
    viewer_password = _required_password("E2E_VIEWER_PASSWORD")
    platform_password = _required_password("E2E_PLATFORM_ADMIN_PASSWORD")

    with SessionLocal.begin() as session:
        roles = seed_rbac(session)
        platform_role = session.scalar(
            select(PlatformRole).where(PlatformRole.code == "platform_super_admin")
        )
        if platform_role is None:
            raise RuntimeError("Run Alembic migrations before the E2E seed")
        platform_admin = session.get(User, E2E_PLATFORM_ADMIN_ID)
        if platform_admin is None:
            platform_admin = User(
                id=E2E_PLATFORM_ADMIN_ID,
                email=E2E_PLATFORM_ADMIN_EMAIL,
                display_name="E2E Platform Admin",
                status="active",
            )
            session.add(platform_admin)
        platform_admin.password_hash = hash_password(platform_password)
        platform_admin.status = "active"
        session.flush()
        assignment = session.get(
            PlatformUserRole,
            {
                "user_id": platform_admin.id,
                "platform_role_id": platform_role.id,
            },
        )
        if assignment is None:
            session.add(
                PlatformUserRole(
                    user_id=platform_admin.id,
                    platform_role_id=platform_role.id,
                )
            )
        company = session.get(Company, E2E_COMPANY_ID)
        if company is None:
            company = Company(id=E2E_COMPANY_ID, name="E2E Synthetic Tenant", status="active")
            session.add(company)
        company.status = "active"

        user = session.get(User, E2E_USER_ID)
        if user is None:
            user = User(id=E2E_USER_ID, email=E2E_EMAIL, display_name="E2E Owner", status="active")
            session.add(user)
        user.password_hash = hash_password(password)
        user.status = "active"
        session.flush()

        membership = session.scalar(
            select(Membership).where(
                Membership.company_id == company.id,
                Membership.user_id == user.id,
            )
        )
        if membership is None:
            membership = Membership(
                id=E2E_OWNER_MEMBERSHIP_ID,
                company_id=company.id,
                user_id=user.id,
                joined_at=datetime.now(UTC),
            )
            session.add(membership)
        membership.status = "active"
        membership.role_id = roles["owner"].id

        viewer = session.get(User, E2E_VIEWER_ID)
        if viewer is None:
            viewer = User(
                id=E2E_VIEWER_ID,
                email=E2E_VIEWER_EMAIL,
                display_name="E2E Viewer",
                status="active",
            )
            session.add(viewer)
        viewer.password_hash = hash_password(viewer_password)
        viewer.status = "active"
        session.flush()
        viewer_membership = session.scalar(
            select(Membership).where(
                Membership.company_id == company.id,
                Membership.user_id == viewer.id,
            )
        )
        if viewer_membership is None:
            viewer_membership = Membership(
                id=E2E_VIEWER_MEMBERSHIP_ID,
                company_id=company.id,
                user_id=viewer.id,
                joined_at=datetime.now(UTC),
            )
            session.add(viewer_membership)
        viewer_membership.status = "active"
        viewer_membership.role_id = roles["viewer"].id
        session.flush()

        sales = session.get(User, E2E_SALES_ID)
        if sales is None:
            sales = User(
                id=E2E_SALES_ID,
                email=E2E_SALES_EMAIL,
                display_name="E2E Sales",
                status="active",
            )
            session.add(sales)
        sales.password_hash = hash_password(E2E_SALES_PASSWORD)
        sales.status = "active"
        session.flush()
        sales_membership = session.scalar(
            select(Membership).where(
                Membership.company_id == company.id,
                Membership.user_id == sales.id,
            )
        )
        if sales_membership is None:
            sales_membership = Membership(
                id=E2E_SALES_MEMBERSHIP_ID,
                company_id=company.id,
                user_id=sales.id,
                joined_at=datetime.now(UTC),
            )
            session.add(sales_membership)
        sales_membership.status = "active"
        sales_membership.role_id = roles["sales"].id
        session.flush()

        contact = session.get(Contact, E2E_CONTACT_ID)
        if contact is None:
            contact = Contact(
                id=E2E_CONTACT_ID,
                company_id=company.id,
                first_name="Samira",
                last_name="Prospect E2E",
                email="samira.e2e@example.com",
                email_normalized="samira.e2e@example.com",
                organization_name="Atlas Test",
                created_by_membership_id=membership.id,
            )
            session.add(contact)
        lead = session.get(Lead, E2E_LEAD_ID)
        if lead is None:
            lead = Lead(
                id=E2E_LEAD_ID,
                company_id=company.id,
                contact_id=contact.id,
                title="Déploiement CRM E2E",
                score=55,
                priority="medium",
                status="new",
                created_by_membership_id=membership.id,
            )
            session.add(lead)

        foreign_company = session.get(Company, E2E_FOREIGN_COMPANY_ID)
        if foreign_company is None:
            foreign_company = Company(
                id=E2E_FOREIGN_COMPANY_ID,
                name="E2E Foreign Tenant",
                status="active",
            )
            session.add(foreign_company)
        foreign_user = session.get(User, E2E_FOREIGN_USER_ID)
        if foreign_user is None:
            foreign_user = User(
                id=E2E_FOREIGN_USER_ID,
                email="e2e-foreign@example.com",
                display_name="E2E Foreign User",
                status="active",
                password_hash=hash_password("Synthetic-Foreign-Password-42!"),
            )
            session.add(foreign_user)
        session.flush()
        foreign_membership = session.scalar(
            select(Membership).where(
                Membership.company_id == foreign_company.id,
                Membership.user_id == foreign_user.id,
            )
        )
        if foreign_membership is None:
            foreign_membership = Membership(
                id=E2E_FOREIGN_MEMBERSHIP_ID,
                company_id=foreign_company.id,
                user_id=foreign_user.id,
                joined_at=datetime.now(UTC),
            )
            session.add(foreign_membership)
        foreign_membership.status = "active"
        foreign_membership.role_id = roles["owner"].id
        session.flush()

        foreign_contact = session.get(Contact, E2E_FOREIGN_CONTACT_ID)
        if foreign_contact is None:
            foreign_contact = Contact(
                id=E2E_FOREIGN_CONTACT_ID,
                company_id=foreign_company.id,
                first_name="Foreign",
                last_name="Prospect",
                email="foreign-prospect@example.com",
                email_normalized="foreign-prospect@example.com",
                created_by_membership_id=foreign_membership.id,
            )
            session.add(foreign_contact)
        foreign_lead = session.get(Lead, E2E_FOREIGN_LEAD_ID)
        if foreign_lead is None:
            foreign_lead = Lead(
                id=E2E_FOREIGN_LEAD_ID,
                company_id=foreign_company.id,
                contact_id=foreign_contact.id,
                title="Foreign confidential opportunity",
                created_by_membership_id=foreign_membership.id,
            )
            session.add(foreign_lead)

    print(
        f"E2E seed ready for companies {E2E_COMPANY_ID} / "
        f"{E2E_FOREIGN_COMPANY_ID} and users {E2E_EMAIL}, "
        f"{E2E_SALES_EMAIL}, {E2E_VIEWER_EMAIL}."
    )


if __name__ == "__main__":
    seed()
