import json

import pytest

from app.services.audit import AuditService

pytestmark = pytest.mark.unit


def test_audit_metadata_recursively_redacts_secrets() -> None:
    metadata = {
        "password": "NeverStoreThis!",
        "nested": {
            "access_token": "header.payload.signature",
            "authorization": "Bearer abc",
            "api-key": "private-api-key",
            "safe": "workflow-42",
        },
        "values": ["eyJhbGciOiJIUzI1NiJ9.payload.signature", "visible"],
    }

    sanitized = AuditService.sanitize_metadata(metadata)
    serialized = json.dumps(sanitized)

    assert "NeverStoreThis" not in serialized
    assert "private-api-key" not in serialized
    assert "Bearer abc" not in serialized
    assert "header.payload.signature" not in serialized
    assert sanitized["nested"]["safe"] == "workflow-42"
