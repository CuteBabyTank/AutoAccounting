from datetime import datetime, timedelta, timezone

from app.services.accounting.jobs import RESUME_WITHIN, STALE_AFTER, is_stale_job, stale_action

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


def test_dead_jobs_resume_while_young_then_fail():
    stale = NOW - STALE_AFTER - timedelta(seconds=1)
    assert stale_action("extracting", NOW - timedelta(hours=1), stale, NOW) == "resume"
    assert stale_action("detecting", NOW - RESUME_WITHIN, stale, NOW) == "resume"
    assert stale_action("extracting", NOW - RESUME_WITHIN - timedelta(seconds=1), stale, NOW) == "fail"


def test_live_or_finished_jobs_need_nothing():
    assert stale_action("extracting", NOW - timedelta(hours=1), NOW - timedelta(minutes=1), NOW) is None
    assert stale_action("done", NOW - timedelta(days=3), NOW - timedelta(days=3), NOW) is None
