from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select, update

from agent_server.core.session_quota import effective_quota
from agent_server.infra.db import schema as db
from agent_server.infra.db.engine import read_connection


class SessionQuotaRepositoryMixin:
    async def session_quota(self, session_id):
        async with read_connection(self._engine) as conn:
            row = (
                await conn.execute(
                    select(db.sessions.c.quota_json).where(
                        db.sessions.c.id == session_id
                    )
                )
            ).first()
        if row is None:
            raise KeyError(session_id)
        return effective_quota(json.loads(row[0]) if row[0] else None)

    async def record_session_quota(self, session):
        owner = await self.get_session_user_id(session.id)
        sources = await self.account_usage_sources(owner)
        source = next(
            (
                s
                for s in sources
                if s["connector_id"] == session.connectorId
                and s["runtime_id"] == session.runtimeId
            ),
            None,
        )
        key = source["account_key"] if source else None
        runtime = "claude_code" if session.runtime == "claude" else session.runtime
        rows = await self.account_usage_rows(owner)
        row = next(
            (r for r in rows if r["runtime"] == runtime and r["account_key"] == key),
            None,
        )
        now = datetime.now(UTC)
        windows = []
        if row and row["snapshot_json"]:
            snapshot = json.loads(row["snapshot_json"])
            windows = [
                w
                for w in snapshot.get("windows", [])
                if w["remainingPercent"] == 0
                and datetime.fromisoformat(w["resetsAt"]) > now
            ]
        previous = await self.session_quota(session.id)
        quota = {
            "state": "limited",
            "accountKey": key,
            "windows": [w["kind"] for w in windows],
            "resetsAt": max((w["resetsAt"] for w in windows), default=None),
            "externalSessionId": session.externalSessionId,
            "interruptedAt": previous["interruptedAt"] if previous and previous.get("state") == "limited" else now.isoformat(),
        }
        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(db.sessions)
                .where(db.sessions.c.id == session.id)
                .values(quota_json=json.dumps(quota), status="limited")
            )
            if not result.rowcount:
                raise KeyError(session.id)
            await self._bump_session(conn, session.id)
        return quota

    async def finish_session_quota(
        self, session_id, *, stopped=False, resumed=False, expected=None
    ):
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    select(db.sessions.c.quota_json)
                    .where(db.sessions.c.id == session_id)
                    .with_for_update()
                )
            ).first()
            if row is None:
                raise KeyError(session_id)
            if not row[0]:
                return None
            quota = json.loads(row[0])
            if expected and quota.get("interruptedAt") != expected.get("interruptedAt"):
                return effective_quota(quota)
            quota["state"] = "stopped" if stopped else "resumed" if resumed else "ready"
            await conn.execute(
                update(db.sessions)
                .where(db.sessions.c.id == session_id)
                .values(quota_json=json.dumps(quota))
            )
            await conn.execute(
                update(db.sessions)
                .where(
                    db.sessions.c.id == session_id, db.sessions.c.status == "limited"
                )
                .values(status="idle")
            )
            await self._bump_session(conn, session_id)
        return quota
