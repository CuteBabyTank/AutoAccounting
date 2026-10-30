"""Who is really calling: the client IP and whether the request came through Cloudflare.

Cloud Run's front end appends the caller's address to ``X-Forwarded-For``; anything before it was sent by the
client and can be forged, so only the last entry is trusted. Behind Cloudflare that last entry is a Cloudflare
edge, and the visitor is in ``CF-Connecting-IP``, which is only believed when the request also carries the origin
secret (a header Cloudflare adds with a Transform Rule). With ``ORIGIN_SECRET`` set, a request without it never
came through Cloudflare (someone calling the run.app URL directly) and is refused.
"""

import hmac
from collections.abc import Mapping

ORIGIN_HEADER = "x-aa-origin"
# Cloud Run startup probes and the frontend's warm-up ping reach the service without passing Cloudflare.
ORIGIN_EXEMPT_PATHS = frozenset({"/api/health"})


def from_edge(headers: Mapping[str, str], secret: str) -> bool:
    """True when the request carries the origin secret (constant-time compare)."""
    if not secret:
        return False
    sent = headers.get(ORIGIN_HEADER, "")
    return bool(sent) and hmac.compare_digest(sent.encode(), secret.encode())


def origin_allowed(path: str, headers: Mapping[str, str], secret: str) -> bool:
    """No secret configured = no lock. Otherwise only Cloudflare (or an exempt path) gets in."""
    return not secret or path in ORIGIN_EXEMPT_PATHS or from_edge(headers, secret)


def client_ip(headers: Mapping[str, str], peer: str | None, secret: str) -> str:
    if from_edge(headers, secret):
        cf = headers.get("cf-connecting-ip", "").strip()
        if cf:
            return cf
    forwarded = [part.strip() for part in headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if forwarded:
        return forwarded[-1]
    return peer or "unknown"
