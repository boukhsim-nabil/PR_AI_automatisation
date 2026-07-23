import os
import secrets
from dataclasses import dataclass


def _jwt_secret_key() -> str:
    environment = os.getenv("APP_ENV", "development").strip().lower()
    configured_secret = os.getenv("JWT_SECRET_KEY", "")

    if configured_secret:
        if len(configured_secret) < 32:
            raise RuntimeError("JWT_SECRET_KEY must contain at least 32 characters")
        return configured_secret

    if environment in {"production", "staging"}:
        raise RuntimeError("JWT_SECRET_KEY is required outside development")

    # A random per-process key keeps local development fail-safe without
    # shipping a forgeable, repository-wide default secret.
    return secrets.token_urlsafe(48)


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Intelligent Automation API")
    environment: str = os.getenv("APP_ENV", "development")
    jwt_secret_key: str = _jwt_secret_key()
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_access_token_expire_minutes: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    refresh_token_expire_days: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
    jwt_issuer: str = os.getenv("JWT_ISSUER", "automation-api")
    jwt_audience: str = os.getenv("JWT_AUDIENCE", "automation-frontend")
    refresh_cookie_name: str = os.getenv("REFRESH_COOKIE_NAME", "automation_refresh_token")
    csrf_cookie_name: str = os.getenv("CSRF_COOKIE_NAME", "automation_csrf_token")


settings = Settings()
