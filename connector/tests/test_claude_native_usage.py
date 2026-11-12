import json

import pytest
from connector.account_usage import LocalAccountUsage
from connector.core.json_kv import JsonKeyValueStore
from connector.runtimes.claude.sdk.events import native_usage_from_message


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
    assert native_usage_from_message({"type": "assistant", "rate_limit_info": {"rate_limit_type": "five_hour"}}) == []
    message = {"type": "rate_limit_event", "rate_limit_info": {"rate_limit_type": "five_hour", "utilization": .5, "resets_at": 2000007200, "raw": {"token": "synthetic-not-forwarded"}}}
    assert native_usage_from_message(message) == [("five_hour", .5, 2000007200)]
    message["rate_limit_info"]["utilization"] = {"token": "synthetic-not-forwarded"}
    message["rate_limit_info"]["resets_at"] = {"token": "synthetic-not-forwarded"}
    assert native_usage_from_message(message) == [("five_hour", None, None)]
    message["rate_limit_info"]["rate_limit_type"] = "unknown"
    assert native_usage_from_message(message) == []

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
    observe = await host.claude_usage_observer()
    assert observe is not None
    await observe("five_hour", .25, 2500000000)
    before = host.account_usage_kv.path.read_text()
    profile.write_text(json.dumps({"oauthAccount": {"accountUuid": "b"}}))
    await observe("five_hour", .5, 2500000000)
    assert host.account_usage_kv.path.read_text() == before


@pytest.mark.anyio
async def test_broker_identity_cache_coalesces_events_and_expires_for_account_switch(tmp_path, monkeypatch):
    import asyncio
    import copy
    from types import SimpleNamespace

    from connector.server import runtime_host
    monkeypatch.setenv("AGENT_CONNECTOR_KV_FILE", str(tmp_path / "kv.json"))
    monkeypatch.setattr(runtime_host, "broker_executable", lambda _: "/fake-broker")
    now = [1000]
    monkeypatch.setattr(runtime_host, "time", SimpleNamespace(monotonic=lambda: now[0]))
    calls = []
    account = ["a" * 64]
    def identify(self):
        calls.append(account[0])
        return {"account_key": account[0]}
    monkeypatch.setattr(LocalAccountUsage, "claude_identity", identify)
    async def ignore(*args, **kwargs): pass
    host = runtime_host.ConnectorRuntimeHost("test", ignore, ignore)
    observers = await asyncio.gather(*(copy.copy(host).claude_usage_observer() for _ in range(8)))
    await asyncio.gather(*(observer("five_hour", .25, 2500000000) for observer in observers))
    assert len(calls) == 1
    before = host.account_usage_kv.path.read_text()
    account[0] = "b" * 64
    now[0] += 61
    await observers[0]("five_hour", .5, 2500000000)
    assert len(calls) == 2
    assert host.account_usage_kv.path.read_text() == before


@pytest.mark.anyio
async def test_broker_identity_failure_is_also_cached(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from connector.server import runtime_host
    monkeypatch.setenv("AGENT_CONNECTOR_KV_FILE", str(tmp_path / "kv.json"))
    monkeypatch.setattr(runtime_host, "broker_executable", lambda _: "/fake-broker")
    now = [1000]
    monkeypatch.setattr(runtime_host, "time", SimpleNamespace(monotonic=lambda: now[0]))
    calls = []
    def identify(self):
        calls.append(True)
        raise RuntimeError("unavailable")
    monkeypatch.setattr(LocalAccountUsage, "claude_identity", identify)
    async def ignore(*args, **kwargs): pass
    host = runtime_host.ConnectorRuntimeHost("test", ignore, ignore)
    assert await host.claude_usage_observer() is None
    assert await host.claude_usage_observer() is None
    assert len(calls) == 1
    now[0] += 61
    assert await host.claude_usage_observer() is None
    assert len(calls) == 2


@pytest.fixture
def unified_native_event():
    # CLI unifiedWindows schema; timestamps/values and ids are synthetic.
    return {
        "type": "rate_limit_event",
        "rate_limit_info": {
            "status": "allowed",
            "unifiedWindows": {
                "five_hour": {"utilization": .25, "resetsAt": 2000007200, "status": "allowed"},
                "seven_day": {"utilization": .4, "resetsAt": 2000604800, "status": "allowed"},
            },
        },
        "uuid": "native-event-fixture",
        "session_id": "native-session-fixture",
    }


@pytest.mark.parametrize("sdk_parsed", [False, True])
def test_unified_windows_survive_sdk_raw_and_need_no_outer_kind(unified_native_event, sdk_parsed):
    from claude_agent_sdk._internal.message_parser import parse_message
    message = parse_message(unified_native_event) if sdk_parsed else unified_native_event
    assert native_usage_from_message(message) == [
        ("five_hour", .25, 2000007200), ("seven_day", .4, 2000604800),
    ]


def test_unified_windows_override_outer_once_and_missing_window_uses_outer(unified_native_event):
    info = unified_native_event["rate_limit_info"]
    info.update(rateLimitType="five_hour", utilization=.9, resetsAt=2000008000)
    assert native_usage_from_message(unified_native_event) == [
        ("five_hour", .25, 2000007200), ("seven_day", .4, 2000604800),
    ]
    del info["unifiedWindows"]["five_hour"]
    assert native_usage_from_message(unified_native_event) == [
        ("five_hour", .9, 2000008000), ("seven_day", .4, 2000604800),
    ]


@pytest.mark.parametrize("value", [None, True, -.1, 1.1, float("nan"), "0.25"])
def test_unified_windows_keep_strict_numeric_validation(unified_native_event, value):
    unified_native_event["rate_limit_info"]["unifiedWindows"]["five_hour"].update(utilization=value, resetsAt=True)
    assert native_usage_from_message(unified_native_event) == [
        ("five_hour", None, None), ("seven_day", .4, 2000604800),
    ]


@pytest.mark.anyio
async def test_transport_observes_both_unified_windows_once(unified_native_event, native):
    from claude_agent_sdk._internal.message_parser import parse_message
    from connector.runtimes.claude.sdk.connection import ClaudeConnection
    service, key, _, _ = native
    seen = []
    class Client:
        async def receive_messages(self):
            yield parse_message(unified_native_event)
    async def ignore(*args): pass
    async def observe(*args):
        seen.append(args)
        assert service.observe_claude_window(key, *args)
    connection = ClaudeConnection(Client(), ignore, ignore, ignore, lambda: None, on_native_usage=observe)
    connection.queried.set(); connection.closing = True
    await connection._run()
    assert seen == [("five_hour", .25, 2000007200), ("seven_day", .4, 2000604800)]
    windows, _, stale = service._claude_cached_usage(key)
    assert len(windows) == 2 and not stale
    assert "native-session-fixture" not in service.kv.path.read_text()
