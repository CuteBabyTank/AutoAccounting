"""Password hashing and rules (OWASP / NIST SP 800-63B).

* Argon2id (argon2-cffi defaults: 3 passes, 64 MiB, 4 lanes, 16-byte salt), run off the event loop.
* Hashes carry their own parameters; ``needs_rehash`` upgrades old ones on the next sign-in.
* Rules: 10 to 128 characters, any characters (spaces and emoji welcome), no composition rules, not a commonly
  used password and not the person's own email. No periodic expiry.
* ``verify`` against a fixed dummy hash when the account doesn't exist, so timing doesn't reveal which emails
  have accounts.
"""

import asyncio
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 10
MAX_LENGTH = 128  # bounds hashing work per request

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("not-a-real-password-just-for-timing")

# The most common passwords (and the obvious variations people reach for to meet a length rule).
_COMMON = frozenset("""
password passw0rd password1 password12 password123 password1234 1234567890 0123456789 12345678910 qwertyuiop
qwerty1234 qwerty12345 1q2w3e4r5t 1qaz2wsx3edc abcdefghij abc1234567 iloveyou12 iloveyou123 letmein123
welcome123 welcome1234 admin12345 administrator changeme123 football123 baseball123 sunshine123 princess123
monkey1234 dragon1234 master1234 shadow1234 superman123 trustno1234 starwars123 passwordpassword 1111111111
0000000000 1234512345 9876543210 aaaaaaaaaa zxcvbnmasdf asdfghjkl1 asdfghjkl123 qwertyuiop123 p@ssw0rd123
autoaccounting accounting123 accountant123 bookkeeping1 philippines philippines123 pilipinas123 mahalkita123
""".split())


def normalize(password: str) -> str:
    """NFKC so the same password typed on different keyboards / OSes hashes the same."""
    return unicodedata.normalize("NFKC", password or "")


def problem(password: str, email: str = "") -> str | None:
    """Why this password can't be used, in words for the person; None when it's fine."""
    pw = normalize(password)
    if len(pw) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters. A short phrase is easy to remember and hard to guess."
    if len(pw) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    low = pw.lower()
    if low in _COMMON or len(set(low)) <= 2:
        return "That password is too common. Try a short phrase only you would know."
    local = (email or "").split("@")[0].lower()
    if local and len(local) >= 4 and (low == local or low.startswith(local) and len(low) - len(local) <= 4):
        return "Don't use your email address as your password."
    return None


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, normalize(password))


def _verify(stored: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored or _DUMMY_HASH, normalize(password)) and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


async def verify_password(stored: str | None, password: str) -> bool:
    """True when ``password`` matches ``stored``. With no stored hash, still does the work and returns False."""
    return await asyncio.to_thread(_verify, stored, password)


def needs_rehash(stored: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored)
    except InvalidHashError:
        return True
