import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from agent_server.core.models import MessageCreateRequest, SessionRuntimeState
from agent_server.core.session_quota import project_quota_state
from agent_server.infra.db import schema as db
from agent_server.services.connector_notifications import (
    SessionStateNotificationHandler,
)
from agent_server.services.session_run import SessionRunConflictError, SessionRunService
from sqlalchemy import update
from test_account_usage import KEY, seed
from test_connector_deletion import add_session, create_device, create_project
from test_connector_deletion import api as api_fixture

api = api_fixture


@pytest.mark.parametrize("runtime", ["codex", "claude"])
def test_limit_cache_expiry_original_identity_and_deletion(api, runtime):
    client, headers = api
    device = create_device(client, headers)
    project = create_project(client, headers, device, "quota-project")
    store = client.app.state.store
    asyncio.run(seed(store, device, runtime))

    async def exercise():
        session = await store.create_session(
            connector_id=device,
            project_id=project,
            runtime=runtime,
            external_session_id="original-native",
            title="Quota",
            cwd=None,
        )
        now = datetime.now(UTC)
        async with store._engine.begin() as conn:
            await conn.execute(
                update(db.sessions)
                .where(db.sessions.c.id == session.id)
                .values(takeover=1)
            )
        source = next(
            s
            for s in await store.account_usage_sources()
            if s["connector_id"] == device
        )
        await store.claim_usage_discovery(source, now.timestamp())
        from agent_server.core.account_usage import UsageCollection, UsageIdentity

        name = "claude_code" if runtime == "claude" else runtime
        await store.save_usage_identity(
            source, UsageIdentity(runtime=name, account_key=KEY)
        )
        row = (await store.account_usage_rows())[0]
        token = await store.claim_account_usage(row, now.timestamp())
        resets = [
            (now + timedelta(minutes=5)).isoformat(),
            (now + timedelta(days=1)).isoformat(),
        ]
        await store.finish_account_usage(
            row,
            token,
            UsageCollection(
                runtime=name,
                account_key=KEY,
                stale=False,
                fetched_at=now,
                windows=[
                    {
                        "kind": kind,
                        "usedPercent": 100,
                        "remainingPercent": 0,
                        "resetsAt": reset,
                        "windowDurationMins": minutes,
                    }
                    for kind, minutes, reset in [
                        ("five_hour", 300, resets[0]),
                        ("weekly", 10080, resets[1]),
                    ]
                ],
            ),
            now.timestamp(),
        )
        params = {
            "sessionId": session.id,
            "runtime": runtime,
            "runtimeId": runtime,
            "externalSessionId": "original-native",
            "status": "error",
            "error": {"code": "usage_limit_reached"},
            "metadata": {"quotaLimited": True},
        }
        handler = SessionStateNotificationHandler(store)
        effect = await handler.apply(
            connector_id=device, method="session.state.updated", params=params
        )
        assert (
            effect.runtime_state["status"] == "limited"
            and effect.notices[0].title == "因限额中断"
        )
        assert effect.item["content"]["code"] == "usage_limit"
        again = await handler.apply(connector_id=device, method="session.state.updated", params=params)
        assert again.item["id"] == effect.item["id"]
        await store.replace_timeline_snapshot(session_id=session.id, items=[])
        items, _ = await store.list_timeline_since(session_id=session.id, after_seq=0, limit=100)
        assert sum(item.source.itemType == "usage_limit" for item in items) == 1
        session = await store.get_session(session.id)
        assert session.status == "limited" and datetime.fromisoformat(
            session.quotaLimit["resetsAt"]
        ) == datetime.fromisoformat(resets[1])
        # A late runtime idle/error and a warm cache cannot remove the durable wait.
        await store.set_session_status(session.id, "idle")
        assert (await store.get_session(session.id)).status == "limited"
        state = SessionRuntimeState(
            sessionId=session.id,
            runtime=runtime,
            status="error",
            externalSessionId="original-native",
            updatedSeq=1,
            createdAt=now.isoformat(),
            updatedAt=now.isoformat(),
        )
        assert project_quota_state(session, state).status == "limited"
        manager = type(
            "Rpc",
            (),
            {
                "is_online": AsyncMock(return_value=True),
                "request": AsyncMock(return_value={}),
            },
        )()
        service = SessionRunService(store, manager, None)
        service._ensure_session_runtime_running = AsyncMock()
        service._require_session_capability = AsyncMock()
        service._read_runtime_status = AsyncMock(return_value="error")
        owner = await store.get_session_user_id(session.id)
        with pytest.raises(SessionRunConflictError, match="session_usage_limited"):
            await service._send_message_admitted(
                session, MessageCreateRequest(content="continue"), user_id=owner
            )
        assert not manager.request.called
        # Advance the durable deadline without sleeping or accessing vendor services.
        quota = dict(
            session.quotaLimit, resetsAt=(now - timedelta(seconds=1)).isoformat()
        )
        async with store._engine.begin() as conn:
            await conn.execute(
                update(db.sessions)
                .where(db.sessions.c.id == session.id)
                .values(quota_json=json.dumps(quota))
            )
        session = await store.get_session(session.id)
        assert session.status == "idle" and session.quotaLimit["state"] == "ready"
        assert project_quota_state(session, state).status == "idle"
        await service._send_message_admitted(
            session, MessageCreateRequest(content="continue"), user_id=owner
        )
        calls = [
            call
            for call in manager.request.call_args_list
            if call.args[1] == "session.send_message"
        ]
        assert (
            len(calls) == 1
            and calls[0].args[2]["externalSessionId"] == "original-native"
        )
        assert all(
            call.args[1] != "session.create" for call in manager.request.call_args_list
        )
        # Native identity loss can never turn a continuation into creation.
        async with store._engine.begin() as conn:
            await conn.execute(
                update(db.sessions)
                .where(db.sessions.c.id == session.id)
                .values(external_session_id=None)
            )
        with pytest.raises(
            SessionRunConflictError, match="session_resume_identity_missing"
        ):
            await service._send_message_admitted(
                session, MessageCreateRequest(content="continue"), user_id=owner
            )
        await store.clear_active_run(session.id)
        return session.id

    session_id = asyncio.run(exercise())
    response = client.get(f"/sessions/{session_id}/quota", headers=headers)
    assert (
        response.status_code == 200
        and response.json()["quotaLimit"]["state"] == "resumed"
    )
    assert client.delete(f"/sessions/{session_id}", headers=headers).status_code == 204
    assert (
        client.get(f"/sessions/{session_id}/quota", headers=headers).status_code == 404
    )


def test_ordinary_error_does_not_create_limit(api):
    client, headers = api
    device = create_device(client, headers)
    project = create_project(client, headers, device, "ordinary")
    sid = add_session(client, device, project, "native")

    async def exercise():
        effect = await SessionStateNotificationHandler(client.app.state.store).apply(
            connector_id=device,
            method="session.state.updated",
            params={
                "sessionId": sid,
                "runtime": "codex",
                "runtimeId": "codex",
                "status": "error",
                "error": {"code": 429, "message": "rate limited"},
            },
        )
        assert effect.runtime_state["status"] == "error"
        assert (await client.app.state.store.get_session(sid)).quotaLimit is None

    asyncio.run(exercise())


@pytest.mark.parametrize("stop", [False, True])
def test_unknown_deadline_recheck_and_stop(api, stop):
    from agent_server.core.account_usage import UsageResponse, UsageSnapshot

    client, headers = api
    device = create_device(client, headers)
    project = create_project(client, headers, device, "unknown")
    sid = add_session(client, device, project, "original")
    store = client.app.state.store
    now = datetime.now(UTC)
    quota = {
        "state": "limited",
        "accountKey": KEY,
        "windows": [],
        "resetsAt": None,
        "externalSessionId": "original",
        "interruptedAt": (now - timedelta(seconds=1)).isoformat(),
    }

    async def persist():
        async with store._engine.begin() as conn:
            await conn.execute(
                update(db.sessions)
                .where(db.sessions.c.id == sid)
                .values(quota_json=json.dumps(quota), status="limited", takeover=1)
            )

    asyncio.run(persist())
    if stop:
        response = client.post(f"/sessions/{sid}/runtime/interrupt", headers=headers)
        assert response.status_code == 200, response.text
        assert (
            client.get(f"/sessions/{sid}/quota", headers=headers).json()["quotaLimit"][
                "state"
            ]
            == "stopped"
        )
        assert client.delete(f"/sessions/{sid}", headers=headers).status_code == 204
        return
    snapshot = UsageSnapshot(
        runtime="codex",
        account_key=KEY,
        account_label="aaa",
        windows=[
            {
                "kind": "five_hour",
                "usedPercent": 50,
                "remainingPercent": 50,
                "resetsAt": (now + timedelta(hours=1)).isoformat(),
                "windowDurationMins": 300,
            }
        ],
        fetched_at=now,
        stale=True,
        next_attempt_at=now.timestamp() + 60,
        bindings=[{"connectorId": device, "runtimeId": "codex"}],
    )
    service = type(
        "Usage",
        (),
        {
            "refresh": AsyncMock(),
            "snapshot": AsyncMock(
                return_value=UsageResponse(
                    snapshots=[snapshot], unavailable=[], server_time=now.isoformat()
                )
            ),
        },
    )()
    client.app.state.account_usage_service = service
    response = client.post(f"/sessions/{sid}/quota/recheck", headers=headers)
    assert response.json()["quotaLimit"]["state"] == "limited"
    snapshot.stale = False
    snapshot.account_key = "b" * 64
    assert (
        client.post(f"/sessions/{sid}/quota/recheck", headers=headers).json()[
            "quotaLimit"
        ]["state"]
        == "limited"
    )
    snapshot.account_key = KEY
    assert (
        client.post(f"/sessions/{sid}/quota/recheck", headers=headers).json()[
            "quotaLimit"
        ]["state"]
        == "ready"
    )
    assert service.refresh.call_count == 3



def test_limited_events_use_new_version_and_ready_events_keep_legacy_delivery():
    from agent_server.core.events import protocol_event
    limited = protocol_event("same", sequence=1, event_type="runtime.state.updated", payload={"runtimeState": {"status": "limited"}})
    ready = protocol_event("same", sequence=2, event_type="runtime.state.updated", payload={"runtimeState": {"status": "idle", "metadata": {"quotaLimit": {"state":"ready"}}}})
    assert limited.protocolVersion == "1.2" and ready.protocolVersion == "1.0"



def test_deleting_limited_session_never_recreates_it(api):
    client, headers = api
    device = create_device(client, headers)
    project = create_project(client, headers, device, "delete-limited")
    sid = add_session(client, device, project, "original")
    async def mark():
        store = client.app.state.store
        session = await store.get_session(sid)
        await store.record_session_quota(session)
        assert (await store.get_session(sid)).status == "limited"
    asyncio.run(mark())
    assert client.delete(f"/sessions/{sid}", headers=headers).status_code == 204
    assert client.get(f"/sessions/{sid}/quota", headers=headers).status_code == 404
