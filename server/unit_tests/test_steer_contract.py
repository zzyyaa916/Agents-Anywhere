import pytest
from pydantic import ValidationError

from agent_server.core.models import SessionSteerRequest


def test_steer_rejects_empty_content():
    with pytest.raises(ValidationError):
        SessionSteerRequest(content="")


def test_steer_accepts_text_with_attachments():
    request = SessionSteerRequest(
        content="continue",
        attachments=[{"fileId": "file_1"}],
        clientMessageId="msg_1",
    )
    assert request.content == "continue"
    assert request.attachments[0].fileId == "file_1"
