import asyncio

from app.config import settings
from app.services import email_service


def _ses(monkeypatch, **over):
    vals = {"email_provider": "ses", "aws_region": "ap-southeast-2", "aws_access_key_id": "AKIA",
            "aws_secret_access_key": "secret", "email_from": "AutoAccounting <noreply@autoaccounting.ph>"} | over
    for k, v in vals.items():
        monkeypatch.setattr(settings, k, v)


def test_ses_needs_keys_and_sender(monkeypatch):
    _ses(monkeypatch)
    assert email_service.ready()
    _ses(monkeypatch, aws_secret_access_key="")
    assert not email_service.ready()
    _ses(monkeypatch, email_from="")
    assert not email_service.ready()


def test_ses_send_goes_to_one_address_from_the_sender(monkeypatch):
    _ses(monkeypatch)
    sent = []

    class Fake:
        def send_email(self, **kw):
            sent.append(kw)

    monkeypatch.setattr(email_service, "_ses_client", lambda: Fake())
    asyncio.run(email_service.send("a@b.ph", "Hi", "Body"))
    assert sent[0]["Source"] == "AutoAccounting <noreply@autoaccounting.ph>"
    assert sent[0]["Destination"] == {"ToAddresses": ["a@b.ph"]}
    assert sent[0]["Message"]["Body"]["Text"]["Data"] == "Body"


def test_nothing_configured_refuses(monkeypatch):
    monkeypatch.setattr(settings, "email_provider", "")
    assert not email_service.ready()
