from __future__ import annotations

import threading
import time


class LoginAttemptLimiter:
    """Small per-process guard; production multi-instance deployments use Redis."""

    def __init__(self, *, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int | None:
        now = time.monotonic()
        with self._lock:
            recent = [
                occurred
                for occurred in self._failures.get(key, [])
                if now - occurred < self.window_seconds
            ]
            if recent:
                self._failures[key] = recent
            else:
                self._failures.pop(key, None)
            if len(recent) < self.max_failures:
                return None
            return max(1, int(self.window_seconds - (now - recent[0])))

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            recent = [
                occurred
                for occurred in self._failures.get(key, [])
                if now - occurred < self.window_seconds
            ]
            recent.append(now)
            self._failures[key] = recent[-self.max_failures :]

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


platform_login_limiter = LoginAttemptLimiter()
