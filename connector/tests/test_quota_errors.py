import pytest
from connector.quota_errors import is_usage_limit


@pytest.mark.parametrize(
    "runtime,error",
    [
        ("codex", {"code": "usage_limit_reached"}),
        ("codex", {"raw": {"codexErrorInfo": "UsageLimitExceeded"}}),
        ("codex", {"message": "You've hit your usage limit. Try again later."}),
        (
            "claude",
            {
                "code": "claude_result_error",
                "message": "You've hit your limit · resets 2pm",
            },
        ),
        ("claude", {"message": "You have reached your usage limit"}),
    ],
)
def test_terminal_usage_limit(runtime, error):
    assert is_usage_limit(runtime, error)


@pytest.mark.parametrize(
    "runtime,error",
    [
        ("codex", {"code": 429, "message": "rate limit exceeded"}),
        ("claude", {"code": "rate_limit_error", "message": "Too many requests"}),
        ("claude", {"message": "network unavailable"}),
        ("codex", {"message": "permission denied"}),
        ("dsh", {"code": "usage_limit_reached"}),
    ],
)
def test_ordinary_errors_unchanged(runtime, error):
    assert not is_usage_limit(runtime, error)


def test_host_reports_terminal_limit_on_original_session():
    import asyncio
    from unittest.mock import AsyncMock

    from connector.server.runtime_host import ConnectorRuntimeHost

    async def exercise():
        notify = AsyncMock()
        host = ConnectorRuntimeHost("device", notify, AsyncMock())
        await host.session_state_update(
            "same-platform-session",
            "codex",
            status="error",
            external_session_id="same-native-thread",
            error={"code": "usage_limit_reached"},
        )
        method, body = notify.call_args.args
        assert method == "session.state.updated"
        assert (
            body["sessionId"] == "same-platform-session"
            and body["externalSessionId"] == "same-native-thread"
        )
        assert (
            body["metadata"]["quotaLimited"] is True
            and body["statusReason"] == "usage_limit"
        )
        await host.session_state_update(
            "same-platform-session",
            "claude",
            status="error",
            error={"code": 429, "message": "Too many requests"},
        )
        assert "quotaLimited" not in notify.call_args.args[1]["metadata"]

    asyncio.run(exercise())


@pytest.mark.parametrize("message", [
    {"type":"assistant", "error":"rate_limit", "content":[{"text":"You've hit your limit · resets 2pm"}]},
    {"type":"result", "is_error":True, "result":"You've hit your usage limit"},
])
def test_claude_structured_error_variants(message):
    from connector.runtimes.claude.sdk.events import terminal_event_from_message
    terminal = terminal_event_from_message(message)
    assert terminal.status == "failed" and terminal.error_code == "usage_limit_reached"


def test_plain_assistant_quote_is_not_a_quota_error():
    from connector.runtimes.claude.sdk.events import terminal_event_from_message
    assert terminal_event_from_message({"type":"assistant", "content":[{"text":"The error may say You've hit your limit"}]}) is None
