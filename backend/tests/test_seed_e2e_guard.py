import pytest

from scripts.seed_e2e import _guard_e2e_database

pytestmark = pytest.mark.unit


def test_e2e_seed_accepts_only_known_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://automation_test:password@127.0.0.1:55432/automation_test",
    )
    _guard_e2e_database()


def test_e2e_seed_refuses_development_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://automation_test:password@127.0.0.1:55432/automation_test",
    )
    with pytest.raises(RuntimeError, match="APP_ENV"):
        _guard_e2e_database()


def test_e2e_seed_refuses_development_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://automation:password@127.0.0.1:5432/automation",
    )
    with pytest.raises(RuntimeError, match="Unsafe DATABASE_URL"):
        _guard_e2e_database()
