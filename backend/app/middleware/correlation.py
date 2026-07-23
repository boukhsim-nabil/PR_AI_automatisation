from uuid import UUID, uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.audit import AuditService


class CorrelationAuditMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation_id = self._correlation_id(Headers(scope=scope).get("x-correlation-id"))
        scope.setdefault("state", {})["correlation_id"] = str(correlation_id)

        async def send_with_correlation(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("X-Correlation-ID", str(correlation_id))
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        finally:
            AuditService.flush(scope)

    @staticmethod
    def _correlation_id(value: str | None) -> UUID:
        try:
            return UUID(value) if value else uuid4()
        except ValueError:
            return uuid4()
