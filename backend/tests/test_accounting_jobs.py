from datetime import datetime, timedelta, timezone

from app.services.accounting.jobs import STALE_AFTER, is_stale_job

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def test_running_job_with_no_progress_is_stale():
    old = NOW - STALE_AFTER - timedelta(seconds=1)
    assert is_stale_job("extracting", old, NOW) is True
    assert is_stale_job("detecting", old, NOW) is True


def test_recent_or_finished_jobs_are_not_stale():
    assert is_stale_job("extracting", NOW - timedelta(minutes=1), NOW) is False
    long_ago = NOW - timedelta(days=3)
    for status in ("awaiting_confirmation", "done", "failed"):
        assert is_stale_job(status, long_ago, NOW) is False
