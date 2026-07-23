from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

APPLICATION_DATABASE_ROLE = "automation_app"


def enforce_application_role(session: Session) -> None:
    """Lower a PostgreSQL transaction to the RLS-constrained application role."""
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(text(f"SET LOCAL ROLE {APPLICATION_DATABASE_ROLE}"))


def set_current_company(session: Session, company_id: UUID) -> None:
    """Set the tenant only for the lifetime of the current transaction."""
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(
        text("SELECT set_config('app.current_company_id', :company_id, true)"),
        {"company_id": str(company_id)},
    )
