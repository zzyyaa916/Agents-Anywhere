from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime

from loguru import logger

from agent_server.core.account_usage import (
    MINIMUM,
    ClaudeProbeResult,
    ProbeRefresh,
    UsageCollection,
    UsageIdentity,
    UsageResponse,
    UsageSnapshot,
    merged_claude_windows,
)


def account_sources(sources, row):
    return [
        s
        for s in sources
        if s["user_id"] == row["user_id"]
        and s["account_key"] == row["account_key"]
        and ("claude_code" if s["runtime_type"] == "claude" else "codex")
        == row["runtime"]
    ]


class AccountUsageService:
    def __init__(self, store, rpc, *, clock=time.time):
        self.store, self.rpc, self.clock = store, rpc, clock
        self.probe_connector_id = os.environ.get("AA_CLAUDE_USAGE_PROBE_CONNECTOR_ID")
        self._probe_task = None
        self._probe_token = None

    async def refresh(self, user_id=None):
        # Discovery is read-only identity lookup, never a quota request.
        sources = await self.store.account_usage_sources(user_id)
        for source in sources:
            if source["runtime_type"] == "claude":
                continue  # Claude observations are pushed by events; never poll its usage.
            if not await self.rpc.is_online(source["connector_id"]):
                continue
            if not await self.store.claim_usage_discovery(source, self.clock()):
                continue
            try:
                payload = await self.rpc.request(
                    source["connector_id"],
                    "accountUsage.identify",
                    {"runtimeId": source["runtime_id"]},
                    timeout=30,
                )
                info = UsageIdentity.model_validate(payload)
                expected = (
                    "claude_code" if source["runtime_type"] == "claude" else "codex"
                )
                if info.runtime != expected:
                    continue
                await self.store.save_usage_identity(source, info)
            except Exception as exc:  # noqa: BLE001 -- optional collection must not break sessions
                logger.debug("Account identity unavailable: {}", type(exc).__name__)
        sources = await self.store.account_usage_sources(user_id)
        rows = await self.store.account_usage_rows(user_id)
        for row in rows:
            if row["runtime"] == "claude_code":
                continue
            matching = account_sources(sources, row)
            if not matching:
                continue
            token = await self.store.claim_account_usage(row, self.clock())
            if token is None:
                continue
            result = None
            for source in matching:
                if not await self.rpc.is_online(source["connector_id"]):
                    continue
                try:
                    payload = await self.rpc.request(
                        source["connector_id"],
                        "accountUsage.collect",
                        {
                            "runtimeId": source["runtime_id"],
                            "accountKey": row["account_key"],
                        },
                        timeout=50,
                    )
                    result = UsageCollection.model_validate(payload)
                except Exception as exc:  # noqa: BLE001 -- only exception class is logged
                    logger.debug("Account usage unavailable: {}", type(exc).__name__)
                    result = None
                # A granted attempt is spent even if transport failed: never fan out across devices.
                break
            await self.store.finish_account_usage(row, token, result, self.clock())

    async def _probe_source(self, user_id):
        if not self.probe_connector_id:
            return None
        sources = await self.store.account_usage_sources(user_id)
        return next((s for s in sources if s["connector_id"] == self.probe_connector_id and s["runtime_type"] == "claude"), None)

    async def manual_refresh(self, user_id):
        source = await self._probe_source(user_id)
        if source is None:
            return
        token, state = await self.store.claim_claude_probe(self.clock())
        flight = token or state.get("attempt_id")
        if not flight or state.get("status") != "running":
            return
        if self._probe_token != flight or self._probe_task is None or self._probe_task.done():
            self._probe_token = flight
            self._probe_task = asyncio.create_task(self._execute_probe(token, source, user_id) if token else self._wait_probe(flight))
        await asyncio.shield(self._probe_task)

    async def _wait_probe(self, flight):
        # One waiter per worker, not one database poller per repeated click.
        while True:
            state = await self.store.claude_probe_state(self.clock())
            if state.get("attempt_id") != flight or state.get("status") != "running":
                return
            await asyncio.sleep(0.25)

    async def _execute_probe(self, token, source, user_id):
        result, error = None, None
        try:
            if not await self.rpc.is_online(source["connector_id"]):
                error = "node_offline"
            else:
                payload = await self.rpc.request(source["connector_id"], "accountUsage.probe", {"runtimeId": source["runtime_id"]}, timeout=70)
                result = ClaudeProbeResult.model_validate(payload)
                if result.runtime != "claude_code" or (not result.error_code and (not result.account_key or not result.windows)):
                    error = "unavailable"
                    result = None
                else:
                    error = result.error_code
        except TimeoutError:
            error = "timeout"
        except Exception:  # noqa: BLE001 -- no RPC details or upstream bodies may be logged.
            error = "unavailable" if await self.rpc.is_online(source["connector_id"]) else "node_offline"
        await self.store.finish_claude_probe(token, user_id=user_id, connector_id=source["connector_id"], runtime_id=source["runtime_id"],
            result=result, error_code=error, now=self.clock())

    async def snapshot(self, user_id):
        sources = await self.store.account_usage_sources(user_id)
        rows = await self.store.account_usage_rows(user_id)
        snapshots = []
        represented = set()
        now = self.clock()
        for row in rows:
            matching = account_sources(sources, row)
            parsed = UsageCollection.model_validate(json.loads(row["snapshot_json"])) if row["snapshot_json"] else None
            if row["runtime"] == "claude_code":
                windows = merged_claude_windows(json.loads(row.get("claude_windows_json") or "{}"), parsed.windows if parsed else [], now)
                receipts = [w.received_at for w in windows if w.received_at]
                fetched = max(receipts) if receipts else None
                stale = not bool(windows)
                if not matching and not windows:
                    continue
            else:
                if not matching:
                    continue
                windows = parsed.windows if parsed else []
                fetched = parsed.fetched_at if parsed else None
                age = now - fetched.timestamp() if fetched else float("inf")
                stale = bool(row["failures"]) or parsed is None or parsed.stale or age > MINIMUM[row["runtime"]] * 2
            represented.add(row["runtime"])
            snapshots.append(UsageSnapshot(runtime=row["runtime"], account_key=row["account_key"], account_label=row["account_key"][:8],
                plan_type=parsed.plan_type if parsed else None, windows=windows, fetched_at=fetched, stale=stale,
                error_code=None if row["runtime"] == "claude_code" else parsed.error_code if parsed else "unavailable",
                next_attempt_at=row["next_attempt_at"], bindings=[{"connector_id": s["connector_id"], "runtime_id": s["runtime_id"]} for s in matching]))
        state = await self.store.claude_probe_state(now)
        enabled = await self._probe_source(user_id) is not None
        refresh = ProbeRefresh(status=state.get("status", "idle") if enabled else "disabled",
            next_allowed_at=datetime.fromtimestamp(state["lease_until"] if state.get("status") == "running" else state["next_allowed_at"], UTC)
                if enabled and (state.get("lease_until") if state.get("status") == "running" else state.get("next_allowed_at")) else None,
            completed_at=datetime.fromtimestamp(state["last_success_at"], UTC) if enabled and state.get("last_success_at") else None,
            error_code=state.get("error_code") if enabled else "probe_not_configured")
        return UsageResponse(snapshots=snapshots, unavailable=[r for r in ("codex", "claude_code") if r not in represented],
            server_time=datetime.fromtimestamp(now, UTC).isoformat(), refresh=refresh)

    async def run(self):
        while True:
            try:
                await self.refresh()
            except Exception as exc:  # noqa: BLE001 -- scheduler stays available after transient failures
                logger.debug(
                    "Account usage scheduling unavailable: {}", type(exc).__name__
                )
            await asyncio.sleep(15)
