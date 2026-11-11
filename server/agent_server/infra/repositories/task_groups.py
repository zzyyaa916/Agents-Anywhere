from __future__ import annotations

import json
from typing import Any

from sqlalchemy import cast, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert

from agent_server.core.utc import utc_now
from agent_server.infra.db.engine import read_connection
from agent_server.infra.db.schema import projects, task_groups
from agent_server.infra.repositories.projects import _clean_workspace_path


def decode(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "projectId": row["project_id"],
        "createdAt": row["created_at"],
        "request": json.loads(row["request_json"]),
        **json.loads(row["state_json"]),
    }


class TaskGroupRepositoryMixin:
    async def _task_group_session_project(
        self,
        conn,
        *,
        session_id: str,
        connector_id: str,
        cwd: str | None,
        user_id: str | None = None,
    ) -> str | None:
        if not session_id.startswith("sess_tg_") or not cwd:
            return None
        query = (
            select(task_groups.c.project_id, task_groups.c.state_json)
            .join(projects, projects.c.id == task_groups.c.project_id)
            .where(
                projects.c.connector_id == connector_id,
                projects.c.user_id == task_groups.c.user_id,
                cast(task_groups.c.state_json, JSONB)["candidates"].contains(
                    [{"sessionId": session_id}]
                ),
            )
        )
        if user_id is not None:
            query = query.where(
                task_groups.c.user_id == user_id, projects.c.user_id == user_id
            )
        for row in (await conn.execute(query)).mappings():
            state = json.loads(row["state_json"])
            for slot, candidate in enumerate(state.get("candidates", [])):
                paths = state.get("paths", [])
                if (
                    candidate.get("sessionId") == session_id
                    and slot < len(paths)
                    and _clean_workspace_path(paths[slot], None)[1]
                    == _clean_workspace_path(cwd, None)[1]
                ):
                    return row["project_id"]
        return None

    async def get_task_group_session_project(
        self, *, session_id: str, connector_id: str, cwd: str | None, user_id: str
    ) -> str | None:
        async with read_connection(self._engine) as conn:
            return await self._task_group_session_project(
                conn,
                session_id=session_id,
                connector_id=connector_id,
                cwd=cwd,
                user_id=user_id,
            )

    async def put_task_group(
        self, identifier: str, *, user_id: str, request: dict, state: dict
    ) -> dict:
        text = json.dumps(request, sort_keys=True, ensure_ascii=False)
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(task_groups)
                .values(
                    id=identifier,
                    user_id=user_id,
                    project_id=request["projectId"],
                    created_at=utc_now(),
                    request_json=text,
                    state_json=json.dumps(state, ensure_ascii=False),
                )
                .on_conflict_do_nothing()
            )
        result = await self.get_task_group(identifier, user_id=user_id)
        if result["request"] != request:
            raise ValueError("Operation identity already used for another request")
        return result

    async def get_task_group(self, identifier: str, *, user_id: str) -> dict:
        async with read_connection(self._engine) as conn:
            row = (
                (
                    await conn.execute(
                        select(task_groups).where(
                            task_groups.c.id == identifier,
                            task_groups.c.user_id == user_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise KeyError(identifier)
        return decode(row)

    async def list_task_groups(self, project_id: str, *, user_id: str) -> list[dict]:
        async with read_connection(self._engine) as conn:
            rows = (
                (
                    await conn.execute(
                        select(task_groups)
                        .where(
                            task_groups.c.project_id == project_id,
                            task_groups.c.user_id == user_id,
                        )
                        .order_by(task_groups.c.created_at.desc())
                        .limit(30)
                    )
                )
                .mappings()
                .all()
            )
        return [decode(row) for row in rows]

    async def change_task_group(
        self,
        identifier: str,
        *,
        user_id: str,
        patch: dict,
        slot: int | None = None,
        expected: str | None = None,
    ) -> bool:
        async with self._engine.begin() as conn:
            row = (
                (
                    await conn.execute(
                        select(task_groups)
                        .where(
                            task_groups.c.id == identifier,
                            task_groups.c.user_id == user_id,
                        )
                        .with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise KeyError(identifier)
            state = json.loads(row["state_json"])
            target = state if slot is None else state["candidates"][slot]
            if expected is not None and target["phase"] != expected:
                return False
            target.update(patch)
            await conn.execute(
                update(task_groups)
                .where(task_groups.c.id == identifier)
                .values(state_json=json.dumps(state, ensure_ascii=False))
            )
        return True
