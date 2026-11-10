from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from agent_server.core.utc import utc_now
from agent_server.infra.db.engine import read_connection
from agent_server.infra.db.schema import task_groups


def decode(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "projectId": row["project_id"],
        "createdAt": row["created_at"],
        "request": json.loads(row["request_json"]),
        **json.loads(row["state_json"]),
    }


class TaskGroupRepositoryMixin:
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
