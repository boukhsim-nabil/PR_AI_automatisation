from sqlalchemy import select

from app.db.models import User
from app.db.session import SessionLocal

OLD_EMAIL = "admin@acme.test"
NEW_EMAIL = "admin@acme.com"


def update_seed_email() -> None:
    with SessionLocal.begin() as session:
        user = session.scalar(select(User).where(User.email == OLD_EMAIL))
        if user is None:
            user = session.scalar(select(User).where(User.email == NEW_EMAIL))
            if user is None:
                raise RuntimeError(f"User {OLD_EMAIL} not found")
            print(f"Email already updated: {user.email}")
            return

        duplicate = session.scalar(select(User).where(User.email == NEW_EMAIL))
        if duplicate is not None and duplicate.id != user.id:
            raise RuntimeError(f"Another user already uses {NEW_EMAIL}")

        user.email = NEW_EMAIL
        print(f"Email updated: {NEW_EMAIL}")


if __name__ == "__main__":
    update_seed_email()
