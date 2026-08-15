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
