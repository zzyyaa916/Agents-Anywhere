import pytest

from agent_server.core.timeline import (
    TIMELINE_ORDER_SEQ_MAX as MAX,
    TIMELINE_ORDER_SEQ_MIN as MIN,
    allocate_timeline_order_seq,
    timeline_order_seq_in_range,
)


@pytest.mark.parametrize("requested", [MIN, -1, 0, 1, MAX])
def test_free_int32_positions_are_honored(requested):
    assert allocate_timeline_order_seq(requested, MAX, occupied=False) == requested


@pytest.mark.parametrize("requested", [MIN - 1, MAX + 1, True])
def test_out_of_range_positions_append(requested):
    assert allocate_timeline_order_seq(requested, 4, occupied=False) == 5
    assert not timeline_order_seq_in_range(requested)


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
