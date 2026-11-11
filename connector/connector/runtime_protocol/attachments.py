from __future__ import annotations

import re
from pathlib import Path

from connector.paths import connector_data_dir

ATTACHMENTS_ROOT_ENV = "AGENT_CONNECTOR_ATTACHMENTS_ROOT"
_SAFE_FILENAME_RE = re.compile(r"[^\w.\-+]+")


def attachments_root() -> Path:
    """Return the connector-local root used for runtime attachment copies."""
    import os

    configured = os.environ.get(ATTACHMENTS_ROOT_ENV)
    root = (
        Path(configured).expanduser()
        if configured
        else connector_data_dir() / "attachments"
    )
    return root.resolve(strict=False)


def session_attachments_dir(session_id: str) -> Path:
    session = _safe_filename(session_id) or "session"
    return attachments_root() / session


def attachment_target(session_id: str, file_id: str, original_name: str | None) -> Path:
    safe_file_id = _safe_filename(file_id) or "file"
    safe_name = _safe_filename(original_name or "") or safe_file_id
    return session_attachments_dir(session_id) / f"{safe_file_id}-{safe_name}"


def _safe_filename(name: str) -> str:
    """Reduce arbitrary user/server values to safe single path components."""
    name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    sanitized = _SAFE_FILENAME_RE.sub("_", name).strip("._") or ""
    return sanitized[:120]


def write_runtime_attachment(target: Path, content: bytes, runtime: str) -> None:
    """Grant only this runtime access to the materialized attachment, not account data."""
    import os

    from connector.core.fork_profile import fork_enabled, share_runtime_path

    shared = fork_enabled() and os.environ.get("AA_FORK_RUNTIME_BROKER") == "1"
    if shared and target.absolute() != target.resolve():
        raise ValueError("Runtime attachments cannot use links")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if shared:
        # Existing session directories can predate runtime sharing.
        for parent in target.parents:
            if parent.stat().st_uid != os.getuid():
                break
            share_runtime_path(parent, "--x", runtime=runtime)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        if shared:
            os.chmod(target, 0o600)
        stream.write(content)
    share_runtime_path(target, "r--", runtime=runtime)
