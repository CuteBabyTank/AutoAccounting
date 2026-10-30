"""Client IP and Cloudflare origin lock (app/edge.py)."""

from app.edge import client_ip, origin_allowed

SECRET = "s" * 40


def test_forged_forwarded_for_is_ignored():
    # Cloud Run appends the real caller last; the first entry is whatever the client sent.
    assert client_ip({"x-forwarded-for": "9.9.9.9, 203.0.113.7"}, "10.0.0.1", "") == "203.0.113.7"


def test_falls_back_to_peer():
    assert client_ip({}, "10.0.0.1", "") == "10.0.0.1"
    assert client_ip({}, None, "") == "unknown"


def test_cf_connecting_ip_needs_the_secret():
    headers = {"cf-connecting-ip": "198.51.100.4", "x-forwarded-for": "172.70.1.1"}
    assert client_ip(headers, None, SECRET) == "172.70.1.1"
    assert client_ip({**headers, "x-aa-origin": "wrong"}, None, SECRET) == "172.70.1.1"
    assert client_ip({**headers, "x-aa-origin": SECRET}, None, SECRET) == "198.51.100.4"
    # No secret configured: a client-sent CF-Connecting-IP is never believed.
    assert client_ip({**headers, "x-aa-origin": ""}, None, "") == "172.70.1.1"


def test_origin_lock():
    assert origin_allowed("/api/auth/me", {}, "")
    assert not origin_allowed("/api/auth/me", {}, SECRET)
    assert not origin_allowed("/api/auth/me", {"x-aa-origin": "nope"}, SECRET)
    assert origin_allowed("/api/auth/me", {"x-aa-origin": SECRET}, SECRET)
    assert origin_allowed("/api/health", {}, SECRET)
