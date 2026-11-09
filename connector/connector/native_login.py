"""Interactive native OAuth stays on the work device, outside captured logs."""

from __future__ import annotations

import os
import subprocess

from connector.core.fork_profile import fork_root, prepare_native_profile
from connector.native_cli import claude_command, codex_command


def login(runtime: str) -> int:
    prepare_native_profile()
    # Native subscription login must not inherit an API-key authentication mode.
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        os.environ.pop(key, None)
    if runtime == "codex":
        command, environment = codex_command(["login"])
    elif runtime == "claude":
        command, environment = claude_command(["auth", "login"]), dict(os.environ)
    else:
        raise ValueError("Unsupported native login")
    print(
        "Log in to the isolated Agents Anywhere Fork profile in your browser. Do not share the login code."
    )
    return subprocess.run(
        command, env=environment, cwd=fork_root(), check=False
    ).returncode
