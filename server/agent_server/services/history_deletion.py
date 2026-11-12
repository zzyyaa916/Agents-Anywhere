from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agent_server.core.history_deletion import (
    BUSY_SESSION_STATUSES,
    DeviceCleanupIncomplete,
    HistoryDeletionConflict,
)
from agent_server.services.repository_ports import HistoryDeletionRepository

if TYPE_CHECKING:
    from agent_server.infra.terminal_broker import TerminalBroker
    from agent_server.services.session_runtime_state_cache import (
        SessionRuntimeStateCache,
    )
    from agent_server.services.timeline_write_buffer import TimelineWriteBuffer


async def cleanup_deleted_history(
    store: HistoryDeletionRepository,
    timeline_buffer: TimelineWriteBuffer,
    runtime_state_cache: SessionRuntimeStateCache,
    audits: list[dict[str, Any]],
    terminals: TerminalBroker | None = None,
    manager: Any = None,
) -> None:
    for audit in audits:
        if audit.get("device_cleanup_json"):
            if manager is None:
                raise DeviceCleanupIncomplete("device cleanup requires an online Connector")
            plan = json.loads(audit["device_cleanup_json"])
            if not plan.get("deviceComplete"):
                result = await manager.request(plan["request"]["connectorId"], "history.cleanup.commit", plan, timeout=120)
                if result.get("complete") is not True:
                    raise DeviceCleanupIncomplete("device cleanup did not complete")
                plan["deviceComplete"] = True
                await store.mark_device_cleanup_complete(audit["id"], plan)
        for sid in audit["session_ids"]:
            await store.files.delete_session(sid)
            await timeline_buffer.discard_session(sid)
            await runtime_state_cache.discard(sid)
            if terminals is not None:
                for terminal in await terminals.get_for_session(sid):
                    await terminals.remove(terminal.id)
        if audit.get("device_cleanup_json"):
            result = await manager.request(plan["request"]["connectorId"], "history.cleanup.release", plan, timeout=10)
            if result.get("released") is not True:
                raise DeviceCleanupIncomplete("device cleanup receipt was not released")
        await store.finish_history_cleanup(audit["id"])


async def delete_history_data(
    object_id: str,
    *,
    user_id: str,
    project: bool,
    store: HistoryDeletionRepository,
    runtime_state_cache: SessionRuntimeStateCache,
    timeline_buffer: TimelineWriteBuffer,
    expected_count: int | None = None,
    terminals: TerminalBroker | None = None,
    manager: Any = None,
    delete_contents: bool = False,
) -> list[str]:
    try:
        connector_id, ids = await store.history_deletion_target(
            object_id, user_id=user_id, project=project
        )
    except KeyError:
        audits = await store.pending_history_cleanup(
            object_id=object_id, project=project, user_id=user_id
        )
        if not audits:
            raise
        if audits[0].get("device_cleanup_json"):
            connector_id = json.loads(audits[0]["device_cleanup_json"])["request"]["connectorId"]
            async with store.connector_lifecycle(connector_id):
                current = await store.pending_history_cleanup(object_id=object_id, project=project, user_id=user_id)
                await cleanup_deleted_history(store, timeline_buffer, runtime_state_cache, current, terminals, manager)
        else:
            await cleanup_deleted_history(store, timeline_buffer, runtime_state_cache, audits, terminals, manager)
        return [sid for audit in audits for sid in audit["session_ids"]]
    async with store.connector_lifecycle(connector_id):
        states = await runtime_state_cache.get_many(ids)
        busy = {
            sid
            for sid, state in states.items()
            if state.status in BUSY_SESSION_STATUSES
        }
        if busy:
            raise HistoryDeletionConflict(sorted(busy))
        if expected_count is not None and len(ids) != expected_count:
            raise HistoryDeletionConflict([], "deletion_count_changed")
        device_cleanup = None
        if delete_contents:
            if manager is None:
                raise DeviceCleanupIncomplete("device cleanup requires an online Connector")
            request = await store.history_device_cleanup_plan(object_id, user_id=user_id, project=project)
            request["operationId"] = uuid4().hex
            prepared = await manager.request(connector_id, "history.cleanup.prepare", request, timeout=30)
            if prepared.get("prepared") is not True:
                raise DeviceCleanupIncomplete("Connector cannot safely delete device contents")
            device_cleanup = {"request": request, "receipt": prepared["receipt"]}
        try:
            ids = await store.delete_history(
                object_id,
                user_id=user_id,
                project=project,
                expected_count=expected_count,
                cached_busy=busy,
                **({"device_cleanup": device_cleanup} if device_cleanup is not None else {}),
            )
        except HistoryDeletionConflict:
            if device_cleanup is not None:
                await manager.request(connector_id, "history.cleanup.cancel", device_cleanup, timeout=10)
            raise
        audits = await store.pending_history_cleanup(
            object_id=object_id, project=project, user_id=user_id
        )
        await cleanup_deleted_history(
            store, timeline_buffer, runtime_state_cache, audits, terminals, manager
        )
    return ids


async def abandon_device_cleanup(object_id, *, user_id, project, store, manager, timeline_buffer, runtime_state_cache, terminals=None):
    audits = await store.pending_history_cleanup(object_id=object_id, project=project, user_id=user_id)
    if not audits:
        raise KeyError(object_id)
    for audit in audits:
        if not audit.get("device_cleanup_json"):
            continue
        plan = json.loads(audit["device_cleanup_json"])
        connector_id = plan["request"]["connectorId"]
        async with store.connector_lifecycle(connector_id):
            # Re-read after acquiring the same lock used by deletion and recovery.
            pending = await store.pending_history_cleanup(object_id=object_id, project=project, user_id=user_id)
            current = next((row for row in pending if row["id"] == audit["id"]), None)
            if current is None or not current.get("device_cleanup_json"):
                continue
            result = await manager.request(connector_id, "history.cleanup.cancel", plan, timeout=120)
            if result.get("released") is not True:
                raise DeviceCleanupIncomplete("device did not cancel cleanup")
            await store.abandon_device_cleanup(audit["id"])
            current = {**current, "device_cleanup_json": None}
            await cleanup_deleted_history(store, timeline_buffer, runtime_state_cache, [current], terminals)
