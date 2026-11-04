"""Password rules and hashing (services/passwords.py)."""

from app.services import passwords
from app.services.password_auth import _hash_token, normalize_email


def test_rules_follow_nist():
    assert passwords.problem("short") and "10 characters" in passwords.problem("short")
    assert passwords.problem("x" * 129)
    assert passwords.problem("password123") and "common" in passwords.problem("password123")
    assert passwords.problem("aaaaaaaaaaaa")                       # one repeated character
    assert passwords.problem("juan.delacruz", "juan.delacruz@firm.ph")  # the email itself
    assert passwords.problem("correct horse battery") is None     # a passphrase, no composition rules
    assert passwords.problem("mga resibo ko 2026 🙂") is None       # spaces and emoji are fine


async def test_hash_round_trip_uses_argon2id_and_normalizes():
    stored = await passwords.hash_password("Ｃorrect horse battery")  # full-width C
    assert stored.startswith("$argon2id$")
    assert await passwords.verify_password(stored, "Correct horse battery")  # NFKC: same password
    assert not await passwords.verify_password(stored, "correct horse batterY")
    assert not await passwords.verify_password(None, "anything at all")      # no account: still False
    assert not passwords.needs_rehash(stored)


def test_tokens_and_emails():
    assert len(_hash_token("abc")) == 64 and _hash_token("abc") != "abc"
    assert normalize_email("  Juan@Firm.PH ") == "juan@firm.ph"
