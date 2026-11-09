import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from connector.core import fork_profile, runtime_owner
from connector.core.fork_profile import native_environment, prepare_native_profile
from connector.core.runtime_owner import (
    ConnectorAlreadyRunningError,
    RuntimeLease,
    read_state,
    runtime_path,
)
from connector.runtimes.claude import provider_config as claude_config
from connector.runtimes.codex import provider_config as codex_config


def activate(monkeypatch):
    home = runtime_owner.system_home()
    monkeypatch.setattr(fork_profile, "system_home", lambda: home)
    for key, value in native_environment(home).items():
        monkeypatch.setenv(key, value)
    return home


def test_independent_leases_preserve_official_history_and_block_fork_duplicates(
    monkeypatch,
):
    home = runtime_owner.system_home()
    official = RuntimeLease()
    official.claim()
    original = official.path.read_bytes()
    legacy = home / ".agentsanywhere/machine.json"
    legacy.parent.mkdir()
    legacy.write_text('{"version":1,"connectorIds":["official-only"]}')
    activate(monkeypatch)
    fork = RuntimeLease()
    assert fork.path != official.path
    fork.claim()
    try:
        assert official.path.read_bytes() == original
        assert legacy.exists()
        assert read_state(fork.path)["connectorIds"] == []
        with pytest.raises(ConnectorAlreadyRunningError):
            RuntimeLease().claim()
    finally:
        fork.release()
        official.release()


def test_profile_requires_both_native_directories_and_rejects_links(
    tmp_path, monkeypatch
):
    home = activate(monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    with pytest.raises(RuntimeError, match="isolated"):
        runtime_path()
    monkeypatch.setenv("CODEX_HOME", native_environment(home)["CODEX_HOME"])
    if os.name != "nt":
        root = home / ".agents-anywhere-fork"
        root.parent.mkdir(exist_ok=True)
        root.symlink_to(tmp_path, target_is_directory=True)
        with pytest.raises(RuntimeError, match="links"):
            runtime_path()


def test_profile_setup_does_not_read_or_copy_official_credentials(monkeypatch):
    home = activate(monkeypatch)
    original = home / ".codex/auth.json"
    original.parent.mkdir(parents=True)
    original.write_text("synthetic-do-not-copy")
    prepare_native_profile(home)
    assert original.read_text() == "synthetic-do-not-copy"
    assert not (Path(os.environ["CODEX_HOME"]) / "auth.json").exists()
    assert not (Path(os.environ["CLAUDE_CONFIG_DIR"]) / ".credentials.json").exists()
    assert runtime_path().parent == home / ".agents-anywhere-fork"


@pytest.mark.parametrize(
    "key",
    [
        "HOME",
        "USERPROFILE",
        "CODEX_HOME",
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_SECURESTORAGE_CONFIG_DIR",
        "AA_CONNECTOR_PROFILE",
    ],
)
def test_runtime_environment_cannot_override_profile(monkeypatch, key):
    activate(monkeypatch)
    for config in (codex_config, claude_config):
        with pytest.raises(Exception, match="managed"):
            config.merge_environment({key: "/other"})
    with pytest.raises(Exception, match="isolated"):
        codex_config.effective_codex_home("/other")


def test_native_launch_uses_bundled_fallback_and_windows_shims(monkeypatch):
    import codex_cli_bin
    import connector.native_cli as cli

    from connector import launch

    monkeypatch.setattr(
        cli, "codex_runtime_environment", lambda _: ({"PATH": ""}, None)
    )
    monkeypatch.setattr(
        cli,
        "select_codex_runtime_binary",
        lambda *a, **kw: SimpleNamespace(codex_bin=None),
    )
    monkeypatch.setattr(codex_cli_bin, "bundled_codex_path", lambda: Path("/sdk/codex"))
    monkeypatch.setattr(
        cli, "codex_launch_command", lambda exe, args, env: [exe, *args]
    )
    assert cli.codex_command(["app-server"])[0] == ["/sdk/codex", "app-server"]
    monkeypatch.setattr(launch, "_powershell_bin", lambda: "powershell.exe")
    monkeypatch.setattr(launch.sys, "platform", "win32")
    command = cli.claude_command(["--version"], "C:/Program Files/claude.cmd")
    assert command[-2] == "-Command"
    assert "'C:/Program Files/claude.cmd' '--version'" in command[-1]


@pytest.mark.parametrize("runtime", ["codex", "claude"])
def test_interactive_login_uses_private_environment_without_capture(
    runtime, monkeypatch
):
    from connector import native_login

    home = activate(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-do-not-forward")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-do-not-forward")
    monkeypatch.setattr(
        native_login, "codex_command", lambda args: (["codex", *args], dict(os.environ))
    )
    monkeypatch.setattr(native_login, "claude_command", lambda args: ["claude", *args])
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(native_login.subprocess, "run", run)
    assert native_login.login(runtime) == 0
    command, kwargs = calls[0]
    assert command == (
        ["codex", "login"] if runtime == "codex" else ["claude", "auth", "login"]
    )
    assert kwargs["cwd"] == home / ".agents-anywhere-fork"
    assert (
        "capture_output" not in kwargs
        and "stdout" not in kwargs
        and "stderr" not in kwargs
    )
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert kwargs["env"]["CODEX_HOME"] == str(
        home / ".agents-anywhere-fork/native/codex"
    )
