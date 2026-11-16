import pytest

from agent_server.core.timeline import TIMELINE_ORDER_SEQ_MAX as MAX
from agent_server.core.timeline import TIMELINE_ORDER_SEQ_MIN as MIN
from agent_server.core.timeline import (
    TIMELINE_ORDER_SEQ_PLACEMENT_WINDOW as WINDOW,
)
from agent_server.core.timeline import (
    allocate_timeline_order_seq,
    append_timeline_order_seq,
    timeline_order_seq_in_range,
)


@pytest.mark.parametrize("requested", [MAX, MAX - 1, MAX - WINDOW])
def test_free_recent_positions_are_honored(requested):
    assert allocate_timeline_order_seq(requested, MAX, occupied=False) == requested


@pytest.mark.parametrize("requested", [MIN, -1, 0])
def test_free_old_positions_are_appended(requested):
    assert allocate_timeline_order_seq(requested, 1000, occupied=False) == 1001


def test_position_just_outside_the_window_appends():
    with pytest.raises(OverflowError):
        allocate_timeline_order_seq(MAX - WINDOW - 1, MAX, occupied=False)


@pytest.mark.parametrize("requested", [MIN - 1, MAX + 1, True])
def test_out_of_range_positions_append(requested):
    assert allocate_timeline_order_seq(requested, 4, occupied=False) == 5
    assert not timeline_order_seq_in_range(requested)


def test_initial_sync_may_use_its_own_numbering():
    assert allocate_timeline_order_seq(42, 0, occupied=False, initial_sync=True) == 42


def test_same_batch_claims_free_position_first_come_first_served():
    occupied = {2, 3, 4}
    maximum = 4
    positions = []
    for requested in [1, 1, 3]:
        result = allocate_timeline_order_seq(
            requested, maximum, occupied=requested in occupied
        )
        occupied.add(result)
        maximum = max(maximum, result)
        positions.append(result)
    assert positions == [1, 5, 6]
    assert len(occupied) == 6
    with pytest.raises(OverflowError):
        allocate_timeline_order_seq(1, MAX, occupied=True)


def test_server_authored_items_always_append():
    assert append_timeline_order_seq(0) == 1
    assert append_timeline_order_seq(7) == 8
    with pytest.raises(OverflowError):
        append_timeline_order_seq(MAX)
