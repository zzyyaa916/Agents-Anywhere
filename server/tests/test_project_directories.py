from unittest.mock import AsyncMock

import pytest
from agent_server.core.project_directories import project_directory
from agent_server.infra.connector_rpc import ConnectorOfflineError, ConnectorRpcError
from connector.core.json_kv import JsonKeyValueStore
from connector.server.history_cleanup import HistoryCleanup
from test_connector_deletion import api as api_fixture
from test_connector_deletion import create_device

api = api_fixture


@pytest.mark.parametrize(
    "parent,name,os,expected",
    [
        ("/work", "项目", None, "/work/项目"),
        ("C:\\work", "Demo", "windows", "C:\\work\\Demo"),
        ("\\\\server\\share", "Demo", "windows", "\\\\server\\share\\Demo"),
    ],
)
def test_child_path_uses_device_path_flavor(parent, name, os, expected):
    assert project_directory(parent, name, os) == expected


@pytest.mark.parametrize("name", ["..", ".", "a/b", "a\\b", "CON", "aux.txt", "bad."])
def test_bad_child_names_never_become_paths(name):
    with pytest.raises(ValueError):
        project_directory("/work", name)


def setup(api, tmp_path, monkeypatch):
    client, headers = api
    device = create_device(client, headers)
    parent = tmp_path / "selected"
    parent.mkdir()
    native = type(
        "Native",
        (),
        {
            "prepare_history_deletion": AsyncMock(),
            "delete_session_history": AsyncMock(),
        },
    )()
    worker = HistoryCleanup(
        device,
        lambda _: native,
        kv=JsonKeyValueStore(tmp_path / "kv.json"),
        data_dir=tmp_path / "data",
        home=tmp_path / "home",
    )

    async def request(device_id, method, params, **kw):
        try:
            if method.startswith("project.directory."):
                return await worker.project_directory(method.rsplit(".", 1)[1], params)
            if method == "history.cleanup.prepare":
                return await worker.prepare(params)
            if method == "history.cleanup.commit":
                return await worker.commit(params)
            if method == "history.cleanup.release":
                return await worker.release(params)
            raise AssertionError(method)
        except (OSError, ValueError) as exc:
            raise ConnectorRpcError(type(exc).__name__, str(exc)) from exc

    monkeypatch.setattr(client.app.state.rpc, "request", AsyncMock(side_effect=request))
    return client, headers, device, parent, worker


def test_manual_create_and_delete_keep_selected_parent_and_siblings(
    api, tmp_path, monkeypatch
):
    client, headers, device, parent, _worker = setup(api, tmp_path, monkeypatch)
    (parent / "keep.txt").write_text("parent data")
    body = {"name": "Demo", "connectorId": device, "workspacePath": str(parent)}
    response = client.post("/projects", headers=headers, json=body)
    assert response.status_code == 200, response.text
    project = response.json()["project"]
    assert (
        project["workspacePath"] == str(parent / "Demo") and (parent / "Demo").is_dir()
    )
    again = client.post("/projects", headers=headers, json=body)
    assert again.json()["project"]["id"] == project["id"]
    (parent / "Demo/code.py").write_text("project data")
    deleted = client.delete(
        "/projects/" + project["id"] + "/contents?expectedSessionCount=0",
        headers=headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert (
        not (parent / "Demo").exists()
        and (parent / "keep.txt").read_text() == "parent data"
    )


def test_existing_directory_and_offline_creation_leave_no_project(
    api, tmp_path, monkeypatch
):
    client, headers, device, parent, _worker = setup(api, tmp_path, monkeypatch)
    (parent / "existing").mkdir()
    (parent / "existing/code.py").write_text("keep")
    response = client.post(
        "/projects",
        headers=headers,
        json={"name": "existing", "connectorId": device, "workspacePath": str(parent)},
    )
    assert response.status_code == 409
    assert client.get("/projects", headers=headers).json()["projects"] == []
    assert (parent / "existing/code.py").read_text() == "keep"


def test_failed_database_registration_only_rolls_back_empty_owned_folder(
    api, tmp_path, monkeypatch
):
    client, headers, device, parent, _worker = setup(api, tmp_path, monkeypatch)
    monkeypatch.setattr(
        client.app.state.store,
        "create_project",
        AsyncMock(side_effect=ValueError("database validation failed")),
    )
    response = client.post(
        "/projects",
        headers=headers,
        json={"name": "Demo", "connectorId": device, "workspacePath": str(parent)},
    )
    assert response.status_code == 422
    assert parent.is_dir() and not (parent / "Demo").exists()


def test_offline_creation_does_not_register_or_create_a_folder(
    api, tmp_path, monkeypatch
):
    client, headers, device, parent, _worker = setup(api, tmp_path, monkeypatch)
    monkeypatch.setattr(
        client.app.state.rpc,
        "request",
        AsyncMock(side_effect=ConnectorOfflineError("offline")),
    )
    response = client.post(
        "/projects",
        headers=headers,
        json={"name": "Demo", "connectorId": device, "workspacePath": str(parent)},
    )
    assert response.status_code == 503
    assert not (parent / "Demo").exists()
    assert client.get("/projects", headers=headers).json()["projects"] == []
