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
