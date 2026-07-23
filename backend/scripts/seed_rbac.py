from app.db.seeds import seed_rbac
from app.db.session import SessionLocal


def seed() -> None:
    with SessionLocal.begin() as session:
        roles = seed_rbac(session)
    print(f"RBAC seed completed: {len(roles)} system roles synchronized.")


if __name__ == "__main__":
    seed()
