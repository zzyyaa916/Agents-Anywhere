"""Use the same native launch semantics for local login and read-only usage."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from connector.core.fork_profile import (
    broker_executable,
    fork_enabled,
    validate_fork_environment,
)
from connector.launch import launch_target
from connector.runtimes.codex.sdk.binary import (
    LoginShellPathResult,
    codex_launch_command,
    codex_runtime_environment,
    select_codex_runtime_binary,
)


def codex_command(
    args: list[str], executable: str | None = None
) -> tuple[list[str], dict[str, str]]:
    if fork_enabled():
        validate_fork_environment()
    if fork_enabled() and not executable:
        environment, shell_path = dict(os.environ), LoginShellPathResult(None, None)
    else:
        environment, shell_path = codex_runtime_environment(None)
    selection = select_codex_runtime_binary(
        "sdk_bundled" if fork_enabled() and not executable else "prefer_system",
        environment,
        shell_path,
        configured_path=executable,
    )
    candidate = selection.codex_bin
    if candidate is None:
        from codex_cli_bin import bundled_codex_path

        candidate = str(bundled_codex_path())
    return codex_launch_command(candidate, args, environment), environment


def claude_command(args: list[str], executable: str | None = None) -> list[str]:
    if fork_enabled():
        validate_fork_environment()
    executable = broker_executable("claude") or executable
    if executable is None:
        spec = importlib.util.find_spec("claude_agent_sdk")
        if spec and spec.origin:
            bundled = (
                Path(spec.origin).parent
                / "_bundled"
                / ("claude.exe" if sys.platform == "win32" else "claude")
            )
            if bundled.is_file():
                executable = str(bundled)
    if executable is None:
        from connector.runtimes.claude.discovery import claude_candidate_targets

        candidates = claude_candidate_targets()
        executable = next(
            (target.path for target in candidates if Path(target.path).is_file()), None
        )
    if executable is None:
        raise FileNotFoundError("Claude CLI is unavailable")
    return launch_target("account", executable).command(args)
