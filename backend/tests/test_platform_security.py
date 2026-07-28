import pytest

from app.core.rate_limit import LoginAttemptLimiter

pytestmark = pytest.mark.unit


def test_platform_login_limiter_blocks_and_resets() -> None:
    limiter = LoginAttemptLimiter(max_failures=2, window_seconds=60)
    key = "127.0.0.1|synthetic@example.com"
    assert limiter.retry_after(key) is None
    limiter.record_failure(key)
    limiter.record_failure(key)
    assert limiter.retry_after(key) is not None
    limiter.reset(key)
    assert limiter.retry_after(key) is None
