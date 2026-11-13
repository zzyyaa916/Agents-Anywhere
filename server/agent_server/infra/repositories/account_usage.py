from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from agent_server.core.account_usage import (
    MINIMUM,
    normalize_probe_state,
    probe_failure,
)
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

    async def _merge_claude_windows(self, conn, user_id, account_key, source, windows, received_at, observation_id=None):
        await conn.execute(insert(db.account_usage_snapshots).values(user_id=user_id, runtime="claude_code", account_key=account_key).on_conflict_do_nothing())
        current = (await conn.execute(select(db.account_usage_snapshots.c.claude_windows_json).where(
            db.account_usage_snapshots.c.user_id == user_id, db.account_usage_snapshots.c.runtime == "claude_code",
            db.account_usage_snapshots.c.account_key == account_key).with_for_update())).scalar_one()
        data = json.loads(current) if current else {}
        for window in windows:
            previous = data.get(window.kind, {}).get(source)
            if previous and datetime.fromisoformat(previous["received_at"]).timestamp() > received_at:
                continue
            if observation_id and previous and previous.get("observation_id") == observation_id:
                continue
            clean = {key: value for key, value in window.model_dump(mode="json", by_alias=True).items()
                     if key in {"kind", "modelScope", "usedPercent", "remainingPercent", "resetsAt", "windowDurationMins"}}
            data.setdefault(window.kind, {})[source] = {"source": source, "window": clean,
                "received_at": datetime.fromtimestamp(received_at, UTC).isoformat(), "observation_id": observation_id}
        await conn.execute(update(db.account_usage_snapshots).where(db.account_usage_snapshots.c.user_id == user_id,
            db.account_usage_snapshots.c.runtime == "claude_code", db.account_usage_snapshots.c.account_key == account_key).values(claude_windows_json=json.dumps(data)))

    async def record_claude_usage_event(self, connector_id, event, *, received_at=None):
        now = time.time() if received_at is None else received_at
        async with self._engine.begin() as conn:
            owner = (await conn.execute(select(db.connectors.c.user_id).join(db.device_runtimes,
                db.connectors.c.id == db.device_runtimes.c.connector_id).where(db.connectors.c.id == connector_id,
                db.connectors.c.revoked == 0, db.device_runtimes.c.runtime_id == event.runtime_id,
                db.device_runtimes.c.runtime_type == "claude", db.device_runtimes.c.config_json.is_not(None)))).scalar_one_or_none()
            if owner is None:
                raise KeyError(connector_id)
            await conn.execute(insert(db.account_usage_sources).values(connector_id=connector_id, runtime_id=event.runtime_id,
                account_key=event.account_key).on_conflict_do_update(index_elements=["connector_id", "runtime_id"], set_={"account_key": event.account_key}))
            await self._merge_claude_windows(conn, owner, event.account_key, "event", event.windows, now, event.event_id)

    async def _locked_claude_probe(self, conn, now):
        await conn.execute(insert(db.claude_usage_probe).values(key="claude", state_json="{}").on_conflict_do_nothing())
        raw = (await conn.execute(select(db.claude_usage_probe.c.state_json).where(db.claude_usage_probe.c.key == "claude").with_for_update())).scalar_one()
        previous = json.loads(raw)
        state = normalize_probe_state(previous, now)
        if state != previous:
            await self._save_claude_probe(conn, state)
        return state

    async def _save_claude_probe(self, conn, state):
        await conn.execute(update(db.claude_usage_probe).where(db.claude_usage_probe.c.key == "claude").values(state_json=json.dumps(state)))

    async def claude_probe_state(self, now):
        async with self._engine.begin() as conn:
            return await self._locked_claude_probe(conn, now)

    async def claim_claude_probe(self, now):
        async with self._engine.begin() as conn:
            state = await self._locked_claude_probe(conn, now)
            if state.get("status") == "running" or state.get("next_allowed_at", 0) > now:
                return None, state
            token = uuid4().hex
            state.update(status="running", attempt_id=token, lease_until=now + 90, error_code=None)
            await self._save_claude_probe(conn, state)
            return token, state

    async def finish_claude_probe(self, token, *, user_id, connector_id, runtime_id, result, error_code, now):
        async with self._engine.begin() as conn:
            state = await self._locked_claude_probe(conn, now)
            if state.get("attempt_id") != token:
                return state
            owned = (await conn.execute(select(db.connectors.c.id).where(db.connectors.c.id == connector_id,
                db.connectors.c.user_id == user_id, db.connectors.c.revoked == 0))).scalar_one_or_none()
            if result is not None and not result.error_code and result.account_key and result.windows and owned:
                await self._merge_claude_windows(conn, user_id, result.account_key, "probe", result.windows, now)
                await conn.execute(insert(db.account_usage_sources).values(connector_id=connector_id, runtime_id=runtime_id,
                    account_key=result.account_key).on_conflict_do_update(index_elements=["connector_id", "runtime_id"], set_={"account_key": result.account_key}))
                state.update(status="success", last_success_at=now, next_allowed_at=now + 300, interval=300,
                             consecutive_429=0, circuit_until=0, error_code=None, attempt_id=None, lease_until=0)
            else:
                state = probe_failure(state, now, error_code or "unavailable",
                    retry_after_seconds=result.retry_after_seconds if result else None,
                    retry_after_at=result.retry_after_at if result else None)
            await self._save_claude_probe(conn, state)
            return state
