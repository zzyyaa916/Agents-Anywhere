"""Scoped Claude transcript deletion; usable by the fixed-identity broker without dependencies."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from uuid import UUID


def claude_history_paths(root: Path, session_id: str) -> list[Path]:
    if str(UUID(session_id)) != session_id:
        raise ValueError("invalid_native_session_id")
    root = root.absolute()
    if root.resolve() != root:
        raise ValueError("native_history_symlink")
    projects = root / "projects"
    paths = []
    if projects.exists():
        if projects.is_symlink():
            raise ValueError("native_history_symlink")
        for project in projects.iterdir():
            if project.is_symlink():
                raise ValueError("native_history_symlink")
            if not project.is_dir():
                continue
            # Enumerating explicitly makes unreadable projects fail instead of reporting a false absence.
            entries = {p.name: p for p in project.iterdir()}
            for name in (session_id + ".jsonl", session_id):
                if name in entries:
                    paths.append(entries[name])
    for directory, name in (("debug", session_id + ".txt"), ("file-history", session_id),
                            ("tasks", session_id), ("session-env", session_id), ("todos", session_id + ".json")):
        parent = root / directory
        if parent.is_symlink():
            raise ValueError("native_history_symlink")
        p = parent / name
        if p.exists() or p.is_symlink():
            paths.append(p)
    for p in paths:
        if p.is_symlink() or p.resolve() != p:
            raise ValueError("native_history_symlink")
        if not os.access(p.parent, os.W_OK | os.X_OK):
            raise PermissionError("native_history_permission_denied")
        if p.is_dir():
            for child in p.rglob("*"):
                if child.is_dir() and not child.is_symlink() and not os.access(child, os.W_OK | os.X_OK):
                    raise PermissionError("native_history_permission_denied")
    return paths


def cleanup_claude_history(root: Path, session_id: str, *, commit=False) -> dict:
    paths = claude_history_paths(root, session_id)
    if commit:
        for p in paths:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
        if claude_history_paths(root, session_id):
            raise OSError("native_history_cleanup_incomplete")
    return {"complete" if commit else "prepared": True}


if __name__ == "__main__":
    phase, session_id = sys.argv[1:]
    if phase not in {"prepare", "commit"}:
        raise SystemExit("invalid native cleanup phase")
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    print(json.dumps(cleanup_claude_history(root, session_id, commit=phase == "commit")))
