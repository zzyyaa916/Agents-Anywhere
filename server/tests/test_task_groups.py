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
