"""Offline-reviewed repair tool. Default is read-only; --apply requires approval.

Run with the deployment's AGENT_SERVER_DB_URL / AGENT_SERVER_REDIS_URL and
AGENT_SERVER_REDIS_PREFIX. Do not pass database credentials on the command line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from agent_server.core.models import TimelineItem
from agent_server.core.timeline import TIMELINE_ORDER_SEQ_MAX as MAX
from agent_server.core.timeline import TIMELINE_ORDER_SEQ_MIN as MIN
from agent_server.infra.db import sessions, timeline_items
from agent_server.infra.redis_coordinator import RedisCoordinator
from agent_server.infra.repositories.facade import Store
from agent_server.infra.timeline_broker import TimelineBroker
from agent_server.services.timeline_write_buffer import TimelineWriteBuffer
from sqlalchemy import select, update


class RepairError(ValueError):
    """Only controlled non-sensitive failure categories."""


def plan(items):
    """Find a disjoint int32 interval for an overall offset, or fail closed."""
    if not items:
        return [], 0
    if len({row.orderSeq for row in items}) != len(items):
        raise RepairError("duplicate_existing_order_seq")

    def created(row):
        stamp = datetime.fromisoformat(row.createdAt)
        if stamp.tzinfo is None:
            raise RepairError("created_at_requires_timezone")
        return stamp

    ordered = sorted(items, key=lambda row: (created(row), row.orderSeq, row.id))
    if len(items) > MAX:
        raise RepairError("final_sequence_out_of_int32_range")
    low = min(row.orderSeq for row in items)
    high = max(row.orderSeq for row in items)
    if low < MIN or high > MAX:
        raise RepairError("existing_sequence_out_of_int32_range")
    width = high - low + 1
    # Exclude existing positions and all final positions. Using interval gaps
    # avoids assuming max+offset or a negative range will fit in INTEGER.
    blocked = sorted(
        [(row.orderSeq, row.orderSeq) for row in items] + [(1, len(items))]
    )
    start = MIN
    temporary_start = None
    for left, right in blocked + [(MAX + 1, MAX + 1)]:
        if left - start >= width:
            temporary_start = start
            break
        start = max(start, right + 1)
    if temporary_start is None:
        raise RepairError("no_safe_int32_temporary_space")
    offset = temporary_start - low
    result = [
        (row, row.orderSeq + offset, index) for index, row in enumerate(ordered, 1)
    ]
    if any(not MIN <= temporary <= MAX for _, temporary, _ in result):
        raise RepairError("temporary_sequence_out_of_int32_range")
    return result, offset


def backup_rows(destination, session_id, rows):
    # Exclusive, restrictive backup; a failed backup always precedes writes.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(
            {"session_id": session_id, "timeline_items": [dict(row) for row in rows]},
            stream,
            ensure_ascii=False,
        )
        stream.flush()
        os.fsync(stream.fileno())


async def run(args):
    redis_url = os.environ.get("AGENT_SERVER_REDIS_URL")
    if args.apply and not redis_url:
        # A process-local mutex cannot fence a running server's buffer. Refuse
        # rather than pretending that the DB lock also blocks live acceptance.
        raise RepairError("apply_requires_shared_server_redis_fence")
    store = Store()
    coordinator = RedisCoordinator(
        redis_url, prefix=os.environ.get("AGENT_SERVER_REDIS_PREFIX", "agents-anywhere")
    )
    buffer = None
    try:

        async def inspect_and_rewrite(conn):
            rows = (
                (
                    await conn.execute(
                        select(timeline_items).where(
                            timeline_items.c.session_id == args.session_id
                        )
                    )
                )
                .mappings()
                .all()
            )
            exists = (
                await conn.execute(
                    select(sessions.c.id).where(sessions.c.id == args.session_id)
                )
            ).first()
            if exists is None:
                raise RepairError("session_not_found")
            items = [
                TimelineItem.model_validate_json(row["payload_json"]) for row in rows
            ]
            changes, offset = plan(items)
            if not args.apply:
                # No content, IDs or database URLs in dry-run output.
                return {
                    "dry_run": True,
                    "count": len(changes),
                    "offset": offset,
                    "old_order_seq": [row.orderSeq for row, _, _ in changes],
                    "temporary_order_seq": [temporary for _, temporary, _ in changes],
                    "new_order_seq": [final for _, _, final in changes],
                }
            backup_rows(args.backup, args.session_id, rows)
            if not changes:
                return {"status": "unchanged", "count": 0}
            revision = await store._bump_session(conn, args.session_id)
            for row, temporary, _ in changes:
                await conn.execute(
                    update(timeline_items)
                    .where(
                        timeline_items.c.session_id == args.session_id,
                        timeline_items.c.id == row.id,
                    )
                    .values(order_seq=temporary)
                )
            rewritten = [
                row.model_copy(
                    update={
                        "orderSeq": final,
                        "updatedSeq": revision,
                        "revision": row.revision + 1,
                    }
                )
                for row, _, final in changes
            ]
            await store.timeline.upsert_many(conn, rewritten)
            await conn.execute(
                update(sessions)
                .where(sessions.c.id == args.session_id)
                .values(timeline_reset_seq=revision)
            )
            return {"status": "rewritten", "count": len(changes)}

        if args.apply:
            # This is exactly the live buffer's Redis session-revision fence;
            # it drains accepted pending rows before taking the DB advisory lock.
            buffer = TimelineWriteBuffer(
                store, TimelineBroker(coordinator), coordinator
            )
            async with (
                buffer.session_fence(args.session_id),
                store._timeline_transaction(args.session_id) as conn,
            ):
                report = await inspect_and_rewrite(conn)
        else:
            # Dry-run performs SELECT only and never creates a Redis projection.
            async with store.engine.connect() as conn:
                report = await inspect_and_rewrite(conn)
        print(json.dumps(report))
    finally:
        if buffer is not None:
            await buffer.close()
        await coordinator.close()
        await store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_id")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.apply and args.backup is None:
        parser.error("--apply requires --backup")
    try:
        asyncio.run(run(args))
    except RepairError as error:
        print(json.dumps({"status": "stopped", "reason": str(error)}))
        raise SystemExit(1) from None
    except Exception:  # noqa: BLE001 -- DB URLs and timeline content must never be printed.
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "reason": "repair_failed_check_configuration_backup_and_int32_space",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
