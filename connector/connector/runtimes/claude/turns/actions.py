from __future__ import annotations

import asyncio
import secrets
from collections.abc import Mapping
from dataclasses import dataclass

from connector.logging import logger
from connector.runtime_protocol import (
    RuntimeAttachment,
    RuntimeInvalidRequestError,
    RuntimeOperationResult,
    RuntimeSessionStateCache,
)
from connector.runtimes.claude.domain.session import ClaudeExecution, ClaudeSession
from connector.runtimes.claude.notifications.projector import (
    ClaudeNotificationProjector,
)
from connector.runtimes.claude.sdk.client import interrupt_client, query_client
from connector.runtimes.claude.sdk.events import interrupted_terminal_event
from connector.runtimes.claude.sessions.cache import ClaudeSessionStore
from connector.runtimes.claude.turns.attachments import (
    content_with_attachment_notes,
    materialize_claude_attachments,
)
from connector.runtimes.claude.turns.interactions import ClaudeInteractionController
from connector.runtimes.claude.turns.lifecycle import ClaudeTurnRunner
from connector.runtimes.claude.turns.selections import ClaudeSelectionController


@dataclass(slots=True)
class ClaudeTurnActionHandler:
    session_states: RuntimeSessionStateCache
    session_store: ClaudeSessionStore
    notifications: ClaudeNotificationProjector
    selections: ClaudeSelectionController
    interactions: ClaudeInteractionController
    runner: ClaudeTurnRunner

    async def stop(self) -> None:
        self.runner.stopping = True
        for session in self.session_store.sessions():
            executions = (session.queued_execution, session.execution)
            for execution in executions:
                if execution is not None:
                    execution.interrupt_source = "claude.runtime.stop"
                    execution.interrupt_reason = "runtime_stopped"
            for execution in executions:
                if execution is not None:
                    await self.interrupt_execution(
                        session=session,
                        execution=execution,
                        source="claude.runtime.stop",
                        reason="runtime_stopped",
                    )
        await self.runner.stop()

    async def start_turn(
        self,
        session_id: str,
        external_session_id: str | None,
        content: str,
        selections: Mapping[str, str | None] | None = None,
        attachments: tuple[RuntimeAttachment, ...] = (),
        client_message_id: str | None = None,
        cwd: str | None = None,
    ) -> RuntimeOperationResult:
        session = self.session_for(session_id, external_session_id, cwd)
        try:
            effective_selections = await self.selections.effective_selections(
                session_id,
                selections,
            )
        except RuntimeInvalidRequestError as exc:
            return RuntimeOperationResult(
                ok=False,
                code="claude_invalid_selection",
                message=str(exc),
            )

        session.selections = effective_selections
        entered = await self.runner.host.prepare_planning_turn(session_id, external_session_id)
        effective_selections = dict(session.selections)
        if entered and not content.strip() and not attachments:
            return RuntimeOperationResult(ok=True, result={"externalSessionId": external_session_id, "created": True, "messageAccepted": False})
        async with session.execution_lock:
            if session.execution is not None:
                return RuntimeOperationResult(
                    ok=False,
                    code="claude_turn_already_running",
                    message="Claude runtime already has an active turn for this session",
                )
            execution = ClaudeExecution(
                turn_id=f"turn_claude_{secrets.token_urlsafe(12)}"
            )
            session.execution = execution
            session.selections = effective_selections
            try:
                await self.notifications.session_state.session_state_update(
                    session,
                    "waiting",
                    selections=session.selections,
                    metadata={"source": "claude.turn.start"},
                )
                execution.task = asyncio.create_task(
                    self.runner.drive_turn(
                        session=session,
                        execution=execution,
                        content=content,
                        attachments=attachments,
                        client_message_id=client_message_id,
                    )
                )
            except BaseException:
                session.execution = None
                execution.finished.set()
                raise
        return RuntimeOperationResult(
            ok=True,
            result={
                "turnId": execution.turn_id,
                "externalSessionId": session.external_session_id,
            },
        )

    async def steer_turn(
        self,
        *,
        session_id: str,
        external_session_id: str | None,
        content: str,
        attachments: tuple[RuntimeAttachment, ...] = (),
        client_message_id: str | None = None,
    ) -> RuntimeOperationResult:
        """Inject a supplement into the live turn; it lands at the next tool boundary."""
        from connector.core.fork_profile import claude_steering_enabled

        if not claude_steering_enabled():
            return RuntimeOperationResult(
                ok=False,
                code="claude_steering_disabled",
                message="Claude mid-turn supplements are disabled on this connector",
            )
        session = self.session_store.get(session_id)
        if session is None:
            return RuntimeOperationResult(
                ok=False,
                code="claude_no_active_turn",
                message="session has no active Claude turn",
            )
        # Snapshot the execution and its live client under the lock; the SDK round
        # trip itself must never run while holding the per-session execution lock.
        async with session.execution_lock:
            execution = session.execution
            if execution is None or execution.client is None:
                return RuntimeOperationResult(
                    ok=False,
                    code="claude_no_active_turn",
                    message="session has no active Claude turn",
                )
            if client_message_id and client_message_id in execution.steered_ids:
                # Idempotent: a retry or reconnect must not run the same instruction twice.
                return RuntimeOperationResult(
                    ok=True,
                    result={
                        "turnId": execution.turn_id,
                        "deduplicated": True,
                        "externalSessionId": session.external_session_id,
                    },
                )
            # A pending approval owns the turn; a supplement never bypasses it.
            if any(
                notice.response_required
                for notice in self.runner.notifications.notices.current_for_session(
                    session_id
                )
            ):
                return RuntimeOperationResult(
                    ok=False,
                    code="claude_steer_blocked_approval",
                    message="resolve the pending approval before supplementing this turn",
                )
            turn_id = execution.turn_id
            target_client = execution.client
            if client_message_id:
                execution.steered_ids.add(client_message_id)
        try:
            materialized = await materialize_claude_attachments(
                self.runner.host,
                session_id,
                attachments,
                self.runner.notifications.notices,
            )
            effective_content = content_with_attachment_notes(content, materialized)
            attachment_mappings = tuple(
                attachment.to_mapping() for attachment in materialized
            )
            supplement_item = self.runner.timeline.message_item(
                session=session,
                turn_id=turn_id,
                role="user",
                text=content,
                event="claude.turn.user.supplement",
                client_message_id=client_message_id,
                attachments=attachment_mappings,
            )
            await self.runner.publish_user_message(
                session=session,
                item=supplement_item,
                content=content,
                attachments=attachment_mappings,
                client_message_id=client_message_id,
                native_message_id=None,
            )
            await query_client(target_client, effective_content)
        except Exception as exc:  # noqa: BLE001 -- surface a clean error, never silently drop
            if client_message_id:
                async with session.execution_lock:
                    execution.steered_ids.discard(client_message_id)
            logger.debug(
                "Claude steer injection failed session_id={} error={}",
                session_id,
                type(exc).__name__,
            )
            return RuntimeOperationResult(
                ok=False,
                code="claude_steer_failed",
                message=str(exc),
            )
        return RuntimeOperationResult(
            ok=True,
            result={
                "turnId": turn_id,
                "externalSessionId": session.external_session_id,
                "messageAccepted": True,
            },
        )

    async def interrupt_session(
        self,
        session_id: str,
        reason: str | None = None,
    ) -> RuntimeOperationResult:
        session = self.session_store.get(session_id)
        if session is None:
            return RuntimeOperationResult(
                ok=True,
                result={"interrupted": False, "alreadyStopped": True},
            )
        async with session.execution_lock:
            execution = session.execution
            if execution is None:
                return RuntimeOperationResult(
                    ok=True,
                    result={"interrupted": False, "alreadyStopped": True},
                )
            execution.interrupt_source = "claude.session.interrupt"
            execution.interrupt_reason = reason
            queued = session.queued_execution
        if queued is not None:
            await self.interrupt_execution(
                session=session,
                execution=queued,
                source="claude.session.interrupt",
                reason=reason,
            )
        await self.interrupt_execution(
            session=session,
            execution=execution,
            source="claude.session.interrupt",
            reason=reason,
        )
        return RuntimeOperationResult(
            ok=True,
            result={"interrupted": True, "alreadyStopped": False},
        )

    async def interrupt_execution(
        self,
        session: ClaudeSession,
        execution: ClaudeExecution,
        source: str,
        reason: str | None,
    ) -> None:
        """Stop one owned execution and wait until all of its work has exited."""

        execution.interrupt_source = source
        execution.interrupt_reason = reason
        try:
            await interrupt_client(execution.client)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Claude SDK interrupt raced with shutdown session_id={}",
                session.session_id,
            )
        task = execution.task
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await self.runner.finish_execution(
            session=session,
            execution=execution,
            terminal=interrupted_terminal_event(reason),
        )

    def has_active_turn(self, session_id: str) -> bool:
        session = self.session_store.get(session_id)
        return session is not None and session.execution is not None

    def session_for(
        self,
        session_id: str,
        external_session_id: str | None,
        cwd: str | None,
    ) -> ClaudeSession:
        return self.session_store.ensure(
            session_id=session_id,
            external_session_id=external_session_id,
            cwd=cwd,
        )
