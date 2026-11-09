"""Explicit Fork isolation; never migrate or copy another profile's credentials."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROFILE_ENV = "AA_CONNECTOR_PROFILE"
PROTECTED_PROFILE_ENV = frozenset(
    {
        PROFILE_ENV,
        "HOME",
        "USERPROFILE",
        "CODEX_HOME",
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_SECURESTORAGE_CONFIG_DIR",
    }
)


def system_home() -> Path:
    if sys.platform != "win32":
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    return Path.home()


def fork_enabled() -> bool:
    value = os.environ.get(PROFILE_ENV, "")
    if value not in {"", "fork"}:
        raise RuntimeError("Unknown Connector profile")
    return value == "fork"


def fork_root(home: Path | None = None) -> Path:
    return (home or system_home()) / ".agents-anywhere-fork"


def native_environment(home: Path | None = None) -> dict[str, str]:
    root = fork_root(home) / "native"
    return {
        PROFILE_ENV: "fork",
        "CODEX_HOME": str(root / "codex"),
        "CLAUDE_CONFIG_DIR": str(root / "claude"),
        "CLAUDE_SECURESTORAGE_CONFIG_DIR": str(root / "claude"),
    }


def validate_fork_environment(home: Path | None = None) -> None:
    expected = native_environment(home)
    for key, value in expected.items():
        if os.environ.get(key) != value:
            raise RuntimeError(
                "Fork requires its isolated native configuration directories"
            )
    root = fork_root(home)
    for path in (root, root / "native", root / "native/codex", root / "native/claude"):
        if path.resolve() != path.absolute():
            raise RuntimeError(
                "Fork native configuration cannot use links or junctions"
            )


def prepare_native_profile(home: Path | None = None) -> dict[str, str]:
    environment = native_environment(home)
    os.environ.update(environment)
    validate_fork_environment(home)
    for path in (fork_root(home), fork_root(home) / "native"):
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    for name in ("CODEX_HOME", "CLAUDE_CONFIG_DIR"):
        Path(environment[name]).mkdir(parents=True, mode=0o700, exist_ok=True)
    return environment
