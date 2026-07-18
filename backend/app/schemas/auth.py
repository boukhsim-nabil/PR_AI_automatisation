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
