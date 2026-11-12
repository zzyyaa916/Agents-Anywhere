from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import delete, insert, or_, select, update

from agent_server.core.history_deletion import (
    BUSY_SESSION_STATUSES,
    HistoryDeletionConflict,
    SessionDeletedError,
    source_key,
)
from agent_server.core.utc import utc_now
from agent_server.infra.db import schema as db
from agent_server.infra.db.engine import read_connection


class HistoryDeletionRepositoryMixin:
    async def history_source_deleted(
        self,
        *,
        session_id: str,
        connector_id: str,
        runtime_id: str | None = None,
        external_session_id: str | None = None,
    ) -> bool:
        key = source_key(connector_id, runtime_id or "", external_session_id)
        conditions = [db.history_deletions.c.session_id == session_id]
        if key:
            conditions.append(db.history_deletions.c.source_key == key)
        async with read_connection(self._engine) as conn:
            return (
                await conn.execute(
                    select(db.history_deletions.c.session_id)
                    .where(or_(*conditions))
                    .limit(1)
                )
            ).first() is not None

    async def history_deletion_target(
        self, object_id: str, *, user_id: str, project: bool
    ) -> tuple[str, list[str]]:
        async with read_connection(self._engine) as conn:
            if project:
                row = (
                    await conn.execute(
                        select(db.projects.c.connector_id, db.projects.c.user_id).where(
                            db.projects.c.id == object_id
                        )
                    )
                ).first()
            else:
                row = (
                    await conn.execute(
                        select(db.sessions.c.connector_id, db.connectors.c.user_id)
                        .join(
                            db.connectors,
                            db.connectors.c.id == db.sessions.c.connector_id,
                        )
                        .where(db.sessions.c.id == object_id)
                    )
                ).first()
            if row is None:
                raise KeyError(object_id)
            if row.user_id != user_id:
                raise PermissionError(object_id)
            query = (
                select(db.sessions.c.id).where(db.sessions.c.project_id == object_id)
                if project
                else select(db.sessions.c.id).where(db.sessions.c.id == object_id)
            )
            return row.connector_id, list((await conn.execute(query)).scalars())

    async def delete_history(
        self,
        object_id: str,
        *,
        user_id: str,
        project: bool,
        expected_count: int | None = None,
        cached_busy: set[str] | None = None,
        device_cleanup: dict | None = None,
    ) -> list[str]:
        connector_id, _ = await self.history_deletion_target(
            object_id, user_id=user_id, project=project
        )
        async with self._engine.begin() as conn:
            # Native insertion shares this lock; a complete project set cannot grow underneath deletion.
            await conn.execute(
                select(db.connectors.c.id)
                .where(db.connectors.c.id == connector_id)
                .with_for_update()
            )
            if project:
                owner = (
                    await conn.execute(
                        select(db.projects.c.user_id)
                        .where(db.projects.c.id == object_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if owner is None:
                    raise KeyError(object_id)
                if owner != user_id:
                    raise PermissionError(object_id)
            predicate = (
                db.sessions.c.project_id == object_id
                if project
                else db.sessions.c.id == object_id
            )
            rows = (
                (
                    await conn.execute(
                        select(db.sessions)
                        .where(predicate)
                        .order_by(db.sessions.c.id)
                        .with_for_update()
                    )
                )
                .mappings()
                .all()
            )
            if not project and not rows:
                raise KeyError(object_id)
            ids = [r["id"] for r in rows]
            if device_cleanup is not None:
                planned = device_cleanup["request"]["sessions"]
                expected = {(r["sessionId"], r.get("externalSessionId"), r.get("cwd")) for r in planned}
                actual = {(r["id"], r["external_session_id"], r["cwd"]) for r in rows}
                if expected != actual:
                    raise HistoryDeletionConflict([], "deletion_count_changed")
            if expected_count is not None and len(ids) != expected_count:
                raise HistoryDeletionConflict([], "deletion_count_changed")
            busy = {r["id"] for r in rows if r["status"] in BUSY_SESSION_STATUSES} | (
                set(ids) & (cached_busy or set())
            )
            if ids:
                busy.update(
                    (
                        await conn.execute(
                            select(db.session_active_runs.c.session_id).where(
                                db.session_active_runs.c.session_id.in_(ids)
                            )
                        )
                    ).scalars()
                )
                busy.update(
                    (
                        await conn.execute(
                            select(db.session_goals.c.session_id).where(
                                db.session_goals.c.session_id.in_(ids),
                                db.session_goals.c.status == "active",
                                db.session_goals.c.ended_at.is_(None),
                            )
                        )
                    ).scalars()
                )
                busy.update(
                    (
                        await conn.execute(
                            select(db.goal_operations.c.session_id).where(
                                db.goal_operations.c.session_id.in_(ids),
                                db.goal_operations.c.state.in_(
                                    ["reserved", "dispatched", "unknown"]
                                ),
                            )
                        )
                    ).scalars()
                )
                # Workflows keep phase in result_json rather than in a SQL column.

                workflows = (
                    await conn.execute(
                        select(
                            db.runtime_workflows.c.session_id,
                            db.runtime_workflows.c.result_json,
                        ).where(db.runtime_workflows.c.session_id.in_(ids))
                    )
                ).all()
                for sid, result in workflows:
                    if json.loads(result).get("phase") not in {
                        "completed",
                        "accepted",
                        "rejected",
                        "cancelled",
                        "failed",
                    }:
                        busy.add(sid)
            if busy:
                raise HistoryDeletionConflict(sorted(busy))
            if project:
                # Also refuse a creation that has reserved the project but has not yet allocated a session.

                workflows = (
                    await conn.execute(
                        select(db.runtime_workflows.c.result_json).where(
                            db.runtime_workflows.c.project_id == object_id,
                            db.runtime_workflows.c.kind == "creation",
                        )
                    )
                ).scalars()
                for result in workflows:
                    if json.loads(result).get("phase") not in {
                        "completed",
                        "accepted",
                        "rejected",
                        "cancelled",
                        "failed",
                    }:
                        raise HistoryDeletionConflict(ids)
            now = utc_now()
            deletion_id = uuid4().hex
            for row in rows:
                await conn.execute(
                    insert(db.history_deletions).values(
                        session_id=row["id"],
                        user_id=user_id,
                        source_key=source_key(
                            row["connector_id"],
                            row["runtime_id"],
                            row["external_session_id"],
                        ),
                        deletion_id=deletion_id,
                        deleted_at=now,
                    )
                )
            if ids:
                await conn.execute(
                    delete(db.connector_terminal_roots).where(
                        db.connector_terminal_roots.c.session_id.in_(ids)
                    )
                )
                await conn.execute(
                    delete(db.runtime_workflows).where(
                        db.runtime_workflows.c.session_id.in_(ids)
                    )
                )
                await conn.execute(delete(db.sessions).where(db.sessions.c.id.in_(ids)))
            if project:
                await conn.execute(
                    delete(db.projects).where(db.projects.c.id == object_id)
                )
            await conn.execute(
                insert(db.history_deletion_audit).values(
                    id=deletion_id,
                    user_id=user_id,
                    object_type="project" if project else "session",
                    object_id=object_id,
                    session_count=len(ids),
                    device_cleanup_json=json.dumps(device_cleanup) if device_cleanup else None,
                    deleted_at=now,
                )
            )
            # Match official Connector deletion: keep SQL rows retryable if external storage fails.
            # Uploads share a session row lock, so no blob write can cross this deletion.
            for sid in ids:
                await self.files.delete_session(sid)
        return ids

    async def pending_history_cleanup(
        self, *, object_id=None, project=None, user_id=None
    ):
        query = select(db.history_deletion_audit).where(
            db.history_deletion_audit.c.cleanup_pending == 1
        )
        if object_id is not None:
            query = query.where(
                db.history_deletion_audit.c.object_id == object_id,
                db.history_deletion_audit.c.object_type
                == ("project" if project else "session"),
            )
        async with read_connection(self._engine) as conn:
            audits = (await conn.execute(query.limit(100))).mappings().all()
            result = []
            for audit in audits:
                if user_id is not None and audit["user_id"] != user_id:
                    raise PermissionError(object_id)
                ids = list(
                    (
                        await conn.execute(
                            select(db.history_deletions.c.session_id).where(
                                db.history_deletions.c.deletion_id == audit["id"]
                            )
                        )
                    ).scalars()
                )
                result.append({**audit, "session_ids": ids})
            return result

    async def mark_device_cleanup_complete(self, deletion_id, plan):
        async with self._engine.begin() as conn:
            await conn.execute(update(db.history_deletion_audit).where(
                db.history_deletion_audit.c.id == deletion_id
            ).values(device_cleanup_json=json.dumps(plan)))

    async def abandon_device_cleanup(self, deletion_id):
        async with self._engine.begin() as conn:
            await conn.execute(update(db.history_deletion_audit).where(
                db.history_deletion_audit.c.id == deletion_id
            ).values(device_cleanup_json=None))

    async def finish_history_cleanup(self, deletion_id):
        async with self._engine.begin() as conn:
            await conn.execute(
                update(db.history_deletion_audit)
                .where(db.history_deletion_audit.c.id == deletion_id)
                .values(cleanup_pending=0, device_cleanup_json=None)
            )

    async def require_history_source_available(
        self, conn, *, session_id, connector_id, runtime_id, external_session_id
    ):
        key = source_key(connector_id, runtime_id, external_session_id)
        conditions = [db.history_deletions.c.session_id == session_id]
        if key is not None:
            conditions.append(db.history_deletions.c.source_key == key)
        if (
            await conn.execute(
                select(db.history_deletions.c.session_id)
                .where(or_(*conditions))
                .limit(1)
            )
        ).first() is not None:
            raise SessionDeletedError(session_id)


    async def history_device_cleanup_plan(self, object_id, *, user_id, project):
        connector_id, ids = await self.history_deletion_target(object_id, user_id=user_id, project=project)
        async with read_connection(self._engine) as conn:
            rows = (await conn.execute(select(db.sessions).where(db.sessions.c.id.in_(ids)))).mappings().all() if ids else []
            projects = (await conn.execute(select(db.projects).where(db.projects.c.connector_id == connector_id))).mappings().all()
            target = next((p for p in projects if p["id"] == object_id), None) if project else None
            if project and target is None:
                raise KeyError(object_id)
            for row in rows:
                if row["external_session_id"]:
                    shared = (await conn.execute(select(db.sessions.c.id).where(
                        db.sessions.c.connector_id == connector_id,
                        db.sessions.c.runtime_id == row["runtime_id"],
                        db.sessions.c.external_session_id == row["external_session_id"],
                        db.sessions.c.id.not_in(ids),
                    ).limit(1))).first()
                    if shared:
                        raise HistoryDeletionConflict([], "shared_native_history")
            protected = [p["workspace_path"] for p in projects if not project or p["id"] != object_id]
            other_cwds = (await conn.execute(select(db.sessions.c.cwd).where(db.sessions.c.connector_id == connector_id, db.sessions.c.id.not_in(ids)))).scalars().all()
            protected.extend(path for path in other_cwds if path)
            return {
                "connectorId": connector_id,
                "projectPath": target["workspace_path"] if target else None,
                "protectedPaths": sorted(set(protected)),
                "sessions": [{"sessionId": r["id"], "runtimeId": r["runtime_id"], "runtime": r["runtime"],
                              "externalSessionId": r["external_session_id"], "cwd": r["cwd"]} for r in rows],
            }


    async def require_workspace_not_deleting(self, conn, connector_id, workspace_path):
        from pathlib import PurePosixPath, PureWindowsPath
        from agent_server.core.history_deletion import SessionDeletedError
        query = select(db.history_deletion_audit.c.device_cleanup_json).where(db.history_deletion_audit.c.cleanup_pending == 1, db.history_deletion_audit.c.device_cleanup_json.is_not(None))
        for raw in (await conn.execute(query)).scalars():
            plan = json.loads(raw)["request"]
            if plan["connectorId"] != connector_id or not plan.get("projectPath"):
                continue
            windows = "\\" in workspace_path or (len(workspace_path) > 1 and workspace_path[1] == ":")
            cls = PureWindowsPath if windows else PurePosixPath
            a, b = cls(workspace_path), cls(plan["projectPath"])
            if a == b or a.is_relative_to(b) or b.is_relative_to(a):
                raise SessionDeletedError("workspace_cleanup_pending")
