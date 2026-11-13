"""Explicit, receipted cleanup of Connector-owned data and confirmed project roots."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from connector.core.fork_profile import fork_enabled, share_runtime_path, system_home
from connector.core.json_kv import JsonKeyValueStore
from connector.paths import connector_data_dir


class HistoryCleanup:
    def __init__(self, connector_id, resolve_runtime, *, kv=None, data_dir=None, home=None, forget_session=None):
        self.connector_id = connector_id
        self.resolve_runtime = resolve_runtime
        self._kv = kv
        self._data_dir = Path(data_dir) if data_dir else None
        self.home = Path(home) if home else system_home()
        self.lock = asyncio.Lock()
        self.forget_session = forget_session

    @property
    def data_dir(self):
        if self._data_dir is None:
            self._data_dir = connector_data_dir()
        return self._data_dir

    @property
    def kv(self):
        if self._kv is None:
            self._kv = JsonKeyValueStore.default()
        return self._kv

    def _path(self, value):
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError("invalid_cleanup_path")
        p = Path(value)
        if not p.is_absolute() or ".." in p.parts:
            raise ValueError("invalid_cleanup_path")
        if p.is_symlink() or p.is_junction():
            raise ValueError("cleanup_symlink_refused")
        # Permit stable aliases in parent directories; proof and deletion use the canonical target.
        p = p.resolve()
        protected = [self.home.resolve(), self.data_dir.resolve(), Path.cwd().resolve()]
        sensitive = [Path(sys.prefix).resolve(), self.data_dir.resolve() / "native"]
        sensitive.extend(self.home / name for name in (".ssh", ".config", ".claude", ".codex", ".dsh"))
        sensitive.extend(self.data_dir / name for name in ("connector.json", "connector-kv.json"))
        if os.name != "nt":
            sensitive.extend(Path(value) for value in ("/etc", "/usr", "/bin", "/sbin", "/boot", "/dev", "/proc", "/sys"))
        sensitive = [q.resolve() for q in sensitive]
        if p == Path(p.anchor) or any(q == p or q.is_relative_to(p) for q in protected):
            raise ValueError("protected_cleanup_path")
        if any(q == p or q.is_relative_to(p) or p.is_relative_to(q) for q in sensitive):
            raise ValueError("protected_cleanup_path")
        return p

    def _validate(self, request):
        if request.get("connectorId") != self.connector_id:
            raise ValueError("cleanup_connector_mismatch")
        operation = request.get("operationId", "")
        if not isinstance(operation, str) or not re.fullmatch(r"[a-f0-9]{32}", operation):
            raise ValueError("invalid_cleanup_operation")
        sessions = request.get("sessions")
        if not isinstance(sessions, list):
            raise TypeError("invalid_cleanup_sessions")
        for session in sessions:
            if not isinstance(session, dict) or not isinstance(session.get("sessionId"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", session["sessionId"]):
                raise ValueError("invalid_cleanup_session_id")
        if not isinstance(request.get("protectedPaths", []), list) or any(
            not isinstance(value, str) or not Path(value).is_absolute()
            for value in request.get("protectedPaths", [])
        ):
            raise ValueError("invalid_cleanup_protected_paths")
        for session in sessions:
            for name in ("cwd", "runtimeId", "runtime", "externalSessionId", "projectPath"):
                if session.get(name) is not None and not isinstance(session[name], str):
                    raise TypeError("invalid_cleanup_session")
            if session.get("projectPath") and (
                not Path(session["projectPath"]).is_absolute() or ".." in Path(session["projectPath"]).parts
            ):
                raise ValueError("invalid_cleanup_path")
        return operation, hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()

    async def prepare(self, request):
        operation, digest = self._validate(request)
        async with self.lock:
            key = "history-cleanup/" + operation
            previous = self.kv.get(key)
            if previous:
                if previous["digest"] != digest:
                    raise ValueError("cleanup_operation_changed")
                return {"prepared": True, "receipt": previous["receipt"]}
            directories = []
            if request.get("projectPath"):
                p = self._path(request["projectPath"])
                for other in request.get("protectedPaths", []):
                    q = Path(other).resolve()
                    if q == p or q.is_relative_to(p) or p.is_relative_to(q):
                        raise ValueError("cleanup_shared_project_path")
                directories.append(p)
            for session in request["sessions"]:
                directories.append(self._path(str(self.data_dir / "attachments" / session["sessionId"])))
                if session.get("projectPath"):
                    root = Path(session["projectPath"]).resolve()
                    private = root / ".agents-anywhere" / "sessions" / session["sessionId"]
                    for part in (private, private.parent, private.parent.parent):
                        if part.is_symlink() or part.is_junction():
                            raise ValueError("cleanup_symlink_refused")
                    directories.append(self._path(str(private)))
                # Session deletion never removes the shared project directory.
                cwd = Path(session["cwd"]).resolve() if session.get("cwd") else None
                conversation_root = self.data_dir.resolve() / "conversations"
                if cwd and cwd.is_relative_to(conversation_root) and cwd != conversation_root:
                    shared = [Path(value).resolve() for value in request.get("protectedPaths", [])]
                    if not any(q == cwd or q.is_relative_to(cwd) or cwd.is_relative_to(q) for q in shared):
                        directories.append(self._path(str(cwd)))
                if session.get("externalSessionId"):
                    runtime = self.resolve_runtime(session)
                    prepare = getattr(runtime, "prepare_history_deletion", None)
                    if not callable(prepare):
                        raise ValueError("native_history_deletion_unsupported")
                    await prepare(session)
            proof = []
            for p in dict.fromkeys(directories):
                exists = p.exists()
                if exists:
                    if not p.is_dir():
                        raise ValueError("cleanup_expected_directory")
                    if not os.access(p.parent, os.W_OK | os.X_OK):
                        raise PermissionError("cleanup_permission_denied")
                    for directory, _, _ in os.walk(p, followlinks=False):
                        if not os.access(directory, os.W_OK | os.X_OK):
                            raise PermissionError("cleanup_permission_denied")
                stat = p.stat() if exists else None
                proof.append({"path": str(p), "identity": [stat.st_dev, stat.st_ino] if stat else None})
            receipt = uuid4().hex
            self.kv.set(key, {"digest": digest, "receipt": receipt, "directories": proof, "done": False, "nativeDone": []})
            return {"prepared": True, "receipt": receipt}

    async def project_directory(self, action, request):
        operation = request.get("operationId", "")
        name = request.get("name", "")
        if request.get("connectorId") != self.connector_id or not re.fullmatch(r"[a-f0-9]{64}", operation):
            raise ValueError("invalid_project_directory_request")
        if not isinstance(name, str) or name in {"", ".", ".."} or any(c in name for c in '/\\\0<>:"|?*') or name.endswith((".", " ")) or any(ord(c) < 32 for c in name):
            raise ValueError("invalid_project_directory_name")
        if name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            raise ValueError("invalid_project_directory_name")
        parent = Path(request["parentPath"])
        if not parent.is_absolute() or not parent.is_dir() or ".." in parent.parts:
            raise ValueError("invalid_project_parent_directory")
        path = self._path(str(parent.resolve() / name))
        key = "project-directory/" + operation
        async with self.lock:
            state = self.kv.get(key)
            if state and state["path"] != str(path):
                raise ValueError("project_directory_request_changed")
            if action == "prepare":
                if state is None:
                    path.mkdir(mode=0o700)  # Never adopt a pre-existing folder as disposable project data.
                    stat = path.stat()
                    state = {"path": str(path), "identity": [stat.st_dev, stat.st_ino], "receipt": uuid4().hex}
                    try:
                        if fork_enabled() and os.environ.get("AA_FORK_RUNTIME_BROKER") == "1":
                            # Only the new project is shared; ancestors receive traversal, never read access.
                            for runtime in ("codex", "claude", "dsh"):
                                for parent in path.parents:
                                    if parent.stat().st_uid != os.getuid():
                                        break
                                    share_runtime_path(parent, "--x", runtime=runtime)
                                share_runtime_path(path, "rwx", runtime=runtime, inherit=True)
                        self.kv.set(key, state)
                    except Exception:
                        path.rmdir()
                        raise
                else:
                    stat = path.stat()
                    if state["identity"] != [stat.st_dev, stat.st_ino]:
                        raise ValueError("project_directory_replaced")
                return {"path": str(path), "receipt": state["receipt"]}
            if action not in {"cancel", "release"}:
                raise ValueError("unknown_project_directory_action")
            if state is None:
                return {"released": True}
            if state["receipt"] != request.get("receipt"):
                raise ValueError("project_directory_receipt_mismatch")
            if action == "cancel" and path.exists():
                stat = path.stat()
                if state["identity"] != [stat.st_dev, stat.st_ino]:
                    raise ValueError("project_directory_replaced")
                path.rmdir()  # Cancellation cannot remove user files added after preparation.
            self.kv.delete(key)
            return {"released": True}

    async def commit(self, plan):
        request = plan.get("request", {})
        operation, digest = self._validate(request)
        async with self.lock:
            key = "history-cleanup/" + operation
            state = self.kv.get(key)
            if not state or state["digest"] != digest or state["receipt"] != plan.get("receipt"):
                raise ValueError("cleanup_receipt_mismatch")
            if state["done"]:
                return {"complete": True}
            # Validate every original directory before the first destructive action.
            for item in state["directories"]:
                p = self._path(item["path"])
                if item["identity"] is not None and p.exists():
                    stat = p.stat()
                    if item["identity"] != [stat.st_dev, stat.st_ino]:
                        raise ValueError("cleanup_directory_replaced")
            for session in request["sessions"]:
                sid = session["sessionId"]
                if session.get("externalSessionId") and sid not in state["nativeDone"]:
                    await self.resolve_runtime(session).delete_session_history(session)
                    state["nativeDone"].append(sid)
                    self.kv.set(key, state)
            if self.forget_session is not None:
                for session in request["sessions"]:
                    await self.forget_session(session)
            for item in state["directories"]:
                if item["identity"] is None:
                    continue  # A directory created after confirmation is never part of this deletion.
                p = self._path(item["path"])
                if p.exists():
                    stat = p.stat()
                    if item["identity"] != [stat.st_dev, stat.st_ino]:
                        raise ValueError("cleanup_directory_replaced")
                    await asyncio.to_thread(shutil.rmtree, p)
            state.update(done=True, directories=[], nativeDone=[])
            self.kv.set(key, state)
            return {"complete": True}

    async def release(self, plan, *, cancel=False):
        operation, digest = self._validate(plan.get("request", {}))
        async with self.lock:
            key = "history-cleanup/" + operation
            state = self.kv.get(key)
            if state is None:
                return {"released": True}
            if state["digest"] != digest or state["receipt"] != plan.get("receipt"):
                raise ValueError("cleanup_receipt_mismatch")
            if not cancel and not state["done"]:
                raise ValueError("cleanup_not_complete")
            self.kv.delete(key)
            return {"released": True}
