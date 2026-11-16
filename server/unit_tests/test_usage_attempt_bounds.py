from datetime import UTC, datetime

from agent_server.core.account_usage import (
    MAX_CONNECTOR_RETRY_SECONDS,
    bounded_next_attempt_at,
    fetched_at_is_ahead,
)


def test_connector_retry_hint_is_bounded_by_server_maximum():
    now = 2_000_000_000.0
    assert bounded_next_attempt_at(now, now + 600, 60) == now + 600
    assert bounded_next_attempt_at(now, now + 10 * 86400, 60) == now + MAX_CONNECTOR_RETRY_SECONDS
    assert bounded_next_attempt_at(now, now - 1, 60) == now + 60


def test_fetched_at_ahead_uses_the_server_tolerance():
    now = 2_000_000_000.0
    assert not fetched_at_is_ahead(datetime.fromtimestamp(now + 30, UTC), now)
    assert fetched_at_is_ahead(datetime.fromtimestamp(now + 31, UTC), now)
    assert not fetched_at_is_ahead(None, now)
