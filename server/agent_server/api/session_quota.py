from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import HTTPConnection

from agent_server.deps import current_user_id

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
):
    session = await owned(conn, session_id, user_id)
    return {"quotaLimit": session.quotaLimit}


@router.post("/{session_id}/quota/recheck")
async def recheck_quota(
    session_id: str,
    conn: HTTPConnection,
    user_id: Annotated[str, Depends(current_user_id)],
):
    session = await owned(conn, session_id, user_id)
    quota = session.quotaLimit
    if quota and quota.get("state") == "limited":
        service = conn.app.state.account_usage_service
        await service.refresh(user_id)
        snapshots = (await service.snapshot(user_id)).snapshots
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
        ):
            quota = await conn.app.state.store.finish_session_quota(
                session_id, expected=quota
            )
            await conn.app.state.session_runtime_state_cache.discard(session_id)
    return {"quotaLimit": quota}
