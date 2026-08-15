import os

from sqlalchemy.engine import make_url

_E2E_DATABASES = {
    ("automation_test", "automation_test", "127.0.0.1", 55432): "automation_test",
    ("automation_test", "automation_test", "localhost", 55432): "automation_test",
    ("automation_e2e", "automation_e2e", "127.0.0.1", 5432): "automation_e2e",
    ("automation_e2e", "automation_e2e", "localhost", 5432): "automation_e2e",
}


def identify_e2e_database(raw_url: str) -> str | None:
    try:
        url = make_url(raw_url)
    except Exception:
        return None
    if not url.drivername.startswith("postgresql"):
        return None
    if url.database is None or url.username is None or url.host is None:
        return None
    identity = (url.database, url.username, url.host, url.port or 5432)
    return _E2E_DATABASES.get(identity)


def ensure_e2e_database(
    raw_url: str | None = None,
    environment: str | None = None,
) -> str:
    """Return the approved E2E database marker or fail before any database access."""
    effective_environment = (
        (environment if environment is not None else os.getenv("APP_ENV", "")).strip().lower()
    )
    if effective_environment not in {"test", "e2e"}:
        raise RuntimeError("E2E operations require APP_ENV=test or APP_ENV=e2e")

    effective_url = raw_url if raw_url is not None else os.getenv("DATABASE_URL", "")
    marker = identify_e2e_database(effective_url)
    if marker is None:
        raise RuntimeError(
            "Unsafe DATABASE_URL: E2E operations only accept the dedicated "
            "automation_test or automation_e2e PostgreSQL identity"
        )
    return marker
