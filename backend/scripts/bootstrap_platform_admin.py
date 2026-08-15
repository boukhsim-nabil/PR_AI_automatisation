"""Create or grant the first platform super-administrator.

Usage:
    python -m scripts.bootstrap_platform_admin --email admin@example.com

The password is read securely from the terminal and is never accepted as a
command-line argument, preventing it from leaking into shell history.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.models import PlatformRole, PlatformUserRole, User
from app.services.platform import normalize_email


def _strong_password(password: str) -> bool:
    return (
        len(password) >= 14
        and bool(re.search(r"[A-Z]", password))
        and bool(re.search(r"[a-z]", password))
        and bool(re.search(r"\d", password))
        and bool(re.search(r"[^A-Za-z0-9]", password))
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a platform super-administrator")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    email = normalize_email(args.email)

    database_url = os.getenv("MIGRATION_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "MIGRATION_DATABASE_URL is required; never bootstrap with the runtime DATABASE_URL."
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    with Session(engine) as db, db.begin():
        role = db.scalar(select(PlatformRole).where(PlatformRole.code == "platform_super_admin"))
        if role is None:
            raise SystemExit("Run `alembic upgrade head` before bootstrapping the administrator.")

        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            password = getpass.getpass("New platform administrator password: ")
            confirmation = getpass.getpass("Confirm password: ")
            if password != confirmation:
                raise SystemExit("Passwords do not match.")
            if not _strong_password(password):
                raise SystemExit(
                    "Password must contain at least 14 characters, upper/lowercase, "
                    "a number and a symbol."
                )
            user = User(
                email=email,
                password_hash=hash_password(password),
                display_name="Platform Administrator",
                status="active",
            )
            db.add(user)
            db.flush()
        elif user.status != "active":
            raise SystemExit("The existing user is inactive; recover it before granting access.")

        assignment = db.get(
            PlatformUserRole,
            {"user_id": user.id, "platform_role_id": role.id},
        )
        if assignment is None:
            db.add(PlatformUserRole(user_id=user.id, platform_role_id=role.id))
            outcome = "granted"
        else:
            outcome = "already present"

    print(f"platform_super_admin {outcome} for {email}")


if __name__ == "__main__":
    main()
