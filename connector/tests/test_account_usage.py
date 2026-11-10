import json
from contextlib import asynccontextmanager

import pytest
from connector.account_usage import (
    LocalAccountUsage,
    UsageUnavailable,
    codex_windows,
    identity,
)


class KV:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = dict(value)


def test_codex_duration_not_position():
    result = codex_windows(
        {
            "rateLimitsByLimitId": {
                "codex": {
                    "primary": {
                        "usedPercent": 20,
                        "resetsAt": 2000000000,
                        "windowDurationMins": 10080,
                    },
                    "secondary": {
                        "usedPercent": 90,
                        "resetsAt": 2000000000,
                        "windowDurationMins": 300,
                    },
                }
            }
        }
    )
    assert [(w["kind"], w["remaining_percent"]) for w in result] == [
        ("weekly", 80),
        ("five_hour", 10),
    ]
    assert (
        codex_windows(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 1,
                        "resetsAt": 2000000000,
                        "windowDurationMins": 15,
                    }
                }
            }
        )[0]["kind"]
        == "other"
    )


@pytest.mark.parametrize("bad", [-1, 101, float("nan"), True, "20"])
def test_invalid_percent_rejected(bad):
    with pytest.raises(UsageUnavailable):
        codex_windows(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": bad,
                        "resetsAt": 2000000000,
                        "windowDurationMins": 300,
                    }
                }
            }
        )


@pytest.mark.anyio
async def test_codex_readonly_gate_restart_backoff_and_identity(tmp_path):
    clock = [2000000000.0]
    calls = []
    fail = [False]
    email = ["test@example.invalid"]

    @asynccontextmanager
    async def factory(executable):
        async def request(method, params=None):
            calls.append((method, params))
            if method == "account/read":
                assert params == {"refreshToken": False}
                return {
                    "account": {
                        "type": "chatgpt",
                        "email": email[0],
                        "planType": "plus",
                    }
                }
            assert method == "account/rateLimits/read"
            if fail[0]:
                raise RuntimeError("synthetic upstream secret must never escape")
            return {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 80,
                        "resetsAt": clock[0] + 100,
                        "windowDurationMins": 300,
                    }
                }
            }

        yield request

    kv = KV()
    service = LocalAccountUsage(
        kv, home=tmp_path, clock=lambda: clock[0], codex_factory=factory
    )
    key = identity("codex", email[0])["account_key"]
    good = await service.collect("codex", key)
    assert good["windows"][0]["remaining_percent"] == 20
    service = LocalAccountUsage(
        kv, home=tmp_path, clock=lambda: clock[0], codex_factory=factory
    )
    await service.collect("codex", key)
    assert sum(method == "account/rateLimits/read" for method, _ in calls) == 1
    fail[0] = True
    for advance, delay in [(60, 300), (300, 900), (900, 1800)]:
        clock[0] += advance
        result = await service.collect("codex", key)
        assert result["stale"] and result["windows"] == good["windows"]
        assert result["next_attempt_at"] == clock[0] + delay
        assert "secret" not in json.dumps(result)
    email[0] = "other@example.invalid"
    result = await service.collect("codex", key)
    assert result["error_code"] == "account_changed" and not result["windows"]
    assert "@" not in json.dumps(kv.data)


@pytest.mark.anyio
async def test_claude_local_identity_and_five_minute_gate(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": "synthetic-account"}}))
    now = [2000000000]
    service = LocalAccountUsage(KV(), home=tmp_path, clock=lambda: now[0])
    info = await service.identify("claude_code")
    assert service.observe_claude_window(info["account_key"], "five_hour", .2, now[0] + 7200)
    first = await service.collect("claude_code", info["account_key"])
    assert first["windows"][0]["remaining_percent"] == 80
    assert first["next_attempt_at"] == now[0] + 300
    assert "synthetic-account" not in json.dumps(first)
    now[0] += 60
    service.observe_claude_window(info["account_key"], "five_hour", .3, now[0] + 7200)
    assert (await service.collect("claude_code", info["account_key"]))["windows"][0]["remaining_percent"] == 80



@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_claude_native_cache_never_reads_credentials_or_starts_process(tmp_path, monkeypatch):
    import connector.account_usage as module
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": "account"}}))
    async def forbidden(*args, **kwargs):
        raise AssertionError("No subprocess or network call allowed")
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", forbidden)
    from pathlib import Path
    original = Path.read_text
    reads = []
    def guarded(path, *args, **kwargs):
        reads.append(str(path))
        assert path.name != ".credentials.json"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", guarded)
    kv = KV(); service = LocalAccountUsage(kv, home=tmp_path, clock=lambda: 2000000000)
    info = await service.identify("claude_code")
    service.observe_claude_window(info["account_key"], "five_hour", .2, 2000007200)
    result = await service.collect("claude_code", info["account_key"])
    assert result["windows"][0]["remaining_percent"] == 80
    assert all("credentials" not in name for name in reads)
    assert set(kv.data["native-claude-usage/" + info["account_key"]]) == {"windows"}



@pytest.mark.anyio
async def test_rpc_whitelist_strips_credentials_and_internal_fields():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from connector.account_usage import AccountUsageRpc

    rpc = AccountUsageRpc(
        SimpleNamespace(
            entry_or_none=lambda _: SimpleNamespace(
                runtime_type="codex", requested_values={}
            )
        ),
        None,
    )
    rpc.collector = SimpleNamespace(
        collect=AsyncMock(
            return_value={
                "runtime": "codex",
                "account_key": "a" * 64,
                "failures": 2,
                "accessToken": "synthetic-private",
                "windows": [
                    {
                        "kind": "five_hour",
                        "used_percent": 90,
                        "remaining_percent": 10,
                        "resets_at": "2030-01-01T00:00:00Z",
                        "window_duration_mins": 300,
                        "apiKey": "synthetic-window-private",
                    }
                ],
            }
        )
    )
    result = await rpc.dispatch(
        "accountUsage.collect", {"runtimeId": "codex", "accountKey": "a" * 64}
    )
    assert (
        result["accountKey"] == "a" * 64
        and result["windows"][0]["remainingPercent"] == 10
    )
    assert "private" not in json.dumps(result) and "failures" not in result


@pytest.mark.anyio
@pytest.mark.anyio
async def test_usage_cancellation_propagates(tmp_path):
    import asyncio

    @asynccontextmanager
    async def cancelled(executable):
        raise asyncio.CancelledError()
        yield

    collector = LocalAccountUsage(KV(), home=tmp_path, codex_factory=cancelled)
    with pytest.raises(asyncio.CancelledError):
        await collector.identify("codex")
