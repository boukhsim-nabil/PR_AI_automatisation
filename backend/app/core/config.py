from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Intelligent Automation API")
    jwt_secret_key: str = os.getenv(
        "JWT_SECRET_KEY", "local-development-secret-change-before-production"
    )
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_access_token_expire_minutes: int = int(
        os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15")
    )
    jwt_issuer: str = os.getenv("JWT_ISSUER", "automation-api")
    jwt_audience: str = os.getenv("JWT_AUDIENCE", "automation-frontend")


settings = Settings()
