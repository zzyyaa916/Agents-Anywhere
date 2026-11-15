import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "timeline_repair", Path(__file__).parents[1] / "scripts/reorder_session_timeline.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def item(identifier, seq, created="2026-11-15T00:00:00+00:00"):
    return SimpleNamespace(id=identifier, orderSeq=seq, createdAt=created)


def test_plan_stable_created_order_and_disjoint_temporary_int32_values():
    items = [
        item("assistant", 2),
        item("user", 5, "2026-11-14T23:00:00+00:00"),
        item("tie", 1),
    ]
    changes, offset = module.plan(items)
    assert [row.id for row, _, _ in changes] == ["user", "tie", "assistant"]
    assert [final for _, _, final in changes] == [1, 2, 3]
    temporary = {value for _, value, _ in changes}
    assert not temporary & {1, 2, 3, 5}
    assert all(module.MIN <= value <= module.MAX for value in temporary)
    assert all(value == row.orderSeq + offset for row, value, _ in changes)


def test_no_safe_offset_stops_without_overflow():
    with pytest.raises(ValueError, match="no_safe_int32_temporary_space"):
        module.plan([item("min", module.MIN), item("max", module.MAX)])
    with pytest.raises(ValueError, match="duplicate_existing_order_seq"):
        module.plan([item("one", 1), item("two", 1)])
    assert module.plan([]) == ([], 0)


def test_backup_failure_cannot_overwrite_existing_export(tmp_path):
    path = tmp_path / "backup.json"
    path.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        module.backup_rows(path, "session", [])
    assert path.read_bytes() == b"existing"
