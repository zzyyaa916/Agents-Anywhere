import asyncio
import json
import subprocess
import threading
from types import SimpleNamespace

import pytest
from connector.account_usage import LocalAccountUsage, UsageUnavailable
from connector.runtime_protocol import attachments
from connector.runtimes.dsh.bridge import host as bridge

from connector import account_usage


@pytest.mark.parametrize('runtime', ['claude', 'codex'])
def test_materialized_attachment_grants_only_target_runtime(tmp_path, monkeypatch, runtime):
    from connector.core import fork_profile
    monkeypatch.setenv('AA_CONNECTOR_PROFILE', 'fork')
    monkeypatch.setenv('AA_FORK_RUNTIME_BROKER', '1')
    calls = []
    monkeypatch.setattr(fork_profile, 'share_runtime_path', lambda p, permission, **kw: calls.append((p, permission, kw)))
    target = tmp_path / 'attachments/session/file-note.txt'
    attachments.write_runtime_attachment(target, b'note', runtime)
    assert target.read_bytes() == b'note'
    assert target.stat().st_mode & 0o777 == 0o600
    assert (target.parent, '--x', {'runtime': runtime}) in calls
    assert calls[-1] == (target, 'r--', {'runtime': runtime})
    other = tmp_path / 'other'
    other.write_bytes(b'keep')
    target.unlink(); target.symlink_to(other)
    with pytest.raises(ValueError, match='links'):
        attachments.write_runtime_attachment(target, b'overwrite', runtime)
    assert other.read_bytes() == b'keep'


def test_bridge_repairs_acl_after_writing_and_when_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv('AA_CONNECTOR_PROFILE', 'fork')
    monkeypatch.setenv('AA_FORK_RUNTIME_BROKER', '1')
    path = tmp_path / 'bridge/connector.json'
    monkeypatch.setattr(bridge, 'rendezvous_path', lambda: path)
    descriptor = {'instanceId': 'first'}
    host = bridge.BridgeHost(SimpleNamespace(descriptor=lambda _: dict(descriptor)))
    seen = []
    def repair(args, **kw):
        assert kw['timeout'] == 10 and kw['check']
        seen.append(bridge.read_rendezvous(path)['instanceId'])
    monkeypatch.setattr(subprocess, 'run', repair)
    host.publish(); inode = path.stat().st_ino
    host.publish()
    assert path.stat().st_ino == inode
    descriptor['instanceId'] = 'second'
    host.publish()
    path.unlink(); host.publish()
    assert seen == ['first', 'first', 'second', 'second']
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired('acl', 10)))
    with pytest.raises(subprocess.TimeoutExpired):
        host.publish()


@pytest.mark.anyio
async def test_bridge_publish_does_not_block_event_loop(monkeypatch):
    from unittest.mock import AsyncMock
    host = bridge.BridgeHost(SimpleNamespace(mount=AsyncMock()))
    loop_thread = threading.get_ident()
    seen = []
    monkeypatch.setattr(host, 'publish', lambda: seen.append(threading.get_ident()))
    await host.start()
    assert seen and seen[0] != loop_thread


@pytest.mark.anyio
async def test_fixed_claude_identity_observation_and_account_switch(tmp_path, monkeypatch):
    from connector.core.json_kv import JsonKeyValueStore
    monkeypatch.setattr(account_usage, 'broker_executable', lambda _: '/broker/claude')
    monkeypatch.setattr(account_usage, 'claude_command', lambda args: ['/broker/claude', *args])
    status = {'loggedIn': True, 'authMethod': 'claude.ai', 'email': 'a@example.invalid', 'subscriptionType': 'max'}
    loop_thread = threading.get_ident()
    seen = []
    def run(command, **kw):
        assert command == ['/broker/claude', 'auth', 'status'] and kw['timeout'] == 15
        seen.append(threading.get_ident())
        return SimpleNamespace(returncode=0, stdout=json.dumps(status))
    monkeypatch.setattr(subprocess, 'run', run)
    service = LocalAccountUsage(JsonKeyValueStore(tmp_path / 'usage.json'), clock=lambda: 2000000000)
    info = await service.identify('claude_code')
    assert info['plan_type'] == 'max' and seen[-1] != loop_thread
    assert await asyncio.to_thread(service.observe_claude_window, info['account_key'], 'five_hour', .25, 2000007200)
    result = await service.collect('claude_code', info['account_key'])
    assert result['windows'][0]['remaining_percent'] == 75
    status['email'] = 'b@example.invalid'
    assert not await asyncio.to_thread(service.observe_claude_window, info['account_key'], 'five_hour', .5, 2000007200)
    assert (await service.collect('claude_code', info['account_key']))['error_code'] == 'account_changed'
    assert '@' not in service.kv.path.read_text()


@pytest.mark.parametrize('status', [{'loggedIn': False}, {'loggedIn': True}, {'loggedIn': True, 'authMethod': 'api_key', 'email': 'a'}])
def test_fixed_claude_invalid_auth_never_returns_identity(monkeypatch, status):
    monkeypatch.setattr(account_usage, 'broker_executable', lambda _: '/broker')
    monkeypatch.setattr(account_usage, 'claude_command', lambda _: ['/broker'])
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(status)))
    with pytest.raises(UsageUnavailable):
        LocalAccountUsage(None).claude_identity()


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_instance_wrapper_keeps_native_usage_callback():
    from unittest.mock import AsyncMock

    from connector.runtime_protocol import RuntimeInstanceHost, RuntimeInstanceSpec
    callback = object()
    base = SimpleNamespace(claude_usage_observer=AsyncMock(return_value=callback))
    instance = RuntimeInstanceSpec(runtime_id="claude", runtime_type="claude", name="Claude")
    host = RuntimeInstanceHost(base=base, instance=instance)
    assert await host.claude_usage_observer() is callback
