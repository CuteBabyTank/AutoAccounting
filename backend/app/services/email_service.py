"""Outgoing email (verification and password reset).

``EMAIL_PROVIDER``:
* ``""`` (default in production): no email is sent; ``ready()`` is False, so the login page hides "Create account"
  and "Forgot password" (an account whose email can't be confirmed must never reach a firm).
* ``console``: the message (with its link) is written to the log. Development only.

Add a real provider (Cloudflare Email, Resend, SMTP) as another branch of ``send`` when it's chosen.
"""

import logging

from app.config import settings

logger = logging.getLogger("email")


def ready() -> bool:
    provider = settings.email_provider.strip().lower()
    if provider == "console":
        return settings.environment == "development"
    return False


async def send(to: str, subject: str, text: str) -> None:
    """Send one plain-text email. Raises RuntimeError when no provider is configured."""
    provider = settings.email_provider.strip().lower()
    if provider == "console" and settings.environment == "development":
        # Dev only: the link is the whole point of the message, so it's logged in full.
        logger.info("email_console to=%s subject=%s\n%s", to, subject, text)
        return
    raise RuntimeError("Email sending is not configured")
