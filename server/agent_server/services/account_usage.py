from __future__ import annotations

import asyncio
import json
import time

from loguru import logger

from agent_server.core.account_usage import (
    MINIMUM,
    UsageCollection,
    UsageIdentity,
    UsageResponse,
    UsageSnapshot,
)
from agent_server.core.utc import utc_now


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

    async def refresh(self, user_id=None):
        # Discovery is read-only identity lookup, never a quota request.
        sources = await self.store.account_usage_sources(user_id)
        for source in sources:
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

    async def snapshot(self, user_id):
        sources = await self.store.account_usage_sources(user_id)
        rows = await self.store.account_usage_rows(user_id)
        snapshots = []
        represented = set()
        now = self.clock()
        for row in rows:
            matching = account_sources(sources, row)
            if not matching:
                continue
            represented.add(row["runtime"])
            parsed = (
                UsageCollection.model_validate(json.loads(row["snapshot_json"]))
                if row["snapshot_json"]
                else None
            )
            age = (
                now - parsed.fetched_at.timestamp()
                if parsed and parsed.fetched_at
                else float("inf")
            )
            stale = (
                bool(row["failures"])
                or parsed is None
                or parsed.stale
                or age > MINIMUM[row["runtime"]] * 2
            )
            snapshots.append(
                UsageSnapshot(
                    runtime=row["runtime"],
                    account_key=row["account_key"],
                    account_label=row["account_key"][:8],
                    plan_type=parsed.plan_type if parsed else None,
                    windows=parsed.windows if parsed else [],
                    fetched_at=parsed.fetched_at if parsed else None,
                    stale=stale,
                    error_code=parsed.error_code if parsed else "unavailable",
                    next_attempt_at=row["next_attempt_at"],
                    bindings=[
                        {
                            "connector_id": s["connector_id"],
                            "runtime_id": s["runtime_id"],
                        }
                        for s in matching
                    ],
                )
            )
        return UsageResponse(
            snapshots=snapshots,
            unavailable=[r for r in ("codex", "claude_code") if r not in represented],
            server_time=utc_now(),
        )

    async def run(self):
        while True:
            try:
                await self.refresh()
            except Exception as exc:  # noqa: BLE001 -- scheduler stays available after transient failures
                logger.debug(
                    "Account usage scheduling unavailable: {}", type(exc).__name__
                )
            await asyncio.sleep(15)
