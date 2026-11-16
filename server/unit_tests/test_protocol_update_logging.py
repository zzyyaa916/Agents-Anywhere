import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import agent_server.api.sessions as sessions_api


def test_best_effort_protocol_update_logs_exception_class(monkeypatch) -> None:
    calls = []

    class FakeLogger:
        def debug(self, message, *args):
            calls.append((message, args))

    monkeypatch.setattr(sessions_api, "logger", FakeLogger())
    db = SimpleNamespace(get_session=AsyncMock(side_effect=RuntimeError("boom")))

    asyncio.run(
        sessions_api._best_effort_publish_session_protocol_update(
            db,
            None,
            None,
            None,
            "sess_logged",
            user_id="user_1",
        )
    )

    assert calls
    assert calls[0][1][0] == "sess_logged"
    assert calls[0][1][1] == "RuntimeError"
