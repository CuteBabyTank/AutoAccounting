"""Security utilities: rate limiting."""

import time
from collections import defaultdict
from threading import Lock

from app.auth.jwt import verify_token


def should_limit_ip(path: str, authorization: str) -> bool:
    """Only verified access tokens on protected routes can use the per-user bucket."""
    protected = ("/api/accounting", "/api/admin", "/api/team", "/api/features")
    if not any(path == prefix or path.startswith(prefix + "/") for prefix in protected):
        return True
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return True
    payload = verify_token(token)
    return payload is None or payload.get("scope") is not None


_EVICTION_INTERVAL = 300  # evict stale keys every 5 minutes
_MAX_TRACKED_KEYS = 50_000  # hard cap to prevent unbounded memory growth


class RateLimiter:
    """Thread-safe sliding-window rate limiter with automatic key eviction."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._last_eviction = time.monotonic()

    def _evict_stale(self, now: float) -> None:
        if now - self._last_eviction < _EVICTION_INTERVAL:
            return
        self._last_eviction = now
        cutoff = now - self._window
        stale = [k for k, v in self._attempts.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._attempts[k]
        if len(self._attempts) > _MAX_TRACKED_KEYS:
            sorted_keys = sorted(self._attempts.keys(), key=lambda k: self._attempts[k][-1] if self._attempts[k] else 0)
            for k in sorted_keys[:len(self._attempts) - _MAX_TRACKED_KEYS]:
                del self._attempts[k]

    def is_rate_limited(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._evict_stale(now)
            cutoff = now - self._window
            self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]
            return len(self._attempts[key]) >= self._max

    def check_and_record(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._evict_stale(now)
            cutoff = now - self._window
            self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]
            if len(self._attempts[key]) >= self._max:
                return False
            self._attempts[key].append(now)
            return True

    def record(self, key: str) -> None:
        with self._lock:
            self._attempts[key].append(time.monotonic())

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self._window
            recent = [t for t in self._attempts[key] if t > cutoff]
            return max(0, self._max - len(recent))


# Sign-in: per IP, 20 attempts per 5 minutes. Enough for a whole office behind one NAT signing in at once;
# Google verifies the credential, so this only slows token replay and floods of the user-creating path.
login_limiter = RateLimiter(max_attempts=20, window_seconds=300)

# Expensive ops: file upload, 20 batches per 10 minutes per user
upload_limiter = RateLimiter(max_attempts=20, window_seconds=600)

# Expensive ops: export/download, 30 per 10 minutes per user
export_limiter = RateLimiter(max_attempts=30, window_seconds=600)

# Chat send: 60 messages per minute per user. Caps the data a single account
# can flood into the messages table without throttling normal-volume chat.
chat_limiter = RateLimiter(max_attempts=60, window_seconds=60)

# Global: per-IP across all *unauthenticated* endpoints, 200 requests per minute.
# Applied in main.py unless a protected route has a verified access token,
# so users sharing one egress IP (corp NAT, CGNAT) don't compete for a bucket.
global_ip_limiter = RateLimiter(max_attempts=200, window_seconds=60)

# Authenticated: per-user across all endpoints, 300 requests per minute.
# Headroom for power users running several batches concurrently: each batch
# polls /status every 2s (~30 req/min), and a user may also be exporting,
# editing, and viewing files in parallel. 120 was tight; 300 leaves room
# without sacrificing abuse protection (single user can't realistically
# generate 5 req/s of legitimate traffic).
global_user_limiter = RateLimiter(max_attempts=300, window_seconds=60)
