import os
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.tenant import (
    enforce_application_role,
    enforce_platform_role,
    set_current_company,
    set_current_platform_user,
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://automation:automation_dev_password@127.0.0.1:5432/automation",
)

engine_options: dict[str, object] = {"pool_pre_ping": True, "pool_recycle": 300}
if DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://")):
    engine_options["connect_args"] = {"connect_timeout": 5}

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    session = SessionLocal()
    try:
        with session.begin():
            platform_context = getattr(request.state, "platform_auth_context", None)
            platform_request = request.url.path.startswith(("/v1/platform", "/v1/invitations"))
            if platform_context is not None or platform_request:
                enforce_platform_role(session)
                if platform_context is not None:
                    set_current_platform_user(session, platform_context.user_id)
            else:
                enforce_application_role(session)
            auth_context = getattr(request.state, "auth_context", None)
            if auth_context is not None:
                set_current_company(session, auth_context.company_id)
            yield session
    finally:
        session.close()
