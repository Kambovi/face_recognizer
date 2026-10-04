"""Password policy + login throttling.

Policy: 10..72 characters, at least one letter and one digit, not the email,
not a well-known password. Throttling, two layers:
  * per user: 5 wrong passwords in a row -> locked for 15 minutes
    (users.failed_logins / locked_until, survives restarts, all workers);
  * per client IP: max 20 login attempts per 5 minutes (in memory, per
    worker) -- stops password spraying across many accounts.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

MIN_LEN = 10
MAX_LEN = 72  # bcrypt limit
MAX_FAILED = 5
LOCK_MINUTES = 15
IP_WINDOW_SECONDS = 300
IP_MAX_ATTEMPTS = 20

COMMON = {
    "changeme123!", "password123", "password@123", "admin@123", "admin12345", "qwerty12345",
    "1234567890", "welcome@123", "india@123", "abc@123456", "p@ssw0rd123", "letmein123",
}


def password_problem(password: str, email: str | None = None) -> str | None:
    """Return a human message if the password is not acceptable, else None."""
    if len(password) < MIN_LEN:
        return f"Password must be at least {MIN_LEN} characters"
    if len(password.encode()) > MAX_LEN:
        return f"Password must be at most {MAX_LEN} bytes"
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Password must contain letters and numbers"
    low = password.lower()
    if low in COMMON:
        return "This password is too common"
    if email and low == email.lower():
        return "Password must not be your email"
    if email and len(email.split("@")[0]) >= 4 and email.split("@")[0].lower() in low:
        return "Password must not contain your email name"
    return None


class IpThrottle:
    def __init__(self, window: int = IP_WINDOW_SECONDS, limit: int = IP_MAX_ATTEMPTS) -> None:
        self.window, self.limit = window, limit
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self._hits) > 50_000:  # memory guard
            self._hits.clear()
        return True

    def reset(self) -> None:
        self._hits.clear()


login_throttle = IpThrottle()
