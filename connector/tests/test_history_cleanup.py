from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from connector.core.json_kv import JsonKeyValueStore
from connector.server.history_cleanup import HistoryCleanup


@pytest.fixture
def fixture(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    data = home / ".agents-anywhere-fork"; data.mkdir()
    native = SimpleNamespace(prepare_history_deletion=AsyncMock(), delete_session_history=AsyncMock())
    cleanup = HistoryCleanup("conn", lambda _: native, kv=JsonKeyValueStore(data / "kv.json"), data_dir=data, home=home)
    project = tmp_path / "project"; project.mkdir()
    return cleanup, native, project


def request(**values):
    return {"operationId": "a" * 32, "connectorId": "conn", "sessions": [], "projectPath": None, "protectedPaths": [], **values}


@pytest.mark.anyio
async def test_project_receipt_survives_restart_and_retry_preserves_new_files(fixture):
    worker, _, project = fixture
    (project / "source").write_text("work")
    body = request(projectPath=str(project)); receipt = await worker.prepare(body)
    assert project.exists()
    worker = HistoryCleanup("conn", lambda _: None, kv=worker.kv, data_dir=worker.data_dir, home=worker.home)
    plan = {"request": body, "receipt": receipt["receipt"]}
    assert await worker.commit(plan) == {"complete": True}
    assert not project.exists()
    project.mkdir(); (project / "new").write_text("unrelated new data")
    await worker.commit(plan)
    assert (project / "new").exists()


@pytest.mark.anyio
async def test_replaced_directory_blocks_native_deletion_too(fixture):
    worker, native, project = fixture
    body = request(projectPath=str(project), sessions=[{"sessionId": "s", "externalSessionId": "n"}])
    receipt = await worker.prepare(body)
    project.rename(project.with_name("original")); project.mkdir(); (project / "new").touch()
    with pytest.raises(ValueError, match="replaced"):
        await worker.commit({"request": body, "receipt": receipt["receipt"]})
    native.delete_session_history.assert_not_awaited()
    assert (project / "new").exists()


@pytest.mark.anyio
async def test_session_cleanup_keeps_shared_project_and_retries_native_partial_failure(fixture):
    worker, native, project = fixture
    (project / "keep").write_text("shared")
    attachment = worker.data_dir / "attachments" / "a"; attachment.mkdir(parents=True); (attachment / "file").touch()
    body = request(sessions=[{"sessionId": sid, "externalSessionId": sid, "cwd": str(project)} for sid in ["a", "b"]], protectedPaths=[str(project)])
    receipt = await worker.prepare(body)
    plan = {"request": body, "receipt": receipt["receipt"]}
    native.delete_session_history.side_effect = [None, OSError("locked"), None]
    with pytest.raises(OSError): await worker.commit(plan)
    assert attachment.exists()
    await worker.commit(plan)
    assert [call.args[0]["sessionId"] for call in native.delete_session_history.await_args_list] == ["a", "b", "b"]
    assert not attachment.exists() and (project / "keep").exists()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["self", "child", "parent"])
async def test_shared_workspaces_are_refused(fixture, kind):
    worker, _, project = fixture
    other = project if kind == "self" else project / "child" if kind == "child" else project.parent
    with pytest.raises(ValueError, match="shared"):
        await worker.prepare(request(projectPath=str(project), protectedPaths=[str(other)]))
    assert project.exists()


@pytest.mark.anyio
async def test_sensitive_paths_symlinks_and_forged_receipts_are_refused(fixture):
    worker, _, project = fixture
    for path in [worker.home, worker.data_dir, worker.home / ".ssh", worker.data_dir / "native/claude", Path(project.anchor)]:
        with pytest.raises(ValueError): await worker.prepare(request(projectPath=str(path)))
    link = project.with_name("link"); link.symlink_to(project, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"): await worker.prepare(request(projectPath=str(link)))
    body = request(projectPath=str(project)); await worker.prepare(body)
    with pytest.raises(ValueError, match="receipt"): await worker.commit({"request": body, "receipt": "forged"})
    with pytest.raises(ValueError): await worker.prepare({**body, "connectorId": "another"})
    assert project.exists()


@pytest.mark.anyio
async def test_cancellation_clears_receipt_and_late_commit_cannot_delete(fixture):
    worker, native, project = fixture
    body = request(projectPath=str(project))
    receipt = await worker.prepare(body)
    plan = {"request": body, "receipt": receipt["receipt"]}
    assert await worker.release(plan, cancel=True) == {"released": True}
    assert worker.kv.get("history-cleanup/" + body["operationId"]) is None
    with pytest.raises(ValueError, match="receipt"):
        await worker.commit(plan)
    assert project.exists()
    native.delete_session_history.assert_not_awaited()


@pytest.mark.anyio
async def test_completed_receipt_can_be_released_repeatedly(fixture):
    worker, _, project = fixture
    body = request(projectPath=str(project))
    receipt = await worker.prepare(body)
    plan = {"request": body, "receipt": receipt["receipt"]}
    with pytest.raises(ValueError, match="not_complete"):
        await worker.release(plan)
    await worker.commit(plan)
    await worker.release(plan)
    assert await worker.release(plan) == {"released": True}
    assert worker.kv.get("history-cleanup/" + body["operationId"]) is None


@pytest.mark.anyio
async def test_parent_alias_is_canonicalized_and_shared_alias_still_blocks(fixture):
    worker, _, project = fixture
    alias = project.parent / "parent-alias"
    alias.symlink_to(project.parent, target_is_directory=True)
    through_alias = alias / project.name
    with pytest.raises(ValueError, match="shared"):
        await worker.prepare(request(projectPath=str(through_alias), protectedPaths=[str(project)]))
    body = request(projectPath=str(through_alias))
    receipt = await worker.prepare(body)
    alias.unlink()
    await worker.commit({"request": body, "receipt": receipt["receipt"]})
    assert not project.exists()


@pytest.mark.anyio
async def test_replacement_while_native_cleanup_awaits_is_not_deleted(fixture):
    worker, native, project = fixture
    body = request(projectPath=str(project), sessions=[{"sessionId": "s", "externalSessionId": "n"}])
    receipt = await worker.prepare(body)
    async def replace(_):
        project.rename(project.with_name("original")); project.mkdir()
        (project / "new").touch()
    native.delete_session_history.side_effect = replace
    with pytest.raises(ValueError, match="replaced"):
        await worker.commit({"request": body, "receipt": receipt["receipt"]})
    assert (project / "new").exists()
