import asyncio

import pytest
from test_acp_preparation_failure import service

from connector.runtimes.acp.domain.definitions import (
    Workspace,
)
from connector.runtimes.acp.domain.sessions import SessionBinding
from connector.runtimes.acp.infrastructure.projection import Projection


@pytest.mark.parametrize("with_id", [True, False])
def test_late_echo_merges_into_user_position_before_agent_output(with_id):
    projection = Projection("session", "epoch", runtime_type="pi")
    user = projection.begin_prompt("client-1", "question")
    agent = projection.apply(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "answer"},
        }
    )
    echo = {
        "sessionUpdate": "user_message_chunk",
        "content": {"type": "text", "text": "question"},
    }
    if with_id:
        echo["_meta"] = {"aa": {"clientMessageId": "client-1"}}
    merged = projection.apply(echo)
    assert merged["id"] == user["id"]
    assert merged["orderSeq"] < agent["orderSeq"]
    assert merged["content"]["text"] == "question"
    assert merged["source"]["clientMessageId"] == "client-1"
    assert len([row for row in projection.items.values() if row["role"] == "user"]) == 1


def test_identical_text_from_different_client_ids_does_not_merge():
    projection = Projection("session", "epoch", runtime_type="pi")
    first = projection.begin_prompt("one", "same")
    projection.finish()
    second = projection.begin_prompt("two", "same")
    late = projection.apply(
        {
            "sessionUpdate": "user_message_chunk",
            "content": {"type": "text", "text": "same"},
            "_meta": {"aa": {"clientMessageId": "one"}},
        }
    )
    assert late["id"] == first["id"] != second["id"]
    assert len(projection.items) == 2


def test_submit_queues_user_before_adapter_runs_and_echo_is_one_item(tmp_path):
    async def scenario():
        app = service(tmp_path)
        session_id = "session"
        projection = Projection(session_id, "generation", runtime_type="controlled")
        binding = SessionBinding(
            session_id,
            "controlled",
            "fixture",
            Workspace(str(tmp_path), str(tmp_path)),
            "owner",
            "generation",
            agent_session_id="native",
            attachment="attached",
            foreground="idle",
        )
        app._save_binding(binding)
        context = {
            "sessionId": session_id,
            "agentSessionId": "native",
            "generation": "generation",
            "projection": projection,
            "closing": False,
        }
        app.sessions[session_id] = context

        async def run(_context, operation, content, creation_id, blocks=None):
            assert app.store.values("projection")[0]["role"] == "user"
            projection.apply(
                {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "answer"},
                }
            )
            projection.apply(
                {
                    "sessionUpdate": "user_message_chunk",
                    "content": {"type": "text", "text": content},
                    "_meta": {"aa": {"clientMessageId": operation.operation_id}},
                }
            )

        app._run_prompt = run
        await app.submit(session_id, "message", "question")
        facts = [
            __import__("json").loads(row[0])
            for row in app.store.db.execute("SELECT body FROM outbox ORDER BY seq")
        ]
        upserts = [row for row in facts if row.get("method") == "timeline.itemUpsert"]
        assert len(upserts) == 1
        await asyncio.gather(*app.tasks)
        rows = list(projection.items.values())
        assert [
            row["role"] for row in sorted(rows, key=lambda row: row["orderSeq"])
        ] == ["user", "assistant"]
        app.store.close()

    asyncio.run(scenario())
