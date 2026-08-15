import pytest

from app.core.e2e import identify_e2e_database

pytestmark = pytest.mark.unit


def test_identifies_local_e2e_database() -> None:
    marker = identify_e2e_database(
        "postgresql+psycopg://automation_test:password@127.0.0.1:55432/automation_test"
    )
    assert marker == "automation_test"


def test_identifies_ci_e2e_database() -> None:
    marker = identify_e2e_database(
        "postgresql+psycopg://automation_e2e:password@127.0.0.1:5432/automation_e2e"
    )
    assert marker == "automation_e2e"


def test_refuses_development_database() -> None:
    marker = identify_e2e_database(
        "postgresql+psycopg://automation:password@127.0.0.1:5432/automation"
    )
    assert marker is None
