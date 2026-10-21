from datetime import date

from app.services.accounting.books.books_start import default_books_start


def test_first_quarter_with_documents():
    assert default_books_start(12, (2026, 3), date(2026, 10, 20)) == date(2026, 7, 1)


def test_fiscal_year_quarter_start():
    # June year end: fiscal 2026 runs Jul 2025 - Jun 2026, so its Q1 starts Jul 1, 2025
    assert default_books_start(6, (2026, 1), date(2026, 10, 20)) == date(2025, 7, 1)
    assert default_books_start(6, (2026, 3), date(2026, 10, 20)) == date(2026, 1, 1)


def test_no_documents_uses_current_fiscal_year():
    assert default_books_start(12, None, date(2026, 10, 20)) == date(2026, 1, 1)
    # Oct 20, 2026 with a June year end is in fiscal 2027, which starts Jul 1, 2026
    assert default_books_start(6, None, date(2026, 10, 20)) == date(2026, 7, 1)
