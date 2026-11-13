from __future__ import annotations

import hashlib
import json

from loguru import logger

from agent_server.core.project_directories import (
    ProjectNameConflictError,
    project_directory,
)


async def create_project_directory(payload, *, user_id, store, manager):
    connector = await store.get_connector(payload.connectorId)
    if connector.userId != user_id:
        raise KeyError(payload.connectorId)
    target = project_directory(payload.workspacePath, payload.name, connector.deviceOs)
    async with store.connector_lifecycle(payload.connectorId):
        # A duplicate request must reuse the committed project without adopting arbitrary files.
        projects = await store.list_projects(user_id=user_id)
        for project in projects:
            if (
                project.connectorId == payload.connectorId
                and project.workspacePath == target
                and project.name == payload.name
            ):
                return project
            if project.name == payload.name:
                raise ProjectNameConflictError(payload.name)
        operation = hashlib.sha256(
            json.dumps([user_id, payload.connectorId, target]).encode()
        ).hexdigest()
        request = {
            "connectorId": payload.connectorId,
            "operationId": operation,
            "parentPath": payload.workspacePath,
            "name": payload.name,
        }
        result = await manager.request(
            payload.connectorId, "project.directory.prepare", request, timeout=30
        )
        if not isinstance(result.get("path"), str) or not result.get("receipt"):
            raise ValueError("工作设备未确认项目目录")
        plan = {**request, "receipt": result["receipt"]}
        try:
            project = await store.create_project(
                user_id=user_id,
                connector_id=payload.connectorId,
                name=payload.name,
                workspace_path=result["path"],
                manually_created=True,
            )
        except Exception:
            try:
                await manager.request(
                    payload.connectorId, "project.directory.cancel", plan, timeout=10
                )
            except Exception:  # noqa: BLE001 -- only an empty, receipted directory may be rolled back.
                logger.warning(
                    "Project creation rollback incomplete operation={}", operation
                )
            raise
        try:
            await manager.request(
                payload.connectorId, "project.directory.release", plan, timeout=10
            )
        except Exception:  # noqa: BLE001 -- the project is committed; do not report it as failed.
            logger.warning(
                "Project creation receipt release incomplete operation={}", operation
            )
        return project
