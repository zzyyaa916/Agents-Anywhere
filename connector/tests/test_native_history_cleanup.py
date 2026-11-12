from uuid import uuid4

import pytest

from connector.runtimes.claude.history.deletion import cleanup_claude_history


def test_claude_deletes_selected_transcript_and_assets_preserving_other_sessions_and_auth(tmp_path):
    sid, other = str(uuid4()), str(uuid4())
    project = tmp_path / "projects" / "test"; project.mkdir(parents=True)
    (project / (sid + ".jsonl")).write_text("selected")
    (project / (other + ".jsonl")).write_text("other")
    (project / sid).mkdir(); (project / sid / "subagent.jsonl").touch()
    (tmp_path / ".credentials.json").write_text("synthetic auth")
    assert cleanup_claude_history(tmp_path, sid) == {"prepared": True}
    assert (project / sid).exists()
    assert cleanup_claude_history(tmp_path, sid, commit=True) == {"complete": True}
    assert not (project / sid).exists() and not (project / (sid + ".jsonl")).exists()
    assert (project / (other + ".jsonl")).read_text() == "other"
    assert (tmp_path / ".credentials.json").exists()
    assert cleanup_claude_history(tmp_path, sid, commit=True) == {"complete": True}


def test_claude_rejects_traversal_and_project_links(tmp_path):
    with pytest.raises(ValueError): cleanup_claude_history(tmp_path, "../../profile", commit=True)
    (tmp_path / "projects").mkdir(); (tmp_path / "other").mkdir()
    (tmp_path / "projects/link").symlink_to(tmp_path / "other", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"): cleanup_claude_history(tmp_path, str(uuid4()), commit=True)
    assert (tmp_path / "other").exists()
