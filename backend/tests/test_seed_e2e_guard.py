import pytest

from app.core.e2e import ensure_e2e_database

pytestmark = pytest.mark.unit


def test_e2e_seed_accepts_only_known_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://automation_test:password@127.0.0.1:55432/automation_test",
    )
    assert ensure_e2e_database() == "automation_test"


def test_e2e_seed_refuses_development_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://automation_test:password@127.0.0.1:55432/automation_test",
    )
    with pytest.raises(RuntimeError, match="APP_ENV"):
        ensure_e2e_database()


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://automation:password@127.0.0.1:5432/automation",
        "postgresql+psycopg://automation_test:password@127.0.0.1:5432/automation_test",
        "postgresql+psycopg://wrong_user:password@127.0.0.1:55432/automation_test",
        "sqlite+pysqlite:///:memory:",
        "not-a-database-url",
        "",
    ],
)
def test_e2e_seed_refuses_unsafe_database_identity(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    with pytest.raises(RuntimeError, match="Unsafe DATABASE_URL"):
        ensure_e2e_database()
