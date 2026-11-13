from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import HTTPConnection

from agent_server.deps import current_user_id, get_session_run_service
from agent_server.services.session_run import SessionRunService

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def owned(conn, session_id, user_id):
    try:
        return await conn.app.state.store.get_session(session_id, user_id=user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found") from None


@router.get("/{session_id}/quota")
async def quota_state(
    session_id: str,
    conn: HTTPConnection,
    user_id: Annotated[str, Depends(current_user_id)],
    run_service: Annotated[SessionRunService, Depends(get_session_run_service)],
):
    session = await owned(conn, session_id, user_id)
    quota = session.quotaLimit
    if quota and quota.get("state") == "ready":
        quota = await run_service.finish_quota(session_id, expected=quota)
    return {"quotaLimit": quota}


@router.post("/{session_id}/quota/recheck")
async def recheck_quota(
    session_id: str,
    conn: HTTPConnection,
    user_id: Annotated[str, Depends(current_user_id)],
    run_service: Annotated[SessionRunService, Depends(get_session_run_service)],
):
    session = await owned(conn, session_id, user_id)
    quota = session.quotaLimit
    if quota and quota.get("state") == "ready":
        quota = await run_service.finish_quota(session_id, expected=quota)
    if quota and quota.get("state") == "limited":
        service = conn.app.state.account_usage_service
        await service.refresh(user_id)
        usage = await service.snapshot(user_id)
        snapshots = usage.snapshots
        snapshot = next(
            (
                s
                for s in snapshots
                if s.account_key == quota.get("accountKey")
                and any(
                    b.connector_id == session.connectorId
                    and b.runtime_id == session.runtimeId
                    for b in s.bindings
                )
            ),
            None,
        )
        if (
            snapshot
            and not snapshot.stale
            and snapshot.fetched_at
            and snapshot.fetched_at > datetime.fromisoformat(quota["interruptedAt"])
            and snapshot.windows
            and all(w.remaining_percent > 0 for w in snapshot.windows)
            and (snapshot.runtime != "claude_code" or all(
                w.received_at is not None
                and w.received_at > datetime.fromisoformat(quota["interruptedAt"])
                and w.resets_at > datetime.fromisoformat(usage.server_time)
                for w in snapshot.windows
            ))
        ):
            quota = await run_service.finish_quota(
                session_id, expected=quota
            )
            await conn.app.state.session_runtime_state_cache.discard(session_id)
    return {"quotaLimit": quota}
