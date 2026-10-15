from app.auth.security import upload_limiter


def test_accounting_uploads_use_their_own_rate_limiter():
    from app.routers.accounting import accounting_upload_limiter

    assert accounting_upload_limiter is not upload_limiter
