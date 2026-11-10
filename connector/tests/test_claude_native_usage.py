import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from connector.account_usage import LocalAccountUsage
from connector.runtimes.claude.sdk.events import native_usage_from_message
from connector.core.json_kv import JsonKeyValueStore

@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    profile = tmp_path / ".claude.json"
    profile.write_text(json.dumps({"oauthAccount": {"accountUuid": "account-a"}}))
    now = [2000000000]
    store = JsonKeyValueStore(tmp_path / "usage.json")
    service = LocalAccountUsage(store, home=tmp_path, clock=lambda: now[0])
    return service, service.claude_identity()["account_key"], now, profile

def test_strict_native_event_shape():
    assert native_usage_from_message({"type": "assistant", "rate_limit_info": {"rate_limit_type": "five_hour"}}) is None
    message = {"type": "rate_limit_event", "rate_limit_info": {"rate_limit_type": "five_hour", "utilization": .5, "resets_at": 2000007200, "raw": {"token": "synthetic-not-forwarded"}}}
    assert native_usage_from_message(message) == ("five_hour", .5, 2000007200)
    message["rate_limit_info"]["rate_limit_type"] = "unknown"
    assert native_usage_from_message(message) is None

@pytest.mark.parametrize("used", [None, True, -0.1, 1.1, float("nan"), "0.2"])
def test_missing_or_invalid_native_utilization_never_invents_a_percentage(native, used):
    service, key, _, _ = native
    assert not service.observe_claude_window(key, "five_hour", used, 2000007200)
    assert service.kv.get("native-claude-usage/" + key) is None

def test_account_change_rejects_old_connection(native):
    service, key, _, profile = native
    profile.write_text(json.dumps({"oauthAccount": {"accountUuid": "account-b"}}))
    assert not service.observe_claude_window(key, "five_hour", .2, 2000007200)
    assert service.kv.get("native-claude-usage/" + key) is None

def test_merge_windows_restart_and_conservative_staleness(native):
    service, key, now, _ = native
    assert service.observe_claude_window(key, "seven_day", .3, now[0] + 86400)
    first = now[0]; now[0] += 301
    assert service.observe_claude_window(key, "five_hour", .1, now[0] + 3600)
    restarted = LocalAccountUsage(service.kv, home=service.home, clock=lambda: now[0])
    windows, observed, stale = restarted._claude_cached_usage(key)
    assert len(windows) == 2 and stale and observed == first
    now[0] += 7200
    windows, _, stale = restarted._claude_cached_usage(key)
    assert stale and next(w for w in windows if w["kind"] == "five_hour")["remaining_percent"] == 90
    assert "account-a" not in service.kv.path.read_text()

@pytest.mark.anyio
async def test_transport_observes_native_events_without_querying_or_forwarding_raw():
    from connector.runtimes.claude.sdk.connection import ClaudeConnection
    class Client:
        async def receive_messages(self):
            yield {"type": "rate_limit_event", "rate_limit_info": {"rate_limit_type": "five_hour", "utilization": .25, "resets_at": 2000007200, "raw": {"token": "synthetic-secret"}}}
    seen = []
    async def ignore(*args): pass
    async def observe(*args): seen.append(args)
    connection = ClaudeConnection(Client(), ignore, ignore, ignore, lambda: None, on_native_usage=observe)
    connection.queried.set(); connection.closing = True
    await connection._run()
    assert seen == [("five_hour", .25, 2000007200)]
    assert connection.current is None

@pytest.mark.anyio
async def test_real_host_callback_captures_account_and_rejects_later_switch(tmp_path, monkeypatch):
    from connector.server.runtime_host import ConnectorRuntimeHost
    profile = tmp_path / ".claude.json"
    profile.write_text(json.dumps({"oauthAccount": {"accountUuid": "a"}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_CONNECTOR_KV_FILE", str(tmp_path / "kv.json"))
    async def ignore(*args, **kwargs): pass
    host = ConnectorRuntimeHost("conn_test", ignore, ignore)
    observe = host.claude_usage_observer()
    assert observe is not None
    await observe("five_hour", .25, 2500000000)
    before = host.account_usage_kv.path.read_text()
    profile.write_text(json.dumps({"oauthAccount": {"accountUuid": "b"}}))
    await observe("five_hour", .5, 2500000000)
    assert host.account_usage_kv.path.read_text() == before
