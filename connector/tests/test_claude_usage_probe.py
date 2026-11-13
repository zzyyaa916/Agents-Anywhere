import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from connector.core.json_kv import JsonKeyValueStore
from connector.runtimes.claude import usage_probe as module

NOW = 2000000000


def body():
    return {"five_hour": {"utilization": 71, "resets_at": datetime.fromtimestamp(NOW + 3600, UTC).isoformat()},
            "seven_day": {"utilization": 28, "resets_at": datetime.fromtimestamp(NOW + 86400, UTC).isoformat()},
            "accessToken": "synthetic-not-forwarded"}


class Response:
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, size): return json.dumps(body()).encode()


def test_local_request_uses_installed_version_and_never_returns_credentials(tmp_path, monkeypatch):
    config = tmp_path / ".claude"; config.mkdir()
    (config / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "synthetic-local-only"}}))
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    calls = []
    def version(args, **kwargs):
        assert args == ["/installed/claude", "--version"]
        return SimpleNamespace(stdout="9.8.7 (Claude Code)")
    monkeypatch.setattr(module.subprocess, "run", version)
    def open_request(request, **kwargs):
        calls.append(request)
        assert request.full_url == module.URL and request.method == "GET"
        headers = {k.lower(): v for k, v in request.header_items()}
        assert headers["authorization"] == "Bearer synthetic-local-only"
        assert headers["anthropic-beta"] == "oauth-2025-04-20"
        assert headers["user-agent"] == "claude-code/9.8.7"
        return Response()
    result = module.fetch_usage(["/installed/claude"], opener=SimpleNamespace(open=open_request))
    assert len(calls) == 1 and set(result) == {"windows"}
    assert [w["used_percent"] for w in result["windows"]] == [71, 28]
    assert "synthetic" not in json.dumps(result)
    assert all(set(w) == {"kind", "used_percent", "resets_at"} for w in result["windows"])


@pytest.mark.parametrize("header, expected", [("600", {"retry_after_seconds": 600}), ("0", {"retry_after_seconds": 0}),
    (None, {}), ("garbage", {}), ("Wed, 18 May 2033 04:00:00 GMT", {"retry_after_at": "2033-05-18T04:00:00+00:00"})])
def test_retry_after_is_a_hint_for_server_clock(header, expected):
    assert module.retry_hint(header) == expected


@pytest.mark.parametrize("bad", [True, -1, 101, float("nan"), "71"])
def test_malformed_percent_is_never_forwarded(bad):
    value = body(); value["five_hour"]["utilization"] = bad
    with pytest.raises(ValueError): module.normalized_usage(value)


def test_only_pinned_linux_arm_connector_is_enabled(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"oracle-machine\n")
    monkeypatch.delenv("AA_CLAUDE_USAGE_PROBE_CONNECTOR_ID", raising=False)
    monkeypatch.delenv("AA_CLAUDE_USAGE_PROBE_MACHINE_ID", raising=False)
    assert not module.node_enabled("oracle")
    monkeypatch.setenv("AA_CLAUDE_USAGE_PROBE_CONNECTOR_ID", "oracle")
    monkeypatch.setenv("AA_CLAUDE_USAGE_PROBE_MACHINE_ID", hashlib.sha256(b"oracle-machine").hexdigest())
    assert module.node_enabled("oracle") and not module.node_enabled("other")
    monkeypatch.setattr(Path, "read_bytes", lambda _: b"other-machine")
    assert not module.node_enabled("oracle")


@pytest.mark.anyio
async def test_passive_collection_cannot_call_probe(tmp_path, monkeypatch):
    from connector.account_usage import AccountUsageRpc
    host = SimpleNamespace(runtime_kv=JsonKeyValueStore(tmp_path / "kv.json"), connector_id="other")
    supervisor = SimpleNamespace(entry_or_none=lambda _: SimpleNamespace(runtime_type="claude", requested_values={}))
    rpc = AccountUsageRpc(supervisor, host)
    rpc.collector = SimpleNamespace(collect=AsyncMock(return_value={"runtime": "claude_code", "windows": []}))
    monkeypatch.setattr(module, "fetch_usage", lambda *_: pytest.fail("Unexpected probe"))
    await rpc.dispatch("accountUsage.collect", {"runtimeId": "claude", "accountKey": "a" * 64})
    monkeypatch.delenv("AA_CLAUDE_USAGE_PROBE_CONNECTOR_ID", raising=False)
    result = await rpc.dispatch("accountUsage.probe", {"runtimeId": "claude"})
    assert result["errorCode"] == "unsupported_auth"


@pytest.mark.anyio
async def test_native_event_push_has_no_observation_clock_and_keeps_reset_windows(tmp_path, monkeypatch):
    from connector.server.runtime_host import ConnectorRuntimeHost
    monkeypatch.setenv("AGENT_CONNECTOR_KV_FILE", str(tmp_path / "kv.json"))
    sent = []
    async def notify(method, params): sent.append((method, params))
    async def ignore(*args): pass
    host = ConnectorRuntimeHost("test", notify, ignore)
    host._claude_identity = AsyncMock(return_value={"account_key": "a" * 64})
    observe = await host.claude_usage_observer()
    await observe("five_hour", .71, 1)
    assert sent[0][0] == "accountUsage.event"
    payload = sent[0][1]
    assert set(payload) == {"runtimeId", "accountKey", "eventId", "windows"}
    assert payload["windows"][0]["usedPercent"] == 71
    assert payload["windows"][0]["resetsAt"].startswith("1970-")


def test_http_429_does_not_read_or_log_error_body(tmp_path, monkeypatch, caplog):
    from io import BytesIO
    from urllib.error import HTTPError
    (tmp_path / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "synthetic-secret"}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="9.8.7"))
    calls = []
    def limited(*args, **kwargs):
        calls.append(True)
        raise HTTPError(module.URL, 429, "synthetic-secret", {"Retry-After": "1800"}, BytesIO(b"synthetic-secret"))
    result = module.fetch_usage(["installed"], opener=SimpleNamespace(open=limited))
    assert result == {"error_code": "rate_limited", "retry_after_seconds": 1800}
    assert len(calls) == 1 and "synthetic-secret" not in caplog.text


def test_valid_old_reset_is_not_cleared_by_machine_clock():
    value = body()
    value["five_hour"]["resets_at"] = "1970-01-01T00:00:01Z"
    assert module.normalized_usage(value)["windows"][0]["used_percent"] == 71
