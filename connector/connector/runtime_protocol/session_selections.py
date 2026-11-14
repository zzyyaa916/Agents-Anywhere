"""Persist successful explicit session choices separately from native observations."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager

from connector.runtime_protocol.host import RuntimeHostClient


class SessionSelectionStore:
    def __init__(self, runtime: str, host: RuntimeHostClient):
        self.runtime = runtime
        self.host = host
        self.lock = asyncio.Lock()
        self.changes: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def change(self, session_id: str):
        async with self.changes.setdefault(session_id, asyncio.Lock()):
            yield

    async def read(self, session_id: str) -> dict[str, str | None]:
        saved = await self.host.sync_state_read(f"{self.runtime}/session-selections/{session_id}")
        if saved is None:
            return {}
        selections = saved.get("selections")
        if not isinstance(selections, Mapping) or any(
            key not in {"model", "permission"} or (value is not None and not isinstance(value, str))
            for key, value in selections.items()
        ):
            raise ValueError("invalid_saved_session_selections")
        return dict(selections)

    async def resolve(self, session_id: str, incoming: Mapping[str, str | None] | None):
        saved = await self.read(session_id)
        if not saved:
            return incoming
        return {**saved, **dict(incoming or {})}

    async def for_turn(self, session_id: str, reported: Mapping[str, str | None] | None):
        saved = await self.read(session_id)
        if not saved:
            return reported
        # Existing-turn payloads may contain stale Server observations, not user edits.
        return {**dict(reported or {}), **saved}

    async def observed(self, session_id: str, reported: Mapping[str, str | None] | None):
        saved = await self.read(session_id)
        if not saved and reported is None:
            return None
        merged = {**saved, **dict(reported or {})}
        # Only confirmed user choices may be presented as this session's selected model.
        if await self.model_is_confirmed(session_id):
            merged["model"] = saved["model"]
        else:
            merged.pop("model", None)
        if "permission" in saved and merged.get("permission") is None:
            merged["permission"] = saved["permission"]
        return merged

    async def model_is_confirmed(self, session_id: str) -> bool:
        saved = await self.read(session_id)
        record = await self.host.sync_state_read(f"{self.runtime}/session-selections/{session_id}")
        return bool(isinstance(saved.get("model"), str) and saved["model"].strip() and not (record or {}).get("modelSelectionRequired"))

    async def require_reselection(self, session_id: str) -> None:
        async with self.lock:
            saved = await self.read(session_id)
            await self.host.sync_state_write(
                f"{self.runtime}/session-selections/{session_id}",
                {"selections": saved, "modelSelectionRequired": True},
            )

    async def remember(self, session_id: str, incoming: Mapping[str, str | None] | None) -> None:
        explicit = {key: value for key, value in (incoming or {}).items() if key in {"model", "permission"}}
        if not explicit:
            return
        # A missing/blank model is never a request to clear the pin back to the runtime default.
        if "model" in explicit and (not isinstance(explicit["model"], str) or not explicit["model"].strip()):
            explicit.pop("model", None)
        if not explicit:
            return
        async with self.lock:
            saved = await self.read(session_id)
            record = await self.host.sync_state_read(f"{self.runtime}/session-selections/{session_id}")
            blocked = bool((record or {}).get("modelSelectionRequired"))
            updated = {**saved, **explicit}
            required = blocked and "model" not in explicit
            if "model" in explicit:
                required = False
            if updated != saved or required != blocked:
                await self.host.sync_state_write(
                    f"{self.runtime}/session-selections/{session_id}",
                    {"selections": updated, "modelSelectionRequired": required},
                )
