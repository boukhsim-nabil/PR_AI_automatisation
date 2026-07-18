from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import create_app


def test_security_middleware_blocks_request_without_token() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/auth/context")

    assert response.status_code == 401
    assert response.json() == {"detail": "Bearer token required"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_security_middleware_derives_tenant_from_token() -> None:
    client = TestClient(create_app())
    user_id = uuid4()
    company_id = uuid4()
    membership_id = uuid4()
    token, _ = create_access_token(
        user_id=user_id,
        company_id=company_id,
        membership_id=membership_id,
        role_id=None,
    )

    response = client.get(
        "/v1/auth/context",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["company_id"] == str(company_id)


def test_security_middleware_blocks_cross_tenant_header() -> None:
    client = TestClient(create_app())
    token, _ = create_access_token(
        user_id=uuid4(),
        company_id=uuid4(),
        membership_id=uuid4(),
        role_id=None,
    )

    response = client.get(
        "/v1/auth/context",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Company-ID": str(uuid4()),
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-tenant access denied"}
