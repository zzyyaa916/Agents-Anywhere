from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from agent_server.core.account_usage import MINIMUM
from agent_server.infra.db import schema as db
from agent_server.infra.db.engine import read_connection


class AccountUsageRepositoryMixin:
    async def account_usage_sources(self, user_id=None):
        query = (
            select(
                db.device_runtimes.c.connector_id,
                db.device_runtimes.c.runtime_id,
                db.device_runtimes.c.runtime_type,
                db.connectors.c.user_id,
                db.account_usage_sources.c.account_key,
            )
            .select_from(
                db.device_runtimes.join(
                    db.connectors,
                    db.connectors.c.id == db.device_runtimes.c.connector_id,
                ).outerjoin(
                    db.account_usage_sources,
                    and_(
                        db.account_usage_sources.c.connector_id
                        == db.device_runtimes.c.connector_id,
                        db.account_usage_sources.c.runtime_id
                        == db.device_runtimes.c.runtime_id,
                    ),
                )
            )
            .where(
                db.connectors.c.revoked == 0,
                db.device_runtimes.c.runtime_type.in_(["codex", "claude"]),
                db.device_runtimes.c.config_json.is_not(None),
            )
        )
        if user_id is not None:
            query = query.where(db.connectors.c.user_id == user_id)
        async with read_connection(self._engine) as conn:
            return [dict(row) for row in (await conn.execute(query)).mappings()]

    async def claim_usage_discovery(self, source, now):
        key = {name: source[name] for name in ("connector_id", "runtime_id")}
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(db.account_usage_sources).values(**key).on_conflict_do_nothing()
            )
            claimed = await conn.execute(
                update(db.account_usage_sources)
                .where(
                    db.account_usage_sources.c.connector_id == key["connector_id"],
                    db.account_usage_sources.c.runtime_id == key["runtime_id"],
                    db.account_usage_sources.c.discovery_after <= now,
                )
                .values(discovery_after=now + 300)
                .returning(db.account_usage_sources.c.runtime_id)
            )
            return claimed.first() is not None

    async def save_usage_identity(self, source, info):
        async with self._engine.begin() as conn:
            # Unavailable discovery preserves the last known account; explicit logout/auth change clears it.
            if info.account_key is not None or info.error_code in {
                "unsupported_auth",
                "account_unavailable",
            }:
                await conn.execute(
                    update(db.account_usage_sources)
                    .where(
                        db.account_usage_sources.c.connector_id
                        == source["connector_id"],
                        db.account_usage_sources.c.runtime_id == source["runtime_id"],
                    )
                    .values(account_key=info.account_key)
                )
            if info.account_key:
                await conn.execute(
                    insert(db.account_usage_snapshots)
                    .values(
                        user_id=source["user_id"],
                        runtime=info.runtime,
                        account_key=info.account_key,
                    )
                    .on_conflict_do_nothing()
                )

    async def account_usage_rows(self, user_id=None):
        query = select(db.account_usage_snapshots)
        if user_id is not None:
            query = query.where(db.account_usage_snapshots.c.user_id == user_id)
        async with read_connection(self._engine) as conn:
            return [dict(row) for row in (await conn.execute(query)).mappings()]

    async def claim_account_usage(self, row, now):
        token = uuid4().hex
        conditions = [
            db.account_usage_snapshots.c.runtime == row["runtime"],
            db.account_usage_snapshots.c.account_key == row["account_key"],
        ]
        async with self._engine.begin() as conn:
            # One quota budget across owners and workers, even if an account is shared.
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "account-usage:" + row["runtime"] + ":" + row["account_key"]},
            )
            maximum = (
                await conn.execute(
                    select(
                        func.max(db.account_usage_snapshots.c.next_attempt_at),
                        func.max(db.account_usage_snapshots.c.failures),
                    ).where(*conditions)
                )
            ).one()
            if maximum[0] is None or maximum[0] > now:
                return None
            await conn.execute(
                update(db.account_usage_snapshots)
                .where(*conditions)
                .values(
                    next_attempt_at=now + MINIMUM[row["runtime"]],
                    attempt_id=token,
                    failures=maximum[1],
                )
            )
            return token

    async def finish_account_usage(self, row, token, result, now):
        conditions = [
            db.account_usage_snapshots.c.user_id == row["user_id"],
            db.account_usage_snapshots.c.runtime == row["runtime"],
            db.account_usage_snapshots.c.account_key == row["account_key"],
            db.account_usage_snapshots.c.attempt_id == token,
        ]
        async with self._engine.begin() as conn:
            current = (
                (
                    await conn.execute(
                        select(db.account_usage_snapshots)
                        .where(*conditions)
                        .with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if current is None:
                return
            valid = (
                result is not None
                and result.account_key == row["account_key"]
                and result.runtime == row["runtime"]
            )
            ok = (
                valid
                and not result.stale
                and result.fetched_at is not None
                and bool(result.windows)
            )
            failures = 0 if ok else current["failures"] + 1
            delay = (
                MINIMUM[row["runtime"]]
                if ok
                else (300, 900, 1800)[min(failures - 1, 2)]
            )
            next_at = now + delay
            if valid and now < result.next_attempt_at < now + 7 * 86400:
                next_at = max(next_at, result.next_attempt_at)
            values = {
                "next_attempt_at": next_at,
                "failures": failures,
                "attempt_id": None,
            }
            previous = (
                json.loads(current["snapshot_json"])
                if current["snapshot_json"]
                else None
            )
            if (
                valid
                and result.fetched_at is not None
                and result.fetched_at.timestamp() <= now + 30
            ):
                candidate = result.model_dump(mode="json", by_alias=True)
                if previous is None or (candidate.get("fetchedAt") or "") >= (
                    previous.get("fetchedAt") or ""
                ):
                    values["snapshot_json"] = json.dumps(candidate)
            await conn.execute(
                update(db.account_usage_snapshots)
                .where(
                    db.account_usage_snapshots.c.runtime == row["runtime"],
                    db.account_usage_snapshots.c.account_key == row["account_key"],
                    db.account_usage_snapshots.c.attempt_id == token,
                )
                .values(**values)
            )
