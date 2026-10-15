"""Sliding-window rate limiter. Used for login/upload/per-user gates."""

import time

from app.auth.security import RateLimiter


def test_allows_under_limit():
    rl = RateLimiter(max_attempts=3, window_seconds=60)
    assert rl.check_and_record("user1") is True
    assert rl.check_and_record("user1") is True
    assert rl.check_and_record("user1") is True


def test_blocks_at_limit():
    rl = RateLimiter(max_attempts=2, window_seconds=60)
    rl.check_and_record("user1")
    rl.check_and_record("user1")
    assert rl.check_and_record("user1") is False
    assert rl.is_rate_limited("user1") is True


def test_keys_isolated():
    rl = RateLimiter(max_attempts=1, window_seconds=60)
    assert rl.check_and_record("a") is True
    assert rl.check_and_record("a") is False
    # Different key still allowed
    assert rl.check_and_record("b") is True


def test_remaining_count():
    rl = RateLimiter(max_attempts=5, window_seconds=60)
    rl.check_and_record("user1")
    rl.check_and_record("user1")
    assert rl.remaining("user1") == 3


def test_window_expiry():
    rl = RateLimiter(max_attempts=1, window_seconds=1)
    assert rl.check_and_record("u") is True
    assert rl.check_and_record("u") is False
    time.sleep(1.1)
    # After window passes, allowed again
    assert rl.check_and_record("u") is True
