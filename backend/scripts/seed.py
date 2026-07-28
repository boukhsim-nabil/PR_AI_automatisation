import os
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import Company, Membership, User
from app.db.seeds import seed_rbac
from app.db.session import SessionLocal

COMPANY_NAME = "Acme Corp"
USER_EMAIL = os.getenv("SEED_USER_EMAIL", "admin@acme.com").strip().lower()


def seed_password() -> str:
    password = os.getenv("SEED_USER_PASSWORD", "")
    if len(password) < 12:
        raise RuntimeError("SEED_USER_PASSWORD must be set and contain at least 12 characters")
    return password


def seed() -> None:
    password = seed_password()
    with SessionLocal.begin() as session:
        roles = seed_rbac(session)
        company = session.scalar(select(Company).where(Company.name == COMPANY_NAME))
        if company is None:
            company = Company(
                name=COMPANY_NAME,
                sector="Technology",
                timezone="Africa/Casablanca",
                language="fr",
                status="active",
            )
            session.add(company)
            session.flush()
        else:
            company.status = "active"

        user = session.scalar(select(User).where(User.email == USER_EMAIL))
        if user is None:
            user = User(
                email=USER_EMAIL,
                display_name="Acme Admin",
                status="active",
            )
            session.add(user)
            session.flush()

        user.password_hash = hash_password(password)
        user.status = "active"

        membership = session.scalar(
            select(Membership).where(
                Membership.company_id == company.id,
                Membership.user_id == user.id,
            )
        )
        if membership is None:
            membership = Membership(
                company_id=company.id,
                user_id=user.id,
                status="active",
                joined_at=datetime.now(UTC),
            )
            session.add(membership)
        else:
            membership.status = "active"
            membership.joined_at = membership.joined_at or datetime.now(UTC)
        membership.role_id = roles["owner"].id

    print("Seed completed.")
    print(f"Company: {COMPANY_NAME}")
    print(f"Email: {USER_EMAIL}")


if __name__ == "__main__":
    seed()
