from app.database import pooler_mode


def test_auto_detects_transaction_pooler_port():
    url = "postgresql+asyncpg://u.ref:pw@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
    assert pooler_mode(url, "auto") == "transaction"


def test_auto_is_none_for_session_port_and_unix_socket():
    assert pooler_mode("postgresql+asyncpg://u:pw@host:5432/db", "auto") == "none"
    cloudsql = "postgresql+asyncpg://postgres:pw@/postgres?host=/cloudsql/p:r:i"
    assert pooler_mode(cloudsql, "auto") == "none"


def test_explicit_setting_overrides_detection():
    assert pooler_mode("postgresql+asyncpg://u:pw@host:6543/db", "none") == "none"
    assert pooler_mode("postgresql+asyncpg://u:pw@host:5432/db", "transaction") == "transaction"


def test_ssl_context_modes():
    import ssl
    import certifi
    from app.database import ssl_context

    assert ssl_context("disable", "") is None
    unverified = ssl_context("require", "")
    assert unverified.verify_mode == ssl.CERT_NONE and not unverified.check_hostname
    verified = ssl_context("require", certifi.where())  # any CA bundle will do
    assert verified.verify_mode == ssl.CERT_REQUIRED and verified.check_hostname
