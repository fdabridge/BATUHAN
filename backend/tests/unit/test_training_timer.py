from datetime import datetime, timedelta

from trainings.timer import remaining_exam_seconds, utc_iso


def test_utc_iso_marks_naive_database_time_as_utc():
    assert utc_iso(datetime(2026, 7, 29, 8, 30)) == "2026-07-29T08:30:00Z"


def test_remaining_exam_seconds_preserves_full_configured_duration():
    now = datetime(2026, 7, 29, 8, 0)
    assert remaining_exam_seconds(now + timedelta(minutes=30), now) == 1800


def test_remaining_exam_seconds_rounds_up_and_never_goes_negative():
    now = datetime(2026, 7, 29, 8, 0)
    assert remaining_exam_seconds(now + timedelta(milliseconds=100), now) == 1
    assert remaining_exam_seconds(now - timedelta(seconds=1), now) == 0
    assert remaining_exam_seconds(None, now) is None
