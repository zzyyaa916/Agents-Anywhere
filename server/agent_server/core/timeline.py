from __future__ import annotations

from dataclasses import dataclass

from agent_server.core.models import TimelineItem, TimelineItemIn

# ``timeline_items.order_seq`` is a PostgreSQL INTEGER. Widening it would
# rewrite the whole table, so every writer must stay inside this range.
TIMELINE_ORDER_SEQ_MIN = -(2**31)
TIMELINE_ORDER_SEQ_MAX = 2**31 - 1
# A late item may sit only this many positions behind the current durable head.
# A late echo drifts by a handful of items; anything tens of positions behind is
# a connector that restarted its projection at 1 and must be appended instead of
# being inserted into old history.  The window is this small so that rule holds
# for short sessions too, where a fixed large window swallowed every restart.
TIMELINE_ORDER_SEQ_PLACEMENT_WINDOW = 16


def timeline_order_seq_in_range(order_seq: int) -> bool:
    return isinstance(order_seq, int) and not isinstance(order_seq, bool) and TIMELINE_ORDER_SEQ_MIN <= order_seq <= TIMELINE_ORDER_SEQ_MAX


def allocate_timeline_order_seq(
    requested: int,
    maximum: int,
    *,
    occupied: bool,
    initial_sync: bool = False,
) -> int:
    """Place a self-reported orderSeq under the caller's session fence.

    A valid position the session does not occupy is stored as it is: an
    oversized or stale number must never drag a free position out of range.
    An initial sync may also use its own numbering for a free position.
    An incremental item keeps a late, smaller position only when it is still
    inside the recent placement window; outside it the renumbering is a
    connector restart and the item is appended.  A position the session
    already holds is never reused, even when ``occupied`` is reported late.
    """
    valid = timeline_order_seq_in_range(requested)
    # An initial sync (or a complete snapshot) reports the runtime's own
    # numbering, so any in-range position it does not need to reuse is stored
    # as it is -- including the negative bound.  The incremental path keeps
    # appending non-positive and stale positions.
    free = valid and not occupied and (
        initial_sync or requested >= 1
    )
    recent = initial_sync or (
        valid and requested >= maximum - TIMELINE_ORDER_SEQ_PLACEMENT_WINDOW
    )
    result = requested if free and recent else maximum + 1
    if not timeline_order_seq_in_range(result):
        raise OverflowError("timeline orderSeq exceeds the column range")
    return result


def append_timeline_order_seq(maximum: int) -> int:
    """Return the next append position for a server-authored item."""
    result = maximum + 1
    if not timeline_order_seq_in_range(result):
        raise OverflowError("timeline orderSeq exceeds the column range")
    return result


@dataclass(frozen=True, slots=True)
class TimelineItemWriteResult:
    item: TimelineItem
    changed: bool


@dataclass(frozen=True, slots=True)
class TimelineBatchWriteResult:
    items: tuple[TimelineItem, ...]
    changed: bool
    # Some items were stored at a different orderSeq than the pending value
    # clients already received, so their copies must be refetched.
    reordered: bool = False


def timeline_item_state_is_unchanged(
    existing: TimelineItem,
    incoming: TimelineItemIn,
) -> bool:
    """Compare the Runtime-owned state identity for one stable item ID."""

    return existing.contentHash == incoming.contentHash


def timeline_item_from_runtime_input(
    item: TimelineItemIn,
    *,
    updated_seq: int,
    now: str,
    existing: TimelineItem | None = None,
    order_seq: int | None = None,
    revision: int | None = None,
) -> TimelineItem:
    # ``dict(item)`` is a shallow field copy, so the (potentially large)
    # ``content`` payload is carried by reference.  ``model_dump()`` deep-copies
    # it, which made this normalization one of the most expensive steps of the
    # streaming hot path.
    data = dict(item)
    data["updatedSeq"] = updated_seq
    if order_seq is not None:
        data["orderSeq"] = order_seq
    if revision is not None:
        data["revision"] = revision
    data["createdAt"] = item.createdAt or (existing.createdAt if existing else now)
    data["updatedAt"] = item.updatedAt or now
    return TimelineItem.model_validate(data)


def latest_timeline_items_by_id(
    items: list[TimelineItemIn],
) -> dict[str, TimelineItemIn]:
    """Keep the last Runtime value when one batch repeats an item ID."""

    return {item.id: item for item in items}


def timeline_snapshot_is_unchanged(
    current_by_id: dict[str, TimelineItem],
    incoming_by_id: dict[str, TimelineItemIn],
) -> bool:
    if set(current_by_id) != set(incoming_by_id):
        return False
    return all(
        timeline_item_state_is_unchanged(current_by_id[item_id], incoming)
        and current_by_id[item_id].orderSeq == incoming.orderSeq
        for item_id, incoming in incoming_by_id.items()
    )


def timeline_item_from_snapshot(
    *,
    item: TimelineItemIn,
    existing: TimelineItem | None,
    updated_seq: int,
    now: str,
) -> TimelineItem:
    if (
        existing is not None
        and timeline_item_state_is_unchanged(existing, item)
        and existing.orderSeq == item.orderSeq
    ):
        return existing
    return timeline_item_from_runtime_input(
        item,
        updated_seq=updated_seq,
        now=now,
        existing=existing,
        revision=next_timeline_item_revision(item, existing),
    )


def next_timeline_item_revision(
    item: TimelineItemIn,
    existing: TimelineItem | None,
) -> int:
    if existing is None:
        return item.revision
    return max(item.revision, existing.revision + 1)
