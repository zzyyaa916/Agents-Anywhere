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


def test_two_real_processes_keep_separate_leases_and_reject_duplicates(tmp_path):
    import subprocess
    import sys

    script = tmp_path / "probe/connector/cli.py"
    script.parent.mkdir(parents=True)
    script.write_text("""
import os, sys
from pathlib import Path
from connector.core import fork_profile, runtime_owner
home = Path(os.environ["AA_TEST_HOME"])
fork_profile.system_home = runtime_owner.system_home = lambda: home
if fork_profile.fork_enabled():
    fork_profile.prepare_native_profile()
lease = runtime_owner.RuntimeLease()
try:
    lease.claim()
except runtime_owner.ConnectorAlreadyRunningError:
    sys.exit(2)
print("ready", flush=True)
try:
    sys.stdin.readline()
finally:
    lease.release()
""")
    base = {**os.environ, "AA_TEST_HOME": str(tmp_path / "home")}
    base.pop("AA_CONNECTOR_PROFILE", None)
    children = []
    try:
        for profile in (None, "fork"):
            environment = dict(base)
            if profile:
                environment["AA_CONNECTOR_PROFILE"] = profile
            child = subprocess.Popen(
                [sys.executable, str(script)],
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            children.append(child)
            assert child.stdout.readline().strip() == "ready"
            duplicate = subprocess.run(
                [sys.executable, str(script)],
                env=environment,
                input="",
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert duplicate.returncode == 2, duplicate.stderr
        assert all(child.poll() is None for child in children)
    finally:
        for child in children:
            child.stdin.close()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            child.stdout.close()
            child.stderr.close()


def test_fork_disables_desktop_ipc_even_for_previous_saved_values(monkeypatch):
    import asyncio

    from connector.runtimes.codex import provider
    from connector.runtimes.codex.sdk.binary import (
        CodexRuntimeBinarySelection,
        LoginShellPathResult,
    )

    home = activate(monkeypatch)
    monkeypatch.setattr(
        provider,
        "codex_runtime_environment",
        lambda *a, **kw: (dict(os.environ), LoginShellPathResult(None, None)),
    )
    monkeypatch.setattr(
        provider,
        "select_codex_runtime_binary",
        lambda *a, **kw: CodexRuntimeBinarySelection(
            "sdk_bundled", "sdk_bundled", None, None, None
        ),
    )
    instance = provider.CodexProvider(sdk_checker=lambda: {"available": True})
    config = asyncio.run(
        instance.validate_config({"ipcEnabled": True, "ipcDeeplinkHandoff": True})
    )
    assert config.values["ipcEnabled"] is False
    assert config.values["ipcDeeplinkHandoff"] is False
    assert config.values["codexHome"] == str(
        home / ".agents-anywhere-fork/native/codex"
    )
    assert config.values["useSystemCodex"] is False


@pytest.mark.parametrize("runtime", ["codex", "claude", "dsh"])
def test_runtime_path_acl_is_fixed_user_and_not_world_access(tmp_path, monkeypatch, runtime):
    import subprocess
    path = tmp_path / "workspace"
    path.mkdir()
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: calls.append(args))
    monkeypatch.delenv("AA_CONNECTOR_PROFILE", raising=False)
    fork_profile.share_runtime_path(path, "rwx", runtime=runtime, inherit=True)
    assert not calls
    monkeypatch.setenv("AA_CONNECTOR_PROFILE", "fork")
    monkeypatch.setenv("AA_FORK_RUNTIME_BROKER", "1")
    fork_profile.share_runtime_path(path, "rwx", runtime=runtime, inherit=True)
    assert calls == [["/usr/bin/setfacl", "-m", f"u:ai-{runtime}:rwx,d:u:ai-{runtime}:rwx,d:u:{os.getuid()}:rwx", str(path)]]
    link = tmp_path / "link"
    link.symlink_to(path, target_is_directory=True)
    with pytest.raises(ValueError, match="without links"):
        fork_profile.share_runtime_path(link, "rwx")
