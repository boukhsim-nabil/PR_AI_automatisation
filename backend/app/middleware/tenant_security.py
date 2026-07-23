from dataclasses import dataclass
from typing import Any
from uuid import UUID

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.security import decode_access_token
from app.services.audit import AuditEvent, AuditService

PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/v1/auth/login",
        "/v1/auth/refresh",
        "/v1/auth/logout",
        "/v1/auth/logout-all",
    }
)


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: UUID
    company_id: UUID
    membership_id: UUID
    role_id: UUID | None = None
    session_id: UUID | None = None


class TenantSecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if method == "OPTIONS" or path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        authorization = headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            await self._reject(
                scope,
                receive,
                send,
                status_code=401,
                detail="Bearer token required",
                authenticate=True,
            )
            return

        try:
            claims = decode_access_token(token)
            auth_context = self._build_auth_context(claims)
        except (AttributeError, KeyError, TypeError, ValueError):
            await self._reject(
                scope,
                receive,
                send,
                status_code=401,
                detail="Invalid or expired access token",
                authenticate=True,
            )
            return

        requested_company_id = headers.get("x-company-id")
        if requested_company_id is not None:
            try:
                company_matches = UUID(requested_company_id) == auth_context.company_id
            except ValueError:
                company_matches = False
            if not company_matches:
                AuditService.record(
                    scope,
                    AuditEvent(
                        company_id=auth_context.company_id,
                        actor_user_id=auth_context.user_id,
                        actor_membership_id=auth_context.membership_id,
                        action="security.cross_tenant",
                        result="denied",
                        metadata={"requested_company_id": requested_company_id},
                    ),
                )
                await self._reject(
                    scope,
                    receive,
                    send,
                    status_code=403,
                    detail="Cross-tenant access denied",
                )
                return

        state = scope.setdefault("state", {})
        state["auth_context"] = auth_context
        state["user_id"] = auth_context.user_id
        state["company_id"] = auth_context.company_id
        state["membership_id"] = auth_context.membership_id

        await self.app(scope, receive, send)

    @staticmethod
    def _build_auth_context(claims: dict[str, Any]) -> AuthContext:
        role_id = claims.get("role_id")
        session_id = claims.get("session_id")
        return AuthContext(
            user_id=UUID(claims["sub"]),
            company_id=UUID(claims["company_id"]),
            membership_id=UUID(claims["membership_id"]),
            role_id=UUID(role_id) if role_id else None,
            session_id=UUID(session_id) if session_id else None,
        )

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        detail: str,
        authenticate: bool = False,
    ) -> None:
        headers = {"WWW-Authenticate": "Bearer"} if authenticate else None
        response = JSONResponse(
            status_code=status_code,
            content={"detail": detail},
            headers=headers,
        )
        await response(scope, receive, send)
