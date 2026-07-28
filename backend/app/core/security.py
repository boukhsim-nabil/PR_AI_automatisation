from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("dummy-password-used-for-timing-safety")


def hash_password(plain_password: str) -> str:
    return password_hash.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    candidate_hash = hashed_password or DUMMY_PASSWORD_HASH
    try:
        return password_hash.verify(plain_password, candidate_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(
    *,
    user_id: UUID,
    company_id: UUID,
    membership_id: UUID,
    role_id: UUID | None,
    session_id: UUID | None = None,
) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "membership_id": str(membership_id),
        "type": "access",
        "jti": str(uuid4()),
        "iat": now,
        "nbf": now,
        "exp": now + expires_delta,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if role_id is not None:
        payload["role_id"] = str(role_id)
    if session_id is not None:
        payload["session_id"] = str(session_id)

    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    payload = _decode_token(token)
    if (
        payload.get("type") != "access"
        or not payload.get("company_id")
        or not payload.get("membership_id")
    ):
        raise ValueError("Invalid token type")
    return payload


def _decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": [
                    "sub",
                    "type",
                    "iat",
                    "nbf",
                    "exp",
                    "iss",
                    "aud",
                ]
            },
        )
    except InvalidTokenError as exc:
        raise ValueError("Invalid access token") from exc

    return payload


def create_platform_access_token(
    *, user_id: UUID, session_id: UUID, platform_role: str
) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_delta = timedelta(minutes=min(settings.jwt_access_token_expire_minutes, 10))
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "session_id": str(session_id),
        "platform_role": platform_role,
        "type": "platform_access",
        "jti": str(uuid4()),
        "iat": now,
        "nbf": now,
        "exp": now + expires_delta,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return (
        jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm),
        int(expires_delta.total_seconds()),
    )


def decode_platform_access_token(token: str) -> dict[str, Any]:
    payload = _decode_token(token)
    if (
        payload.get("type") != "platform_access"
        or payload.get("platform_role") != "platform_super_admin"
        or not payload.get("session_id")
    ):
        raise ValueError("Invalid platform token")
    return payload
