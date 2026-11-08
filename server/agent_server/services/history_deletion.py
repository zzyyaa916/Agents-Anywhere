from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_server.core.history_deletion import BUSY_SESSION_STATUSES
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
) -> None:
    for audit in audits:
        for sid in audit["session_ids"]:
            await store.files.delete_session(sid)
            await timeline_buffer.discard_session(sid)
            await runtime_state_cache.discard(sid)
            if terminals is not None:
                for terminal in await terminals.get_for_session(sid):
                    await terminals.remove(terminal.id)
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
        await cleanup_deleted_history(
            store, timeline_buffer, runtime_state_cache, audits, terminals
        )
        return [sid for audit in audits for sid in audit["session_ids"]]
    async with store.connector_lifecycle(connector_id):
        states = await runtime_state_cache.get_many(ids)
        busy = {
            sid
            for sid, state in states.items()
            if state.status in BUSY_SESSION_STATUSES
        }
        ids = await store.delete_history(
            object_id,
            user_id=user_id,
            project=project,
            expected_count=expected_count,
            cached_busy=busy,
        )
        audits = await store.pending_history_cleanup(
            object_id=object_id, project=project, user_id=user_id
        )
        await cleanup_deleted_history(
            store, timeline_buffer, runtime_state_cache, audits, terminals
        )
    return ids
