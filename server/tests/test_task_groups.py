import asyncio
from types import SimpleNamespace

import pytest
from agent_server.api.task_groups import service as task_service
from agent_server.core.task_groups import TaskGroupCreate, TaskGroupHandoff
from agent_server.services.task_groups import TaskGroupService
from connector.local import worktrees
from test_connector_deletion import api as api_fixture
from test_connector_deletion import create_device, create_project

api = api_fixture


class Rpc:
    def __init__(self, repo):
        self.repo = repo
        self.calls = []

    async def request(self, connector_id, method, params, *, timeout):
        self.calls.append(method)
        return await asyncio.to_thread(
            getattr(worktrees, method.split(".")[1]), {**params, "root": str(self.repo)}
        )


class Runs:
    def __init__(self, store):
        self.store = store
        self.calls = []
        self.fail = False

    async def create_and_start_session(self, payload, *, user_id, reserved_session_id):
        self.calls.append(payload)
        session = await self.store.create_session(
            connector_id=payload.connectorId,
            project_id=payload.projectId,
            user_id=user_id,
            runtime=payload.runtime,
            runtime_id=payload.runtimeId,
            external_session_id="native_" + reserved_session_id,
            title=payload.title,
            cwd=payload.cwd,
            session_id=reserved_session_id,
            takeover=True,
        )
        if self.fail:
            raise TimeoutError("lost response")
        return {"session": session}


@pytest.fixture
def setup(api, tmp_path):
    client, headers = api
    repo = tmp_path / "repo"
    repo.mkdir()
    worktrees.git(repo, "init")
    worktrees.git(repo, "config", "user.name", "Test")
    worktrees.git(repo, "config", "user.email", "test@localhost")
    (repo / "file.txt").write_text("base\n")
    worktrees.git(repo, "add", ".")
    worktrees.git(repo, "commit", "-m", "baseline")
    device = create_device(client, headers)
    project = create_project(client, headers, device, "Parallel")
    store = client.app.state.store
    project_view = client.get("/projects", headers=headers).json()["projects"][0]
    rpc, runs = Rpc(repo), Runs(store)
    svc = TaskGroupService(store, rpc, runs)
    client.app.dependency_overrides[task_service] = lambda: svc
    request = {
        "operationId": "parallel-test-001",
        "projectId": project,
        "content": "Improve the implementation",
        "candidates": [{"runtime": "codex", "runtimeId": "codex"}] * 3,
    }
    return SimpleNamespace(
        client=client,
        headers=headers,
        store=store,
        svc=svc,
        runs=runs,
        rpc=rpc,
        user_id=project_view["userId"],
        request=request,
        repo=repo,
    )


def create(s):
    result = s.client.post("/api/v2/task-groups", headers=s.headers, json=s.request)
    assert result.status_code == 200, result.text
    return result.json()


def test_preparation_does_not_run_agents_and_same_operation_is_idempotent(setup):
    s = setup
    first = create(s)
    second = create(s)
    assert first["id"] == second["id"] and first["paths"] == second["paths"]
    assert len(set(first["paths"])) == 3 and not s.runs.calls
    conflict = s.client.post(
        "/api/v2/task-groups", headers=s.headers, json={**s.request, "content": "other"}
    )
    assert conflict.status_code == 409
    assert s.client.get(f"/api/v2/task-groups/{first['id']}").status_code == 401
    with pytest.raises(KeyError):
        asyncio.run(s.svc.get(first["id"], user_id="someone-else"))


def test_concurrent_start_claims_once_and_preserves_other_candidates(setup):
    s = setup
    row = create(s)

    async def start():
        return await asyncio.gather(
            *(s.svc.start(row["id"], 0, user_id=s.user_id) for _ in range(8))
        )

    results = asyncio.run(start())
    assert len(s.runs.calls) == 1
    result = asyncio.run(s.svc.get(row["id"], user_id=s.user_id))
    assert result["candidates"][0]["phase"] == "sent"
    assert result["candidates"][1]["phase"] == "pending"
    assert s.runs.calls[0].cwd == row["paths"][0]
    assert len({r["candidates"][0]["sessionId"] for r in results}) == 1


def test_unknown_and_recovered_dispatch_are_never_replayed(setup):
    s = setup
    row = create(s)
    s.runs.fail = True
    first = asyncio.run(s.svc.start(row["id"], 0, user_id=s.user_id))
    assert first["candidates"][0]["phase"] == "unknown"
    asyncio.run(s.svc.start(row["id"], 0, user_id=s.user_id))
    assert len(s.runs.calls) == 1
    asyncio.run(
        s.store.change_task_group(
            row["id"],
            user_id=s.user_id,
            slot=1,
            patch={"phase": "dispatching", "sessionId": "sess_recovery"},
        )
    )
    recovered = TaskGroupService(s.store, s.rpc, s.runs)
    asyncio.run(recovered.start(row["id"], 1, user_id=s.user_id))
    assert len(s.runs.calls) == 1


def test_selection_handoff_uses_frozen_snapshot_and_sends_brief_only_on_start(setup):
    s = setup
    row = create(s)
    row = asyncio.run(s.svc.start(row["id"], 0, user_id=s.user_id))
    from pathlib import Path

    source = Path(row["paths"][0])
    (source / "new.txt").write_text("candidate result\n")
    row = asyncio.run(s.svc.select(row["id"], 0, user_id=s.user_id))
    assert row["selected"] == 0
    payload = TaskGroupHandoff(
        operationId="handoff-test-001",
        slot=0,
        mode="review",
        target={"runtime": "claude", "runtimeId": "claude"},
    )
    result = asyncio.run(s.svc.handoff(row["id"], payload, user_id=s.user_id))
    assert len(s.runs.calls) == 1
    assert result["phase"] == "ready" and result["candidates"][0]["phase"] == "pending"
    assert (Path(result["paths"][0]) / "new.txt").read_text() == "candidate result\n"
    assert row["candidates"][0]["sessionId"] in result["handoffBrief"]
    assert "不要修改代码" in result["handoffBrief"]
    asyncio.run(s.svc.start(result["id"], 0, user_id=s.user_id))
    assert len(s.runs.calls) == 2 and s.runs.calls[-1].runtime == "claude"
    assert s.runs.calls[-1].content == result["handoffBrief"]


def test_running_candidate_and_active_run_refuse_selection_and_handoff(setup):
    s = setup
    row = create(s)
    row = asyncio.run(s.svc.start(row["id"], 0, user_id=s.user_id))
    sid = row["candidates"][0]["sessionId"]

    async def busy():
        await s.store.start_active_run(
            session_id=sid, runtime="codex", status="running"
        )

    asyncio.run(busy())
    with pytest.raises(ValueError, match="stop"):
        asyncio.run(s.svc.select(row["id"], 0, user_id=s.user_id))
    assert (
        s.client.post(
            f"/api/v2/task-groups/{row['id']}/candidates/-1/start", headers=s.headers
        ).status_code
        == 409
    )


@pytest.mark.parametrize("count", [1, 2, 3])
def test_one_two_and_three_candidates_can_prepare_and_start(setup, count):
    s = setup
    s.request["candidates"] = s.request["candidates"][:count]
    row = create(s)
    assert len(row["paths"]) == count
    for slot in range(count):
        result = asyncio.run(s.svc.start(row["id"], slot, user_id=s.user_id))
        assert result["candidates"][slot]["phase"] == "sent"
    assert len(s.runs.calls) == count


def test_custom_forward_instructions_are_preserved_and_idempotent(setup):
    s = setup
    row = create(s)
    asyncio.run(s.svc.start(row["id"], 0, user_id=s.user_id))
    payload = TaskGroupHandoff(operationId="forward-custom-001", slot=0, mode="continue",
        instructions="请检查这个结果是否正确，先不要修改代码。", target={"runtime":"claude", "runtimeId":"claude"})
    first = asyncio.run(s.svc.handoff(row["id"], payload, user_id=s.user_id))
    repeated = asyncio.run(s.svc.handoff(row["id"], payload, user_id=s.user_id))
    assert first["id"] == repeated["id"]
    assert first["handoffBrief"].startswith(payload.instructions)
    assert "从当前代码快照继续以下任务" not in first["handoffBrief"]
    asyncio.run(s.svc.start(first["id"], 0, user_id=s.user_id))
    assert payload.instructions in s.runs.calls[-1].content
    changed = payload.model_copy(update={"instructions":"Another instruction"})
    with pytest.raises(ValueError, match="another request"):
        asyncio.run(s.svc.handoff(row["id"], changed, user_id=s.user_id))


def test_candidate_count_and_empty_tasks_are_rejected():
    from pydantic import ValidationError

    for content, count in [(" ", 3), ("task", 0), ("task", 4)]:
        with pytest.raises(ValidationError):
            TaskGroupCreate(
                operationId="validation-001",
                projectId="p",
                content=content,
                candidates=[{"runtime": "codex", "runtimeId": "codex"}] * count,
            )


def test_initial_attachments_reach_all_candidates_and_forward_without_text_expansion(setup):
    s = setup
    attachment = {"fileId": "initial-file", "name": "task.txt", "mediaType": "text/plain", "contentBase64": "aGVsbG8="}
    s.request["attachments"] = [attachment]
    row = create(s)
    assert "contentBase64" not in row["request"]["attachments"][0]
    for slot in range(3):
        asyncio.run(s.svc.start(row["id"], slot, user_id=s.user_id))
    assert all(call.attachments[0].contentBase64 == "aGVsbG8=" for call in s.runs.calls)
    payload = TaskGroupHandoff(operationId="forward-attachment-001", slot=0, mode="review", target={"runtime": "claude", "runtimeId": "claude"})
    forwarded = asyncio.run(s.svc.handoff(row["id"], payload, user_id=s.user_id))
    asyncio.run(s.svc.start(forwarded["id"], 0, user_id=s.user_id))
    assert s.runs.calls[-1].attachments[0].name == "task.txt"
    assert "aGVsbG8=" not in s.runs.calls[-1].content


def test_forward_explicit_attachment_checks_source_session_ownership(setup):
    s = setup
    row = create(s)
    source = asyncio.run(s.svc.start(row["id"], 0, user_id=s.user_id))
    saved = asyncio.run(s.store.save_user_uploaded_file(session_id=source["candidates"][0]["sessionId"], user_id=s.user_id, name="review.txt", data=b"review", media_type="text/plain"))
    payload = TaskGroupHandoff(operationId="forward-extra-file-001", slot=0, mode="review", attachments=[{"fileId": saved["fileId"]}], target={"runtime":"claude", "runtimeId":"claude"})
    forwarded = asyncio.run(s.svc.handoff(row["id"], payload, user_id=s.user_id))
    assert forwarded["request"]["attachments"][0]["contentBase64"] == "cmV2aWV3"
    invalid = payload.model_copy(update={"operationId":"forward-extra-file-002", "attachments":[type(payload.attachments[0])(fileId="missing-file")]})
    with pytest.raises(KeyError):
        asyncio.run(s.svc.handoff(row["id"], invalid, user_id=s.user_id))


def test_forward_deduplicates_reuploaded_original_attachment(setup):
    s = setup
    s.request["attachments"] = [{"fileId":"original-id", "name":"task.txt", "contentBase64":"aGVsbG8="}]
    row = create(s)
    source = asyncio.run(s.svc.start(row["id"], 0, user_id=s.user_id))
    saved = asyncio.run(s.store.save_user_uploaded_file(session_id=source["candidates"][0]["sessionId"], user_id=s.user_id, name="task.txt", data=b"hello", media_type="text/plain"))
    payload = TaskGroupHandoff(operationId="forward-deduplicate-001", slot=0, mode="review", attachments=[{"fileId":saved["fileId"]}], target={"runtime":"claude", "runtimeId":"claude"})
    forwarded = asyncio.run(s.svc.handoff(row["id"], payload, user_id=s.user_id))
    assert len(forwarded["request"]["attachments"]) == 1


def test_plain_questions_start_two_ais_and_forward_text_and_attachments(setup, monkeypatch):
    s = setup
    ordinary = s.repo.parent / "ordinary"
    ordinary.mkdir()
    state = s.repo.parent / "state"
    state.mkdir()
    monkeypatch.setenv("AGENT_CONNECTOR_DATA_DIR", str(state))
    s.rpc.repo = ordinary
    s.request["content"] = "请解释月食是怎么发生的"
    s.request["candidates"] = [{"runtime": "codex", "runtimeId": "codex"}, {"runtime": "dsh", "runtimeId": "dsh"}]
    s.request["attachments"] = [{"fileId": "question", "name": "question.txt", "contentBase64": "aGVsbG8="}]
    row = create(s)
    assert row["base"] == "conversation"
    for slot in range(2):
        asyncio.run(s.svc.start(row["id"], slot, user_id=s.user_id))
    assert [call.runtime for call in s.runs.calls] == ["codex", "dsh"]
    assert all(call.content == s.request["content"] and call.attachments[0].name == "question.txt" for call in s.runs.calls)
    assert len({call.cwd for call in s.runs.calls}) == 2
    for mode in ("review", "continue"):
        forwarded = asyncio.run(s.svc.handoff(row["id"], TaskGroupHandoff(operationId=f"ordinary-forward-{mode}", slot=0, mode=mode, target={"runtime": "dsh", "runtimeId": "dsh"}), user_id=s.user_id))
        brief = forwarded["handoffBrief"]
        assert s.request["content"] in brief
        assert "git diff" not in brief and "交接快照" not in brief
        assert ("请审核以下问题" if mode == "review" else "请继续处理以下问题") in brief
        asyncio.run(s.svc.start(forwarded["id"], 0, user_id=s.user_id))
        assert s.runs.calls[-1].attachments[0].name == "question.txt"


def test_candidates_and_forwards_stay_in_original_project_after_sync(setup):
    s = setup
    row = create(s)
    project_count = len(s.client.get("/projects", headers=s.headers).json()["projects"])
    async def scenario():
        for slot in range(3):
            started = await s.svc.start(row["id"], slot, user_id=s.user_id)
            sid = started["candidates"][slot]["sessionId"]
            session = await s.store.get_session(sid, user_id=s.user_id)
            assert session.projectId == s.request["projectId"]
            assert session.cwd == row["paths"][slot]
            synced = await s.store.update_session_snapshot(session_id=sid, cwd=session.cwd, title="Runtime title")
            assert synced.projectId == session.projectId and synced.cwd == session.cwd
            imported = await s.store.upsert_connector_session(connector_id=session.connectorId, session_id=sid, runtime="codex", runtime_id="codex", external_session_id=session.externalSessionId, cwd=session.cwd, title="Synced")
            assert imported.projectId == session.projectId
        forwarded = await s.svc.handoff(row["id"], TaskGroupHandoff(operationId="same-project-forward", slot=0, mode="review", target={"runtime": "claude", "runtimeId": "claude"}), user_id=s.user_id)
        forwarded = await s.svc.start(forwarded["id"], 0, user_id=s.user_id)
        session = await s.store.get_session(forwarded["candidates"][0]["sessionId"], user_id=s.user_id)
        assert session.projectId == s.request["projectId"]
        assert session.cwd == forwarded["paths"][0]
        assert await s.store.get_task_group_session_project(session_id=session.id, connector_id=session.connectorId, cwd=session.cwd, user_id="another-user") is None
        with pytest.raises(ValueError, match="workspace"):
            await s.store.create_session(connector_id=session.connectorId, project_id=session.projectId, user_id=s.user_id, runtime="codex", runtime_id="codex", external_session_id=None, title="Invalid", cwd=row["paths"][1], session_id="sess_tg_unclaimed")
    asyncio.run(scenario())
    assert len(s.client.get("/projects", headers=s.headers).json()["projects"]) == project_count


def test_single_session_forward_stays_in_project_and_never_replays_source(setup):
    from agent_server.core.models import TimelineItemIn
    s = setup
    project = asyncio.run(s.store.get_project(s.request['projectId'], user_id=s.user_id))
    session = asyncio.run(s.store.create_session(
        connector_id=project.connectorId, project_id=project.id, user_id=s.user_id,
        runtime='codex', runtime_id='codex', external_session_id='ordinary-native',
        title='Original question', cwd=project.workspacePath, session_id='sess_ordinary_forward', takeover=True,
    ))
    saved = asyncio.run(s.store.save_user_uploaded_file(session_id=session.id, user_id=s.user_id, name='original.txt', data=b'original', media_type='text/plain'))
    asyncio.run(s.store.upsert_timeline_item(session_id=session.id, item=TimelineItemIn(
        id='original-message', sessionId=session.id, type='message', status='done', role='user',
        content={'text':'Original task', 'attachments':[{'fileId':saved['fileId']}]}, source={'runtime':'codex'}, orderSeq=1, contentHash='original',
    )))
    (s.repo / 'file.txt').write_text('dirty source')
    body = {'operationId':'single-forward-001', 'slot':0, 'mode':'review', 'instructions':'Check this', 'target':{'runtime':'dsh', 'runtimeId':'dsh'}}
    url = f'/api/v2/task-groups/from-session/{session.id}/handoffs'
    result = s.client.post(url, headers=s.headers, json=body)
    assert result.status_code == 200, result.text
    row = result.json()
    assert row['projectId'] == project.id
    assert 'Original task' in row['handoffBrief'] and 'Check this' in row['handoffBrief']
    assert row['request']['attachments'][0]['name'] == 'original.txt'
    assert 'contentBase64' not in row['request']['attachments'][0]
    assert not s.runs.calls
    assert s.client.post(url, headers=s.headers, json=body).json()['id'] == row['id']
    assert not s.runs.calls
    for _ in range(2):
        started = asyncio.run(s.svc.start(row['id'], 0, user_id=s.user_id))
    assert len(s.runs.calls) == 1
    target = asyncio.run(s.store.get_session(started['candidates'][0]['sessionId'], user_id=s.user_id))
    assert target.projectId == project.id
    assert s.runs.calls[0].runtime == 'dsh'
    assert s.runs.calls[0].attachments[0].name == 'original.txt'
    from pathlib import Path
    assert (Path(s.runs.calls[0].cwd) / 'file.txt').read_text() == 'dirty source'
    asyncio.run(s.store.start_active_run(session_id=session.id, runtime='codex', status='running'))
    refused = s.client.post(url, headers=s.headers, json={**body, 'operationId':'single-forward-busy'})
    assert refused.status_code == 409
    assert s.client.post(url, json=body).status_code == 401


def test_single_session_fanout_keeps_project_and_delivers_history_and_extra_attachments(setup):
    from agent_server.core.models import TimelineItemIn

    s = setup
    project = asyncio.run(s.store.get_project(s.request['projectId'], user_id=s.user_id))
    source = asyncio.run(s.store.create_session(
        connector_id=project.connectorId, project_id=project.id, user_id=s.user_id,
        runtime='codex', runtime_id='codex', external_session_id='fanout-source',
        title='Original task', cwd=project.workspacePath, session_id='sess_fanout_source', takeover=True,
    ))
    original = asyncio.run(s.store.save_user_uploaded_file(session_id=source.id, user_id=s.user_id, name='original.txt', data=b'original', media_type='text/plain'))
    extra = asyncio.run(s.store.save_user_uploaded_file(session_id=source.id, user_id=s.user_id, name='extra.txt', data=b'extra', media_type='text/plain'))
    asyncio.run(s.store.upsert_timeline_item(session_id=source.id, item=TimelineItemIn(
        id='fanout-original', sessionId=source.id, type='message', status='done', role='user',
        content={'text': 'Original task', 'attachments': [{'fileId': original['fileId']}]},
        source={'runtime': 'codex'}, orderSeq=1, contentHash='fanout-original',
    )))
    count = len(s.client.get('/projects', headers=s.headers).json()['projects'])
    created_ids = []
    for runtime in ['codex', 'claude', 'dsh']:
        body = {'operationId': f'fanout-forward-{runtime}', 'slot': 0, 'mode': 'continue',
                'target': {'runtime': runtime, 'runtimeId': runtime}, 'instructions': 'Use both attachments',
                'attachments': [{'fileId': extra['fileId']}]}
        response = s.client.post(f'/api/v2/task-groups/from-session/{source.id}/handoffs', headers=s.headers, json=body)
        assert response.status_code == 200, response.text
        group = response.json()
        assert group['projectId'] == project.id
        assert 'contentBase64' not in response.text
        assert {a['name'] for a in group['request']['attachments']} == {'original.txt', 'extra.txt'}
        first = asyncio.run(s.svc.start(group['id'], 0, user_id=s.user_id))
        second = asyncio.run(s.svc.start(group['id'], 0, user_id=s.user_id))
        target_id = first['candidates'][0]['sessionId']
        assert target_id == second['candidates'][0]['sessionId']
        created_ids.append(target_id)
        target = asyncio.run(s.store.get_session(target_id, user_id=s.user_id))
        assert target.projectId == project.id
        assert {a.name for a in s.runs.calls[-1].attachments} == {'original.txt', 'extra.txt'}
        assert 'Original task' in s.runs.calls[-1].content
    assert len(set(created_ids)) == 3 and len(s.runs.calls) == 3
    assert len(s.client.get('/projects', headers=s.headers).json()['projects']) == count
