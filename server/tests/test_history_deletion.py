from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from agent_server.infra.connector_rpc import ConnectorOfflineError
from agent_server.core.history_deletion import SessionDeletedError
from agent_server.core.models import SessionRuntimeState
from agent_server.core.utc import utc_now
from agent_server.infra.db import schema as db
from agent_server.infra.files.local import LocalFileStorage
from agent_server.services.connector_notifications import ConnectorNotificationService
from sqlalchemy import insert, select, update
from test_connector_deletion import (
    add_session,
    create_device,
    create_project,
    timeline_input,
)
from test_connector_deletion import (
    api as api_fixture,
)

api = api_fixture


def setup_history(api):
    client, headers = api
    device = create_device(client, headers)
    project = create_project(client, headers, device, "History")
    session = add_session(client, device, project, "thread_original")
    return client, headers, device, project, session


def test_delete_session_removes_contents_files_and_survives_native_replay(
    api, tmp_path
):
    client, headers, device, project, sid = setup_history(api)
    store = client.app.state.store
    store.files = LocalFileStorage(tmp_path / "blobs")

    async def seed():
        await store.files.write(
            sid,
            "file_test",
            b"payload",
            {"name": "test.txt", "mediaType": "text/plain"},
        )
        (tmp_path / "blobs" / sid / "file_test.thumb-512.webp").write_bytes(b"preview")
        await store.upsert_timeline_item(session_id=sid, item=timeline_input(sid))
        await client.app.state.timeline_write_buffer.accept(
            session_id=sid, item=timeline_input(sid, "pending")
        )
        now = utc_now()
        await client.app.state.session_runtime_state_cache.put(
            SessionRuntimeState(
                sessionId=sid,
                runtime="codex",
                status="idle",
                updatedSeq=2,
                createdAt=now,
                updatedAt=now,
            )
        )

    asyncio.run(seed())
    response = client.delete(f"/sessions/{sid}", headers=headers)
    assert response.status_code == 204, response.text
    assert client.get(f"/sessions/{sid}/meta", headers=headers).status_code == 404
    assert client.delete(f"/sessions/{sid}", headers=headers).status_code == 404
    assert not (tmp_path / "blobs" / sid).exists()
    # Fresh list reads from any client use the same durable Server state.
    assert client.get("/sessions", headers=headers).json()["sessions"] == []
    assert (
        client.get("/projects", headers=headers).json()["projects"][0]["id"] == project
    )

    async def verify():
        assert await store.timeline.read(sid) == []
        assert await client.app.state.session_runtime_state_cache.get(sid) is None
        assert (
            sid not in await client.app.state.timeline_write_buffer.dirty_session_ids()
        )
        async with store.engine.connect() as conn:
            audit = (
                (await conn.execute(select(db.history_deletion_audit))).mappings().one()
            )
            assert audit["object_id"] == sid and audit["cleanup_pending"] == 0
            tombstone = (
                (await conn.execute(select(db.history_deletions))).mappings().one()
            )
            assert len(tombstone["source_key"]) == 64
            assert "thread_original" not in str(tombstone)
        for replay_id in [sid, "sess_different_alias"]:
            with pytest.raises(SessionDeletedError):
                await store.upsert_connector_session(
                    connector_id=device,
                    session_id=replay_id,
                    runtime="codex",
                    external_session_id="thread_original",
                    cwd="/work/History",
                )
        # A deleted notification is acknowledged without invoking any handlers or realtime.
        realtime = AsyncMock()
        service = ConnectorNotificationService(store, realtime)
        effect = await service.apply(
            connector_id=device,
            method="session.meta.upsert",
            params={
                "sessionId": "sess_alias",
                "externalSessionId": "thread_original",
                "runtime": "codex",
            },
        )
        assert effect.session_id is None
        realtime.apply.assert_not_called()
        with pytest.raises(KeyError):
            await client.app.state.timeline_write_buffer.accept(
                session_id=sid, item=timeline_input(sid, "late")
            )

    asyncio.run(verify())


@pytest.mark.parametrize(
    "status", ["running", "waiting", "pending", "stopping", "waiting_approval"]
)
def test_busy_session_refuses_individual_and_project_deletion(api, status):
    client, headers, _, project, sid = setup_history(api)

    async def busy():
        async with client.app.state.store.engine.begin() as conn:
            await conn.execute(
                update(db.sessions).where(db.sessions.c.id == sid).values(status=status)
            )

    asyncio.run(busy())
    for path in [f"/sessions/{sid}", f"/projects/{project}"]:
        response = client.delete(path, headers=headers)
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "session_running"
        assert sid in response.json()["detail"]["sessionIds"]
    assert client.get(f"/sessions/{sid}/meta", headers=headers).status_code == 200


@pytest.mark.parametrize("fact", ["active_run", "cache", "active_goal"])
def test_busy_facts_override_idle_database_status(api, fact):
    client, headers, _, _, sid = setup_history(api)
    store = client.app.state.store

    async def seed():
        now = utc_now()
        if fact == "active_run":
            await store.start_active_run(session_id=sid, runtime="codex")
        elif fact == "cache":
            await client.app.state.session_runtime_state_cache.put(
                SessionRuntimeState(
                    sessionId=sid,
                    runtime="codex",
                    status="running",
                    updatedSeq=1,
                    createdAt=now,
                    updatedAt=now,
                )
            )
        else:
            async with store.engine.begin() as conn:
                await conn.execute(
                    insert(db.session_goals).values(
                        session_id=sid,
                        goal_id="goal",
                        status="active",
                        source_revision=1,
                        payload="{}",
                        created_at=now,
                        updated_at=now,
                    )
                )

    asyncio.run(seed())
    response = client.delete(f"/sessions/{sid}", headers=headers)
    assert response.status_code == 409, response.text


def test_project_preview_includes_archived_and_count_race_requires_confirmation(api):
    client, headers, device, project, sid = setup_history(api)
    other = add_session(client, device, project, "archived_thread", archived=True)
    preview = client.get(f"/projects/{project}/deletion-preview", headers=headers)
    assert preview.status_code == 200 and preview.json()["sessionCount"] == 2
    conflict = client.delete(
        f"/projects/{project}?expectedSessionCount=1", headers=headers
    )
    assert (
        conflict.status_code == 409
        and conflict.json()["detail"]["code"] == "deletion_count_changed"
    )
    assert client.get(f"/sessions/{sid}/meta", headers=headers).status_code == 200
    response = client.delete(
        f"/projects/{project}?expectedSessionCount=2", headers=headers
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["deletedSessions"] == 2
        and response.json()["detachedSessions"] == 0
    )
    assert client.get("/projects", headers=headers).json()["projects"] == []
    for item in [sid, other]:
        assert client.get(f"/sessions/{item}/meta", headers=headers).status_code == 404


def test_deletion_and_preview_require_owner(api):
    client, headers, _, project, sid = setup_history(api)
    client.patch(
        "/admin/settings", headers=headers, json={"registrationOpen": True}
    ).raise_for_status()
    other = client.post(
        "/auth/register",
        json={
            "email": "other@example.com",
            "displayName": "Other",
            "password": "secret",
        },
    )
    assert other.status_code == 200, other.text
    foreign_headers = {"Authorization": f"Bearer {other.json()['accessToken']}"}
    for path in [f"/sessions/{sid}", f"/projects/{project}"]:
        assert client.delete(path, headers=foreign_headers).status_code == 403
    assert (
        client.get(
            f"/projects/{project}/deletion-preview", headers=foreign_headers
        ).status_code
        == 403
    )
    assert client.get(f"/sessions/{sid}/meta", headers=headers).status_code == 200


def test_storage_failure_does_not_report_success_and_can_retry(api, monkeypatch):
    client, headers, _, _, sid = setup_history(api)
    files = client.app.state.store.files
    original = files.delete_session
    monkeypatch.setattr(
        files,
        "delete_session",
        AsyncMock(side_effect=OSError("synthetic storage failure")),
    )
    with pytest.raises(OSError, match="synthetic storage failure"):
        client.delete(f"/sessions/{sid}", headers=headers)
    assert client.get(f"/sessions/{sid}/meta", headers=headers).status_code == 200
    monkeypatch.setattr(files, "delete_session", original)
    assert client.delete(f"/sessions/{sid}", headers=headers).status_code == 204


def test_cache_cleanup_failure_persists_retry_across_recovery(api, monkeypatch):
    client, headers, _, _, sid = setup_history(api)
    cache = client.app.state.session_runtime_state_cache
    original = cache.discard
    monkeypatch.setattr(
        cache, "discard", AsyncMock(side_effect=OSError("synthetic cache failure"))
    )
    with pytest.raises(OSError, match="synthetic cache failure"):
        client.delete(f"/sessions/{sid}", headers=headers)
    assert client.get(f"/sessions/{sid}/meta", headers=headers).status_code == 404
    monkeypatch.setattr(cache, "discard", original)
    # Same request can finish cleanup despite the business row being gone.
    assert client.delete(f"/sessions/{sid}", headers=headers).status_code == 204
    assert asyncio.run(client.app.state.store.pending_history_cleanup()) == []


def test_new_runtime_binding_is_not_suppressed(api):
    client, headers, device, project, sid = setup_history(api)
    assert client.delete(f"/sessions/{sid}", headers=headers).status_code == 204

    async def new_source():
        return await client.app.state.store.upsert_connector_session(
            connector_id=device,
            session_id="sess_new",
            runtime="codex",
            external_session_id="new_thread",
            cwd="/work/History",
        )

    created = asyncio.run(new_source())
    assert created.id == "sess_new" and created.projectId == project


def test_project_deletion_handles_more_than_one_list_page(api):
    client, headers, _, project, sid = setup_history(api)
    store = client.app.state.store

    async def seed():
        async with store.engine.begin() as conn:
            template = dict(
                (await conn.execute(select(db.sessions).where(db.sessions.c.id == sid)))
                .mappings()
                .one()
            )
            await conn.execute(
                insert(db.sessions),
                [
                    dict(
                        template, id=f"sess_page_{i}", external_session_id=f"thread_{i}"
                    )
                    for i in range(105)
                ],
            )

    asyncio.run(seed())
    assert (
        client.get(f"/projects/{project}/deletion-preview", headers=headers).json()[
            "sessionCount"
        ]
        == 106
    )
    response = client.delete(
        f"/projects/{project}?expectedSessionCount=106", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["deletedSessions"] == 106


def test_duplicate_native_bindings_can_both_be_deleted(api):
    client, headers, device, project, sid = setup_history(api)
    alias = add_session(client, device, project, "thread_original")
    assert alias != sid
    response = client.delete(f"/projects/{project}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["deletedSessions"] == 2


def test_upload_finishes_before_deletion_and_cannot_leave_orphan(api, tmp_path):
    client, _, _, _, sid = setup_history(api)
    store = client.app.state.store
    store.files = LocalFileStorage(tmp_path / "files")

    async def scenario():
        user_id = await store.get_session_user_id(sid)
        async with store.attachment_write_fence(sid, user_id=user_id):
            task = asyncio.create_task(
                store.delete_history(sid, user_id=user_id, project=False)
            )
            await asyncio.sleep(0.05)
            assert not task.done()
            await store.files.write(sid, "file_race", b"synthetic", {})
        assert await asyncio.wait_for(task, 5) == [sid]
        with pytest.raises(KeyError):
            async with store.attachment_write_fence(sid, user_id=user_id):
                pytest.fail("deleted session accepted an upload")
        assert not (tmp_path / "files" / sid).exists()

    asyncio.run(scenario())


def test_admitted_run_and_deletion_cannot_both_succeed(api):
    client, _, _, _, sid = setup_history(api)
    store = client.app.state.store

    async def scenario():
        user_id = await store.get_session_user_id(sid)
        deletion, admission = await asyncio.gather(
            store.delete_history(sid, user_id=user_id, project=False),
            store.start_active_run(session_id=sid, runtime="codex"),
            return_exceptions=True,
        )
        assert isinstance(deletion, Exception) or isinstance(admission, Exception)
        if not isinstance(deletion, Exception):
            assert isinstance(admission, KeyError)
            assert await store.get_active_run(sid) is None
        else:
            from agent_server.core.history_deletion import HistoryDeletionConflict

            assert isinstance(deletion, HistoryDeletionConflict)
            assert admission is None

    asyncio.run(scenario())


def test_background_recovery_finishes_durable_pending_cleanup(api, monkeypatch):
    client, headers, _, _, sid = setup_history(api)
    cache = client.app.state.session_runtime_state_cache
    original = cache.discard
    monkeypatch.setattr(
        cache, "discard", AsyncMock(side_effect=OSError("synthetic failure"))
    )
    with pytest.raises(OSError, match="synthetic failure"):
        client.delete(f"/sessions/{sid}", headers=headers)
    monkeypatch.setattr(cache, "discard", original)

    async def recover():
        await client.app.state.connector_deletion_recovery.run_once()
        assert await client.app.state.store.pending_history_cleanup() == []

    asyncio.run(recover())


def test_session_deletion_clears_terminal_history_and_root_without_other_session(api):
    client, headers, device, project, sid = setup_history(api)
    other = add_session(client, device, project, "other_terminal_thread")
    store = client.app.state.store
    broker = client.app.state.terminal_broker

    async def seed():
        result = []
        for session_id in (sid, other):
            term = await broker.register(
                session_id=session_id,
                connector_id=device,
                label="test terminal",
                cwd="/work/History",
                shell="bash",
                cols=80,
                rows=24,
            )
            await broker.on_output(term.id, data=b"synthetic output", seq=1)
            await store.record_connector_terminal_root(
                connector_id=device,
                terminal_id=term.id,
                session_id=session_id,
                root="/work/History",
                cwd="/work/History",
            )
            result.append(term.id)
        return result

    deleted, retained = asyncio.run(seed())
    response = client.delete(f"/sessions/{sid}", headers=headers)
    assert response.status_code == 204, response.text

    async def verify():
        assert await broker.get(deleted) is None
        assert await broker.get(retained) is not None
        assert (
            await store.get_connector_terminal_root(
                connector_id=device, terminal_id=deleted
            )
            is None
        )
        assert (
            await store.get_connector_terminal_root(
                connector_id=device, terminal_id=retained
            )
            is not None
        )

    asyncio.run(verify())


@pytest.mark.parametrize(
    "phase, expected", [("accepted", 204), ("opening", 409), ("outcome_unknown", 409)]
)
def test_creation_workflow_admission_is_not_confused_with_an_active_turn(
    api, phase, expected
):
    import json

    client, headers, device, project, sid = setup_history(api)
    store = client.app.state.store

    async def seed():
        user_id = await store.get_session_user_id(sid)
        async with store.engine.begin() as conn:
            await conn.execute(
                insert(db.runtime_workflows).values(
                    user_id=user_id,
                    kind="creation",
                    id="creation_test",
                    connector_id=device,
                    runtime_id="codex",
                    runtime_type="codex",
                    project_id=project,
                    session_id=sid,
                    input_digest="synthetic",
                    request_json="{}",
                    result_json=json.dumps({"phase": phase}),
                )
            )

    asyncio.run(seed())
    response = client.delete(f"/sessions/{sid}", headers=headers)
    assert response.status_code == expected, response.text


def test_late_terminal_root_cannot_recreate_deleted_session_data(api):
    client, headers, device, _, sid = setup_history(api)
    assert client.delete(f"/sessions/{sid}", headers=headers).status_code == 204

    async def late():
        with pytest.raises(SessionDeletedError):
            await client.app.state.store.record_connector_terminal_root(
                connector_id=device,
                terminal_id="late_terminal",
                session_id=sid,
                root="/work/History",
                cwd="/work/History",
            )
        assert (
            await client.app.state.store.get_connector_terminal_root(
                connector_id=device, terminal_id="late_terminal"
            )
            is None
        )

    asyncio.run(late())


def device_cleanup(api, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from connector.core.json_kv import JsonKeyValueStore
    from connector.server.history_cleanup import HistoryCleanup
    client, headers, device, project, sid = setup_history(api)
    directory = tmp_path / "project"; directory.mkdir(); (directory / "source.txt").write_text("project data")
    home = tmp_path / "home"; home.mkdir()
    data = home / ".agents-anywhere-fork"; data.mkdir()
    native = SimpleNamespace(prepare_history_deletion=AsyncMock(), delete_session_history=AsyncMock())
    worker = HistoryCleanup(device, lambda _: native, kv=JsonKeyValueStore(data / "kv.json"), data_dir=data, home=home)
    async def configure():
        async with client.app.state.store.engine.begin() as conn:
            await conn.execute(update(db.projects).where(db.projects.c.id == project).values(workspace_path=str(directory), workspace_key=str(directory)))
    asyncio.run(configure())
    async def rpc(connector, method, params, **kwargs):
        assert connector == device
        if method == "history.cleanup.prepare": return await worker.prepare(params)
        if method == "history.cleanup.commit": return await worker.commit(params)
        return await worker.release(params, cancel=method.endswith("cancel"))
    request = AsyncMock(side_effect=rpc)
    monkeypatch.setattr(client.app.state.rpc, "request", request)
    return client, headers, project, sid, directory, native, request, rpc


def test_complete_session_deletion_cleans_native_data_but_keeps_project_files(api, tmp_path, monkeypatch):
    client, headers, project, sid, directory, native, request, _ = device_cleanup(api, tmp_path, monkeypatch)
    result = client.delete(f"/sessions/{sid}/contents", headers=headers)
    assert result.status_code == 204, result.text
    native.delete_session_history.assert_awaited_once()
    assert request.await_count == 3
    assert directory.exists() and (directory / "source.txt").exists()
    assert client.get(f"/sessions/{sid}/meta", headers=headers).status_code == 404
    assert any(item["id"] == project for item in client.get("/projects", headers=headers).json()["projects"])


def test_offline_device_never_turns_full_deletion_into_record_only_deletion(api, tmp_path, monkeypatch):
    client, headers, project, sid, directory, native, request, _ = device_cleanup(api, tmp_path, monkeypatch)
    request.side_effect = ConnectorOfflineError("device offline")
    result = client.delete(f"/projects/{project}/contents?expectedSessionCount=1", headers=headers)
    assert result.status_code == 503
    assert client.get(f"/sessions/{sid}/meta", headers=headers).status_code == 200
    assert directory.exists()
    native.delete_session_history.assert_not_awaited()


def test_interrupted_device_cleanup_is_durable_and_retry_removes_the_project_directory(api, tmp_path, monkeypatch):
    client, headers, project, sid, directory, native, request, rpc = device_cleanup(api, tmp_path, monkeypatch)
    store = client.app.state.store
    owner = asyncio.run(store.get_session_user_id(sid))
    connector = asyncio.run(store.get_session(sid)).connectorId
    async def disconnect_after_commit(connector, method, params, **kwargs):
        if method.endswith("commit"): raise ConnectorOfflineError("lost connection after SQL deletion")
        return await rpc(connector, method, params, **kwargs)
    request.side_effect = disconnect_after_commit
    result = client.delete(f"/projects/{project}/contents?expectedSessionCount=1", headers=headers)
    assert result.status_code == 503 and directory.exists()
    async def verify_pending():
        audits = await store.pending_history_cleanup(object_id=project, project=True, user_id=owner)
        assert len(audits) == 1 and audits[0]["device_cleanup_json"]
        with pytest.raises(SessionDeletedError):
            await store.create_project(user_id=owner, connector_id=connector, name="new", workspace_path=str(directory))
    asyncio.run(verify_pending())
    request.side_effect = rpc
    result = client.delete(f"/projects/{project}/contents?expectedSessionCount=1", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["deletedSessions"] == 1
    assert not directory.exists()
    native.delete_session_history.assert_awaited_once()
    async def verify_done():
        async with store.engine.connect() as conn:
            audit = (await conn.execute(select(db.history_deletion_audit).where(db.history_deletion_audit.c.object_id == project))).mappings().one()
            assert audit["cleanup_pending"] == 0 and audit["device_cleanup_json"] is None
        await store.create_project(user_id=owner, connector_id=connector, name="new", workspace_path=str(directory))
    asyncio.run(verify_done())


def test_legacy_endpoint_can_retry_full_device_cleanup(api, tmp_path, monkeypatch):
    client, headers, project, sid, directory, native, request, rpc = device_cleanup(api, tmp_path, monkeypatch)
    async def fail_commit(connector, method, params, **kwargs):
        if method.endswith("commit"): raise ConnectorOfflineError("offline")
        return await rpc(connector, method, params, **kwargs)
    request.side_effect = fail_commit
    assert client.delete(f"/projects/{project}/contents?expectedSessionCount=1", headers=headers).status_code == 503
    request.side_effect = rpc
    result = client.delete(f"/projects/{project}", headers=headers)
    assert result.status_code == 200, result.text
    assert not directory.exists()


def test_abandon_cleanup_preserves_replaced_directory_and_unlocks_path(api, tmp_path, monkeypatch):
    client, headers, project, sid, directory, native, request, rpc = device_cleanup(api, tmp_path, monkeypatch)
    store = client.app.state.store
    owner = asyncio.run(store.get_session_user_id(sid))
    connector = asyncio.run(store.get_session(sid)).connectorId
    async def replace_after_prepare(connector, method, params, **kwargs):
        if method.endswith("commit"):
            directory.rename(directory.with_name("original")); directory.mkdir()
            (directory / "new").write_text("keep this")
            from agent_server.infra.connector_rpc import ConnectorRpcError
            try: return await rpc(connector, method, params, **kwargs)
            except ValueError as error: raise ConnectorRpcError("invalid_request", str(error)) from error
        return await rpc(connector, method, params, **kwargs)
    request.side_effect = replace_after_prepare
    assert client.delete(f"/projects/{project}/contents", headers=headers).status_code == 503
    request.side_effect = rpc
    response = client.post(f"/projects/{project}/contents/abandon", headers=headers)
    assert response.status_code == 204, response.text
    assert (directory / "new").read_text() == "keep this"
    native.delete_session_history.assert_not_awaited()
    asyncio.run(store.create_project(user_id=owner, connector_id=connector, name="reused", workspace_path=str(directory)))


def test_unexpected_prepare_error_is_not_reported_as_offline_device(api, tmp_path, monkeypatch):
    client, headers, project, sid, directory, native, request, _ = device_cleanup(api, tmp_path, monkeypatch)
    request.side_effect = RuntimeError("programming defect")
    with pytest.raises(RuntimeError, match="programming defect"):
        client.delete(f"/projects/{project}/contents", headers=headers)
    assert directory.exists()


def test_lost_release_ack_is_retryable_without_repeating_native_deletion(api, tmp_path, monkeypatch):
    client, headers, project, sid, directory, native, request, rpc = device_cleanup(api, tmp_path, monkeypatch)
    async def lose_release_ack(connector, method, params, **kwargs):
        result = await rpc(connector, method, params, **kwargs)
        if method.endswith("release"): raise ConnectorOfflineError("ack lost")
        return result
    request.side_effect = lose_release_ack
    assert client.delete(f"/projects/{project}/contents", headers=headers).status_code == 503
    assert not directory.exists()
    request.side_effect = rpc
    assert client.delete(f"/projects/{project}/contents", headers=headers).status_code == 200
    native.delete_session_history.assert_awaited_once()
