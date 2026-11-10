from pathlib import Path
from types import SimpleNamespace

import pytest
from connector.core import fork_profile
from connector.native_cli import claude_command, codex_command
from connector.runtimes.claude.sdk.client import build_sdk_options
from connector.runtimes.codex.sdk import binary
from test_fork_profile import activate


def broker(monkeypatch):
    activate(monkeypatch)
    monkeypatch.setenv('AA_FORK_RUNTIME_BROKER', '1')
    monkeypatch.setattr(Path, 'is_file', lambda p: True)
    monkeypatch.setattr(fork_profile.os, 'access', lambda *a: True)
    monkeypatch.setattr(binary, 'codex_version_error', lambda *a: None)


def test_native_login_and_sdk_keep_fixed_identity_over_explicit_paths(monkeypatch):
    broker(monkeypatch)
    assert codex_command(['app-server'], '/other/codex')[0] == [
        '/opt/agents-anywhere-fork-connector/bin/codex', 'app-server']
    assert claude_command(['auth', 'status'], '/other/claude') == [
        '/opt/agents-anywhere-fork-connector/bin/claude', 'auth', 'status']
    # Model discovery and real SDK sessions use this same options builder.
    session = SimpleNamespace(selections={}, planning_mode=False, cwd=None, external_session_id=None)
    options = build_sdk_options(SimpleNamespace(), {'executablePath': '/other/claude'}, session)
    assert options['cli_path'] == '/opt/agents-anywhere-fork-connector/bin/claude'


def test_missing_or_broken_broker_never_falls_back_to_another_identity(monkeypatch):
    broker(monkeypatch)
    monkeypatch.setattr(binary, 'codex_version_error', lambda *a: 'not available')
    with pytest.raises(RuntimeError, match='version check failed'):
        codex_command(['app-server'])
    monkeypatch.setattr(Path, 'is_file', lambda p: False)
    with pytest.raises(RuntimeError, match='Missing fixed-identity'):
        fork_profile.broker_executable('codex')


def test_broker_flag_does_not_change_official_launches(monkeypatch):
    monkeypatch.delenv('AA_CONNECTOR_PROFILE', raising=False)
    monkeypatch.setenv('AA_FORK_RUNTIME_BROKER', '1')
    assert fork_profile.broker_executable('codex') is None


def test_unchanged_bridge_keeps_inode_and_changed_or_missing_file_republishes(tmp_path, monkeypatch):
    from connector.runtimes.dsh.bridge import host as module
    monkeypatch.delenv('AA_FORK_RUNTIME_BROKER', raising=False)
    path = tmp_path / 'bridge/connector.json'
    monkeypatch.setattr(module, 'rendezvous_path', lambda: path)
    descriptor = {'instanceId': 'one'}
    host = module.BridgeHost.__new__(module.BridgeHost)
    host._published = None
    host.hub = SimpleNamespace(descriptor=lambda _: dict(descriptor))
    host.publish()
    before = path.stat().st_ino
    host.publish()
    assert path.stat().st_ino == before
    descriptor['instanceId'] = 'two'
    host.publish()
    assert module.read_rendezvous(path)['instanceId'] == 'two'
    path.write_text('invalid-json')
    host.publish()
    assert module.read_rendezvous(path)['instanceId'] == 'two'
    path.unlink()
    host.publish()
    assert path.exists()
