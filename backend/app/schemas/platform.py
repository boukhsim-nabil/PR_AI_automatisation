from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlatformLogin(StrictModel):
    email: EmailStr
    password: SecretStr


class PlatformToken(StrictModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CompanyCreate(StrictModel):
    name: str = Field(min_length=2, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    sector: str | None = Field(default=None, max_length=120)
    country: str = Field(default="MA", pattern=r"^[A-Z]{2}$")
    timezone: str = Field(default="Africa/Casablanca", min_length=3, max_length=64)
    language: str = Field(default="fr", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    currency: str = Field(default="MAD", pattern=r"^[A-Z]{3}$")
    plan_code: str = Field(default="trial", min_length=1, max_length=64)
    trial_days: int | None = Field(default=14, ge=0, le=365)
    owner_first_name: str = Field(min_length=1, max_length=120)
    owner_last_name: str = Field(min_length=1, max_length=120)
    owner_email: EmailStr


class CompanyUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    sector: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    timezone: str | None = Field(default=None, min_length=3, max_length=64)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    plan_code: str | None = Field(default=None, min_length=1, max_length=64)


class CompanyRead(StrictModel):
    id: UUID
    name: str
    legal_name: str | None
    slug: str
    sector: str | None
    country: str
    timezone: str
    language: str
    currency: str
    status: str
    onboarding_status: str
    plan_code: str
    trial_ends_at: datetime | None
    owner_email: EmailStr | None = None
    created_at: datetime
    suspended_at: datetime | None
    suspension_reason: str | None


class CompanyPage(StrictModel):
    items: list[CompanyRead]
    total: int
    page: int
    page_size: int
    pages: int


class InvitationRead(StrictModel):
    id: UUID
    company_id: UUID
    email: EmailStr
    status: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class CompanyProvisioned(StrictModel):
    company: CompanyRead
    invitation: InvitationRead


class InviteOwner(StrictModel):
    owner_email: EmailStr


class SuspendCompany(StrictModel):
    reason: str = Field(min_length=5, max_length=1000)


class InvitationValidation(StrictModel):
    valid: bool
    invitation_id: UUID | None = None
    company_name: str | None = None
    email: EmailStr | None = None
    expires_at: datetime | None = None
    existing_user: bool = False


class AcceptInvitation(StrictModel):
    token: str = Field(min_length=32, max_length=512)
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    password: SecretStr
    password_confirmation: SecretStr | None = None
    accept_terms: bool = False

    @model_validator(mode="after")
    def passwords_match(self) -> "AcceptInvitation":
        if self.password_confirmation is not None and (
            self.password.get_secret_value() != self.password_confirmation.get_secret_value()
        ):
            raise ValueError("password confirmation does not match")
        return self


class UsageSummary(StrictModel):
    company_id: UUID
    contacts: int = 0
    leads: int = 0
    tasks: int = 0
    sessions_active: int = 0


class AdminSummary(StrictModel):
    total_companies: int
    active_companies: int
    onboarding_companies: int
    suspended_companies: int
    pending_owner_invitations: int
    trials_expiring_soon: int
