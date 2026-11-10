"""Small Git-backed workspaces; native sessions remain owned by existing runtimes."""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ID = re.compile(r"[a-f0-9]{40}")
MAX_DIFF = 512_000


def git(root: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null" if os.name != "nt" else "core.hooksPath=NUL",
            *args,
        ],
        cwd=root,
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace")[:2000])
    return result.stdout


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Invalid task group identity")
    return value


def managed(root: str, group_id: str) -> tuple[Path, Path]:
    repo = Path(root).expanduser().resolve(strict=True)
    top = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != repo:
        raise ValueError("Select the Git repository root")
    common = Path(git(repo, "rev-parse", "--git-common-dir").decode().strip())
    common = (repo / common).resolve()
    directory = common / "aa-fork-worktrees" / identifier(group_id)
    for path in (directory.parent, directory):
        if path.is_symlink():
            raise ValueError("Managed workspaces cannot contain symbolic links")
        path.mkdir(exist_ok=True, mode=0o700)
    return repo, directory


@contextlib.contextmanager
def locked(directory: Path):
    path = directory / "operation.lock"
    if path.is_symlink():
        raise ValueError("Invalid workspace lock")
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.write(b"0")
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def save(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise ValueError("Invalid workspace metadata")
    descriptor, name = tempfile.mkstemp(prefix="manifest-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load(directory: Path) -> dict[str, Any]:
    path = directory / "manifest.json"
    if path.is_symlink():
        raise ValueError("Invalid workspace metadata")
    return json.loads(path.read_text())


def workspace(repo: Path, directory: Path, slot: int, base: str) -> Path:
    path = directory / str(slot)
    branch = f"aa-fork/{directory.name}/{slot}"
    if path.is_symlink():
        raise ValueError("Invalid workspace link")
    if not path.exists():
        git(repo, "worktree", "add", "-b", branch, str(path), base)
    actual = Path(git(path, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if (
        actual != path
        or git(path, "branch", "--show-current").decode().strip() != branch
    ):
        raise ValueError("Workspace identity conflict")
    return path


def prepare(params: dict[str, Any]) -> dict[str, Any]:
    repo, directory = managed(params["root"], params["groupId"])
    count = params["count"]
    if type(count) is not int or count not in (1, 3):
        raise ValueError("Choose one or three candidates")
    with locked(directory):
        if (directory / "manifest.json").exists():
            manifest = load(directory)
            if manifest["count"] != count:
                raise ValueError("Task group identity conflict")
        else:
            if git(repo, "status", "--porcelain"):
                raise ValueError(
                    "Commit or save repository changes before starting independent candidates"
                )
            base = git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
            manifest = {"base": base, "count": count}
            save(directory / "manifest.json", manifest)
        paths = [
            str(workspace(repo, directory, n, manifest["base"])) for n in range(count)
        ]
        return {"base": manifest["base"], "paths": paths}


def source(params: dict[str, Any]) -> tuple[Path, Path, dict[str, Any], Path]:
    repo, directory = managed(params["root"], params["groupId"])
    manifest = load(directory)
    slot = params["slot"]
    if type(slot) is not int or not 0 <= slot < manifest["count"]:
        raise ValueError("Invalid candidate")
    return repo, directory, manifest, workspace(repo, directory, slot, manifest["base"])


def snapshot(path: Path) -> str:
    # A private index includes new/binary files without staging or committing in the user's index.
    files = git(path, "ls-files", "-co", "--exclude-standard", "-z").split(b"\0")
    total = 0
    for name in set(files):
        if not name:
            continue
        file = path / os.fsdecode(name)
        if file.is_file() and not file.is_symlink():
            total += file.stat().st_size
        if total > 64 * 1024 * 1024:
            raise ValueError(
                "Snapshot exceeds 64 MiB; exclude generated files before handoff"
            )
    with tempfile.TemporaryDirectory(prefix="aa-index-") as temporary:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index")}
        git(path, "read-tree", "HEAD", env=env)
        git(path, "add", "-A", "--", ".", env=env)
        tree = git(path, "write-tree", env=env).decode().strip()
        head = git(path, "rev-parse", "HEAD").decode().strip()
        env.update(
            GIT_AUTHOR_NAME="Agents Anywhere Fork",
            GIT_AUTHOR_EMAIL="fork@localhost",
            GIT_COMMITTER_NAME="Agents Anywhere Fork",
            GIT_COMMITTER_EMAIL="fork@localhost",
        )
        return (
            git(
                path,
                "commit-tree",
                tree,
                "-p",
                head,
                "-m",
                "Fork candidate snapshot",
                env=env,
            )
            .decode()
            .strip()
        )


def diff(params: dict[str, Any]) -> dict[str, Any]:
    _, directory, manifest, path = source(params)
    with locked(directory):
        head = snapshot(path)
        data = git(
            path,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--stat",
            manifest["base"],
            head,
        )
        patch = git(
            path, "diff", "--no-ext-diff", "--no-textconv", manifest["base"], head
        )
        if len(patch) > MAX_DIFF:
            raise ValueError(
                "Diff exceeds 512 KiB; inspect this candidate in its session"
            )
        return {
            "base": manifest["base"],
            "head": head,
            "stat": data.decode(errors="replace"),
            "diff": patch.decode(errors="replace"),
        }


def handoff(params: dict[str, Any]) -> dict[str, Any]:
    repo, directory, manifest, path = source(params)
    target_id = identifier(params["targetGroupId"])
    if target_id == directory.name:
        raise ValueError("Handoff requires a new group")
    _, target = managed(str(repo), target_id)
    with locked(directory), locked(target):
        if (target / "manifest.json").exists():
            value = load(target)
            if value.get("source") != [directory.name, params["slot"]]:
                raise ValueError("Handoff identity conflict")
        else:
            value = {
                "base": snapshot(path),
                "count": 1,
                "source": [directory.name, params["slot"]],
                "originalBase": manifest["base"],
            }
            save(target / "manifest.json", value)
        destination = workspace(repo, target, 0, value["base"])
        return {
            "base": value["base"],
            "paths": [str(destination)],
            "originalBase": value["originalBase"],
        }
