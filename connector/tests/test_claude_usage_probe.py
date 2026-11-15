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
    (config / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "synthetic-local-only", "refreshToken": "synthetic-refresh", "expiresAt": 9999999999999}}))
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
    result = module.normalized_usage(value)
    assert [w["kind"] for w in result["windows"]] == ["seven_day"]
    assert result["parse_warnings"][0]["field"] == "five_hour.utilization"


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
    (tmp_path / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "synthetic-secret", "refreshToken": "synthetic-refresh", "expiresAt": 9999999999999}}))
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


class JsonResponse:
    def __init__(self, value): self.data = json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, size): return self.data[:size]


@pytest.fixture
def probe_credentials(tmp_path, monkeypatch):
    import secrets
    path = tmp_path / '.credentials.json'
    value = {'other': {'preserved': True}, 'claudeAiOauth': {
        'accessToken': secrets.token_urlsafe(), 'refreshToken': secrets.token_urlsafe(),
        'expiresAt': (NOW - 1) * 1000, 'scopes': ['preserved']}}
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(module.time, 'time', lambda: NOW)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='9.8.7'))
    return path, value


def refresh_response():
    import secrets
    return {'access_token': secrets.token_urlsafe(), 'refresh_token': secrets.token_urlsafe(), 'expires_in': 28800}


def test_inactive_windows_and_real_sample():
    value = {'five_hour': {'utilization': 0.0, 'resets_at': None, 'limit_dollars': None,
        'used_dollars': None, 'remaining_dollars': None, 'locked_reason': None},
        'seven_day': {'utilization': 43.0, 'resets_at': '2026-11-19T17:00:00.050859+00:00',
        'limit_dollars': None, 'used_dollars': None, 'remaining_dollars': None, 'locked_reason': None}}
    result = module.normalized_usage(value)
    assert result['windows'][0] == {'kind': 'five_hour', 'used_percent': 0, 'resets_at': None}
    assert result['windows'][1]['used_percent'] == 43
    value['five_hour']['utilization'] = None
    assert module.normalized_usage(value)['windows'][0]['used_percent'] == 0
    del value['five_hour']['resets_at']
    assert module.normalized_usage(value)['parse_warnings'] == [{'field': 'five_hour.resets_at', 'reason': 'MissingField'}]


@pytest.mark.parametrize('value', [None, [], 'invalid', 1])
def test_bad_root_is_sanitized(value):
    with pytest.raises(module.ParseError, match=r'\$: TypeError'):
        module.normalized_usage(value)


@pytest.mark.parametrize('reset', ['bad-date', '2026-11-19T17:00:00', 123, False])
def test_bad_reset_discards_only_that_window(reset):
    value = body(); value['five_hour']['resets_at'] = reset
    result = module.normalized_usage(value)
    assert len(result['windows']) == 1
    assert result['parse_warnings'][0]['field'] == 'five_hour.resets_at'


def test_refresh_success_is_atomic_preserves_owner_mode_and_other_fields(probe_credentials):
    import os
    path, original = probe_credentials
    stat = path.stat(); response = refresh_response(); calls = []
    def open_request(request, **kw):
        calls.append(request.full_url)
        if request.full_url == module.TOKEN_URL:
            assert json.loads(request.data)['grant_type'] == 'refresh_token'
            return JsonResponse(response)
        return JsonResponse(body())
    result = module.fetch_usage(['claude'], opener=SimpleNamespace(open=open_request))
    assert 'windows' in result
    saved = json.loads(path.read_text())
    assert saved['other'] == original['other']
    assert saved['claudeAiOauth']['scopes'] == original['claudeAiOauth']['scopes']
    assert saved['claudeAiOauth']['accessToken'] == response['access_token'], 'access field mismatch'
    assert saved['claudeAiOauth']['refreshToken'] == response['refresh_token'], 'refresh field mismatch'
    assert saved['claudeAiOauth']['expiresAt'] == (NOW + 28800) * 1000
    assert path.stat().st_mode & 0o777 == 0o600
    assert (path.stat().st_uid, path.stat().st_gid) == (stat.st_uid, stat.st_gid)
    assert calls == [module.TOKEN_URL, module.URL]
    assert not list(path.parent.glob('.credentials-*'))


def test_refresh_failure_leaves_file_byte_identical(probe_credentials):
    path, _ = probe_credentials; before = path.read_bytes()
    def fail(*a, **kw): raise OSError('never forward exception text')
    result = module.fetch_usage(['claude'], opener=SimpleNamespace(open=fail))
    assert result == {'error_code': 'auth_expired'}
    assert path.read_bytes() == before, 'credential file changed'


def test_other_writer_refresh_before_lock_uses_existing_credentials(probe_credentials, monkeypatch):
    from contextlib import contextmanager
    path, original = probe_credentials; updated = refresh_response()
    @contextmanager
    def lock(_):
        value = json.loads(path.read_text())
        value['claudeAiOauth'].update(accessToken=updated['access_token'], refreshToken=updated['refresh_token'], expiresAt=(NOW+3600)*1000)
        path.write_text(json.dumps(value))
        yield
    monkeypatch.setattr(module, '_credential_lock', lock)
    calls = []
    def request(req, **kw):
        calls.append(req.full_url)
        assert req.get_header('Authorization') == 'Bearer ' + updated['access_token'], 'did not use current credential'
        return JsonResponse(body())
    assert 'windows' in module.fetch_usage(['claude'], opener=SimpleNamespace(open=request))
    assert calls == [module.URL]


@pytest.mark.parametrize('expired', [True, False])
def test_401_refreshes_at_most_once_and_retries_at_most_once(probe_credentials, expired):
    from io import BytesIO
    from urllib.error import HTTPError
    path, value = probe_credentials
    if not expired:
        value['claudeAiOauth']['expiresAt'] = (NOW+3600)*1000
        path.write_text(json.dumps(value))
    calls = []
    def request(req, **kw):
        calls.append(req.full_url)
        if req.full_url == module.TOKEN_URL: return JsonResponse(refresh_response())
        raise HTTPError(module.URL, 401, '', {}, BytesIO())
    result = module.fetch_usage(['claude'], opener=SimpleNamespace(open=request))
    assert result == {'error_code': 'auth_expired'}
    assert calls.count(module.TOKEN_URL) == 1
    assert calls.count(module.URL) == (1 if expired else 2)


def test_write_failure_after_refresh_is_explicit_and_preserves_bytes(probe_credentials, monkeypatch):
    path, _ = probe_credentials; before = path.read_bytes()
    def fail(*a): raise OSError()
    monkeypatch.setattr(module.os, 'replace', fail)
    result = module.fetch_usage(['claude'], opener=SimpleNamespace(open=lambda *a, **kw: JsonResponse(refresh_response())))
    assert result == {'error_code': 'auth_expired', 'detail': 'write_failed_after_refresh'}
    assert path.read_bytes() == before, 'credential file changed'
    assert not list(path.parent.glob('.credentials-*'))


def test_external_login_during_refresh_is_not_overwritten(probe_credentials):
    path, value = probe_credentials; external = refresh_response(); calls = []
    def request(req, **kw):
        calls.append(req.full_url)
        if req.full_url == module.TOKEN_URL:
            value['claudeAiOauth'].update(accessToken=external['access_token'], refreshToken=external['refresh_token'], expiresAt=(NOW+3600)*1000)
            path.write_text(json.dumps(value))
            return JsonResponse(refresh_response())
        assert req.get_header('Authorization') == 'Bearer ' + external['access_token'], 'wrong credential selected'
        return JsonResponse(body())
    assert 'windows' in module.fetch_usage(['claude'], opener=SimpleNamespace(open=request))
    assert json.loads(path.read_text()) == value, 'external login overwritten'


@pytest.mark.parametrize('raw', [b'{', b'[]', b'\xff', b'{"five_hour":false,"seven_day":{}}'])
def test_fetch_parse_failures_are_not_unavailable(probe_credentials, raw):
    path, value = probe_credentials
    value['claudeAiOauth']['expiresAt'] = (NOW+3600)*1000
    path.write_text(json.dumps(value))
    response = JsonResponse(None); response.data = raw
    result = module.fetch_usage(['claude'], opener=SimpleNamespace(open=lambda *a, **kw: response))
    assert result['error_code'] == 'parse_error'
    assert 'detail' in result


@pytest.mark.anyio
@pytest.mark.parametrize('code', ['auth_expired', 'parse_error'])
async def test_probe_rpc_preserves_error_codes_and_warnings(tmp_path, monkeypatch, code):
    from connector import account_usage
    host = SimpleNamespace(connector_id='test')
    rpc = account_usage.AccountUsageRpc(None, host)
    rpc.collector = SimpleNamespace(identify=AsyncMock(return_value={'account_key': 'a'*64}))
    monkeypatch.setattr(module, 'node_enabled', lambda _: True)
    monkeypatch.setattr(account_usage, 'broker_executable', lambda _: None)
    monkeypatch.setattr(account_usage, 'claude_command', lambda _: ['unused'])
    warning = {'field': 'five_hour.utilization', 'reason': 'TypeError'}
    monkeypatch.setattr(module, 'fetch_usage', lambda _: {'error_code': code, 'parse_warnings': [warning]})
    result = await rpc._manual_probe()
    assert result['errorCode'] == code
    assert result['parseWarnings'] == [warning]


def test_default_opener_disables_proxies_and_redirects(probe_credentials, monkeypatch):
    path, value = probe_credentials
    value['claudeAiOauth']['expiresAt'] = (NOW+3600)*1000
    path.write_text(json.dumps(value))
    handlers = []
    def build(*values):
        handlers.extend(values)
        return SimpleNamespace(open=lambda *a, **kw: JsonResponse(body()))
    monkeypatch.setattr(module.urllib.request,'build_opener',build)
    assert 'windows' in module.fetch_usage(['claude'])
    assert handlers[0].proxies == {}
    assert isinstance(handlers[1],module.NoRedirect)
    assert handlers[1].redirect_request(None,None,302,'',{},'https://example.invalid') is None
