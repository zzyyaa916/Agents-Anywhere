import json
from contextlib import asynccontextmanager

import pytest
from connector.account_usage import (
    LocalAccountUsage,
    UsageUnavailable,
    claude_windows,
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


def test_claude_priority_legacy_and_scoped():
    reset = "2030-01-01T12:00:00Z"
    current = claude_windows(
        {
            "limits": [
                {"kind": "session", "percent": 30, "resets_at": reset},
                {
                    "kind": "weekly_scoped",
                    "model": "Claude Opus",
                    "percent": 50,
                    "resets_at": reset,
                },
            ],
            "five_hour": {"utilization": 99, "resets_at": reset},
        }
    )
    assert current[0]["remaining_percent"] == 70
    assert current[1]["model_scope"] == "opus"
    assert (
        claude_windows({"seven_day": {"utilization": 25, "resets_at": reset}})[0][
            "remaining_percent"
        ]
        == 75
    )
    with pytest.raises(UsageUnavailable):
        claude_windows(
            {"limits": [], "five_hour": {"utilization": 99, "resets_at": reset}}
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
    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"accountUuid": "synthetic-account"}})
    )
    service = LocalAccountUsage(KV(), home=tmp_path, clock=lambda: 2000000000)
    calls = []

    async def usage(executable):
        calls.append(1)
        return claude_windows(
            {"five_hour": {"utilization": 20, "resets_at": "2033-05-18T03:33:20Z"}}
        )

    monkeypatch.setattr(service, "_claude_usage", usage)
    info = await service.identify("claude_code")
    first = await service.collect("claude_code", info["account_key"])
    await service.collect("claude_code", info["account_key"])
    assert len(calls) == 1 and first["next_attempt_at"] == 2000000300
    assert "synthetic-account" not in json.dumps(first)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_claude_request_credentials_stay_local(tmp_path, monkeypatch):
    import connector.account_usage as module

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    credentials = tmp_path / ".claude"
    credentials.mkdir()
    (credentials / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "synthetic-local-only"}})
    )
    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"accountUuid": "account"}})
    )

    class Child:
        returncode = 0

        async def communicate(self):
            return b"2.1.0 (Claude Code)", b""

    async def spawn(*args, **kwargs):
        assert args == ("claude", "--version")
        assert kwargs["stderr"] == module.asyncio.subprocess.DEVNULL
        return Child()

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)

    class Response:
        status_code = 200

        def json(self):
            return {
                "five_hour": {"utilization": 20, "resets_at": "2030-01-01T00:00:00Z"},
                "accessToken": "synthetic-upstream-secret",
            }

    class Http:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 20, "follow_redirects": False}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, *, headers):
            assert url == "https://api.anthropic.com/api/oauth/usage"
            assert headers == {
                "Authorization": "Bearer synthetic-local-only",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "claude-code/2.1.0",
            }
            return Response()

    kv = KV()
    collector = LocalAccountUsage(
        kv, home=tmp_path, platform="linux", http_factory=Http
    )
    info = await collector.identify("claude_code")
    result = await collector.collect("claude_code", info["account_key"])
    serialized = json.dumps([result, kv.data])
    assert (
        "synthetic-local-only" not in serialized
        and "synthetic-upstream-secret" not in serialized
    )
    assert result["windows"][0]["remaining_percent"] == 80
