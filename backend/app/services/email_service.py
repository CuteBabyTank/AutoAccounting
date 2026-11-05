"""Outgoing email (verification and password reset).

``EMAIL_PROVIDER``:
* ``""`` (default in production): no email is sent; ``ready()`` is False, so the login page hides "Create account"
  and "Forgot password" (an account whose email can't be confirmed must never reach a firm).
* ``console``: the message (with its link) is written to the log. Development only.
* ``ses``: Amazon SES (``AWS_REGION``, ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``). ``EMAIL_FROM``'s domain must
  be a verified identity in that region, and the key needs ``ses:SendEmail``.
"""

import asyncio
import logging
from email.utils import parseaddr

from app.config import settings

logger = logging.getLogger("email")


def ready() -> bool:
    provider = settings.email_provider.strip().lower()
    if provider == "console":
        return settings.environment == "development"
    if provider == "ses":
        return bool(settings.aws_region and settings.aws_access_key_id and settings.aws_secret_access_key
                    and parseaddr(settings.email_from)[1])
    return False


_ses = None


def _ses_client():
    global _ses
    if _ses is None:
        import boto3  # only needed when SES is the provider

        _ses = boto3.client("ses", region_name=settings.aws_region, aws_access_key_id=settings.aws_access_key_id,
                            aws_secret_access_key=settings.aws_secret_access_key)
    return _ses


class EmailSendError(RuntimeError):
    """A send failed. Carries only the provider's error code: SES messages can contain the recipient's address."""


def _send_ses(to: str, subject: str, text: str) -> None:
    try:
        _send_ses_raw(to, subject, text)
    except Exception as exc:  # botocore ClientError, connection errors
        code = getattr(exc, "response", {}).get("Error", {}).get("Code") if hasattr(exc, "response") else None
        raise EmailSendError(f"ses_send_failed code={code or type(exc).__name__}") from None


def _send_ses_raw(to: str, subject: str, text: str) -> None:
    _ses_client().send_email(
        Source=settings.email_from,
        Destination={"ToAddresses": [to]},
        Message={"Subject": {"Data": subject, "Charset": "UTF-8"},
                 "Body": {"Text": {"Data": text, "Charset": "UTF-8"}}},
    )


async def send(to: str, subject: str, text: str) -> None:
    """Send one plain-text email. Raises RuntimeError when no provider is configured."""
    provider = settings.email_provider.strip().lower()
    if provider == "console" and settings.environment == "development":
        # Dev only: the link is the whole point of the message, so it's logged in full.
        logger.info("email_console to=%s subject=%s\n%s", to, subject, text)
        return
    if provider == "ses" and ready():
        await asyncio.to_thread(_send_ses, to, subject, text)  # boto3 blocks; keep the event loop free
        logger.info("email_sent provider=ses subject=%s", subject)  # no address or link in the log
        return
    raise RuntimeError("Email sending is not configured")
