from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from agent_server.core.session_quota import (
    limited_quota_windows,
    recheck_window_usable,
)

NOW = datetime(2033, 5, 18, 3, 0, tzinfo=UTC)


def window(*, remaining=0, reset="2033-05-18T04:00:00+00:00"):
    return {"kind": "five_hour", "remainingPercent": remaining, "resetsAt": reset}


def test_null_reset_is_not_a_consuming_deadline():
    values = [window(reset=None), window(remaining=20, reset=None), window()]
    assert limited_quota_windows(values, NOW) == [values[2]]


def test_invalid_reset_is_ignored_instead_of_raising():
    assert limited_quota_windows([window(reset="not-a-date")], NOW) == []
    assert limited_quota_windows([window(reset=42)], NOW) == []


def test_naive_reset_is_interpreted_as_utc():
    naive = (NOW + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    assert limited_quota_windows([window(reset=naive)], NOW) == [window(reset=naive)]


def test_recheck_rejects_a_null_reset_without_raising():
    received = NOW + timedelta(seconds=5)
    assert not recheck_window_usable(
        SimpleNamespace(received_at=received, resets_at=None),
        NOW,
        NOW,
    )


def test_recheck_requires_receipt_after_interrupt_and_future_reset():
    received = NOW + timedelta(seconds=5)
    usable = SimpleNamespace(received_at=received, resets_at=NOW + timedelta(hours=1))
    assert recheck_window_usable(usable, NOW, NOW)
    assert not recheck_window_usable(usable, received + timedelta(seconds=1), NOW)
    assert not recheck_window_usable(usable, NOW, NOW + timedelta(hours=2))
