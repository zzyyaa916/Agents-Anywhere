import concurrent.futures
from pathlib import Path

import pytest
from connector.local import worktrees as wt


@pytest.fixture
def repo(tmp_path):
    wt.git(tmp_path, "init")
    wt.git(tmp_path, "config", "user.name", "Test")
    wt.git(tmp_path, "config", "user.email", "test@localhost")
    (tmp_path / "file.txt").write_text("baseline\n")
    wt.git(tmp_path, "add", ".")
    wt.git(tmp_path, "commit", "-m", "baseline")
    return tmp_path


def params(repo, group="a" * 40, count=3):
    return {"root": str(repo), "groupId": group, "count": count}


@pytest.mark.parametrize("count", [1, 2, 3])
def test_any_count_from_one_to_three(repo, count):
    result = wt.prepare(params(repo, count=count))
    assert len(result["paths"]) == len(set(result["paths"])) == count


@pytest.mark.parametrize("count", [0, 4, -1, True, "2"])
def test_invalid_counts_do_not_create_worktrees(repo, count):
    with pytest.raises(ValueError, match="one to three"):
        wt.prepare(params(repo, count=count))


def test_three_worktrees_share_baseline_and_concurrent_retries_are_idempotent(repo):
    request = params(repo)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(wt.prepare, [request] * 3))
    assert results[0] == results[1] == results[2]
    result = results[0]
    assert len(set(result["paths"])) == 3
    for path in result["paths"]:
        assert (
            wt.git(Path(path), "rev-parse", "HEAD").decode().strip() == result["base"]
        )
    (Path(result["paths"][0]) / "file.txt").write_text("candidate\n")
    assert (repo / "file.txt").read_text() == "baseline\n"
    assert (Path(result["paths"][1]) / "file.txt").read_text() == "baseline\n"
    (repo / "file.txt").write_text("later source changes\n")
    assert wt.prepare(request) == result


def test_handoff_captures_committed_uncommitted_new_binary_and_deletions_without_staging(
    repo,
):
    prepared = wt.prepare(params(repo))
    path = Path(prepared["paths"][0])
    (path / "committed.txt").write_text("committed\n")
    wt.git(path, "add", ".")
    wt.git(path, "commit", "-m", "candidate commit")
    (path / "file.txt").unlink()
    (path / "new.txt").write_text("not staged\n")
    (path / "new.bin").write_bytes(b"\x00\xff\x00\x01")
    before = wt.git(path, "diff", "--cached")
    head = wt.git(path, "rev-parse", "HEAD")
    result = wt.diff({**params(repo), "slot": 0})
    assert (
        "new.txt" in result["diff"]
        and "new.bin" in result["diff"]
        and "file.txt" in result["diff"]
    )
    request = {**params(repo), "slot": 0, "targetGroupId": "b" * 40}
    handoff = wt.handoff(request)
    target = Path(handoff["paths"][0])
    assert not (target / "file.txt").exists()
    assert (target / "new.txt").read_text() == "not staged\n"
    assert (target / "committed.txt").read_text() == "committed\n"
    assert (target / "new.bin").read_bytes() == b"\x00\xff\x00\x01"
    assert wt.git(path, "diff", "--cached") == before
    assert wt.git(path, "rev-parse", "HEAD") == head
    (path / "new.txt").write_text("changed after handoff")
    assert wt.handoff(request) == handoff
    assert (target / "new.txt").read_text() == "not staged\n"


def test_rejects_dirty_baseline_invalid_ids_and_links(repo, tmp_path):
    (repo / "file.txt").write_text("dirty\n")
    with pytest.raises(ValueError, match="Commit or save"):
        wt.prepare(params(repo))
    with pytest.raises(ValueError, match="identity"):
        wt.prepare(params(repo, group="../outside"))
    wt.git(repo, "checkout", "--", "file.txt")
    managed = repo / ".git" / "aa-fork-worktrees"
    outside = repo / "outside"
    outside.mkdir()
    if managed.exists():
        # Only empty test-created directories are removed.
        (managed / ("a" * 40) / "operation.lock").unlink()
        (managed / ("a" * 40)).rmdir()
        managed.rmdir()
    managed.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        wt.prepare(params(repo))
    assert not (outside / ("a" * 40)).exists()


def test_diff_limit_is_explicit_and_original_tree_is_untouched(repo):
    result = wt.prepare(params(repo, count=1))
    (Path(result["paths"][0]) / "large.txt").write_text("large line\n" * 60_000)
    with pytest.raises(ValueError, match="512 KiB"):
        wt.diff({**params(repo, count=1), "slot": 0})
    assert not (repo / "large.txt").exists()


def test_plain_conversation_needs_no_git_or_project_files(tmp_path, monkeypatch):
    root = tmp_path / "ordinary"
    root.mkdir()
    (root / "private.txt").write_text("must not be copied")
    data = tmp_path / "state"
    data.mkdir()
    monkeypatch.setenv("AGENT_CONNECTOR_DATA_DIR", str(data))
    monkeypatch.setattr(
        wt,
        "git",
        lambda *args, **kwargs: pytest.fail("Git used for plain conversation"),
    )
    request = params(root, count=2)
    first = wt.prepare(request)
    assert first["base"] == "conversation"
    assert wt.prepare(request) == first
    assert len(set(first["paths"])) == 2
    for path in first["paths"]:
        assert Path(path).is_relative_to(data)
        assert list(Path(path).iterdir()) == []
    assert wt.diff({**request, "slot": 0})["diff"] == ""
    handoff_request = {**request, "slot": 0, "targetGroupId": "b" * 40}
    target = wt.handoff(handoff_request)
    assert target == wt.handoff(handoff_request)
    assert target["base"] == target["originalBase"] == "conversation"
    assert list(Path(target["paths"][0]).iterdir()) == []
    assert list(root.iterdir()) == [root / "private.txt"]


def test_plain_conversation_rejects_managed_symlink(tmp_path, monkeypatch):
    root = tmp_path / "ordinary"
    root.mkdir()
    data = tmp_path / "state"
    data.mkdir()
    monkeypatch.setenv("AGENT_CONNECTOR_DATA_DIR", str(data))
    (data / "conversations").symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        wt.prepare(params(root))
    assert not list(root.iterdir())


def test_dsh_only_receives_managed_conversation_access(tmp_path, monkeypatch):
    from connector.core import fork_profile
    state = tmp_path / "state"
    root = tmp_path / "ordinary"
    state.mkdir()
    root.mkdir()
    monkeypatch.setenv("AGENT_CONNECTOR_DATA_DIR", str(state))
    monkeypatch.setenv("AA_CONNECTOR_PROFILE", "fork")
    monkeypatch.setenv("AA_FORK_RUNTIME_BROKER", "1")
    calls = []
    monkeypatch.setattr(fork_profile, "share_runtime_path", lambda p, permission, **kw: calls.append((p, permission, kw)))
    path = Path(wt.prepare(params(root, count=2))["paths"][1])
    wt.prepare_runtime_workspace(str(path), "dsh")
    assert calls[-1] == (path, "rwx", {"runtime": "dsh", "inherit": True})
    assert all(permission == "--x" and p in path.parents for p, permission, _ in calls[:-1])
    assert not any(p == path.parent / "0" or p == state / "native" for p, _, _ in calls)
    calls.clear()
    wt.prepare_runtime_workspace(str(root), "dsh")
    assert not calls


@pytest.mark.parametrize("runtime", ["codex", "claude", "dsh"])
def test_native_runtime_workspace_access_precedes_model_dispatch(monkeypatch, runtime):
    import asyncio
    from types import SimpleNamespace
    from connector.runtime_protocol import RuntimeOperationResult
    from connector.server.runtime_turn_rpc import dispatch_session_create
    calls = []
    monkeypatch.setattr(wt, "prepare_runtime_workspace", lambda cwd, kind: calls.append(("access", cwd, kind)))
    async def create(*args, **kwargs):
        calls.append(("model",))
        return RuntimeOperationResult(ok=True)
    target = SimpleNamespace(identity=SimpleNamespace(runtime=runtime), create_and_start_session=create)
    asyncio.run(dispatch_session_create(target, {"sessionId": "sess_test", "content": "test", "cwd": "/managed/workspace"}))
    assert calls == [("access", "/managed/workspace", runtime), ("model",)]


def test_adopt_dirty_repository_snapshots_without_changing_source(repo):
    request = params(repo, count=1)
    original_head = wt.git(repo, "rev-parse", "HEAD")
    (repo / "file.txt").write_text("dirty result")
    (repo / "new.txt").write_text("new result")
    original_index = wt.git(repo, "diff", "--cached")
    assert wt.adopt(request) == wt.adopt(request)
    result = wt.handoff({**request, "slot": 0, "targetGroupId": "b" * 40})
    target = Path(result["paths"][0])
    assert (target / "file.txt").read_text() == "dirty result"
    assert (target / "new.txt").read_text() == "new result"
    assert wt.git(repo, "rev-parse", "HEAD") == original_head
    assert wt.git(repo, "diff", "--cached") == original_index
    assert (repo / "file.txt").read_text() == "dirty result"
