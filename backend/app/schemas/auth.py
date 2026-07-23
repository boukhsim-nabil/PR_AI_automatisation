from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: SecretStr
    company_id: UUID


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    company_id: UUID


class AuthContextResponse(BaseModel):
    user_id: UUID
    company_id: UUID
    membership_id: UUID
    role_id: UUID | None = None
    session_id: UUID | None = None


class CurrentUserInfo(BaseModel):
    id: UUID
    email: EmailStr
    display_name: str | None


class CurrentCompanyInfo(BaseModel):
    id: UUID
    name: str


class CurrentMembershipInfo(BaseModel):
    id: UUID
    status: str


class CurrentRoleInfo(BaseModel):
    id: UUID
    code: str
    name: str


class CurrentUserResponse(BaseModel):
    user: CurrentUserInfo
    company: CurrentCompanyInfo
    membership: CurrentMembershipInfo
    role: CurrentRoleInfo | None
    permissions: list[str]
