from __future__ import annotations

import hashlib
from typing import Any, Protocol

from agent_server.core.models import SessionCreateAndStartRequest
from agent_server.core.task_groups import TaskGroupCreate, TaskGroupHandoff
from agent_server.services.session_run import SessionRunService


class TaskGroupRepository(Protocol):
    async def get_project(self, project_id: str, *, user_id: str) -> Any: ...
    async def ensure_project_for_workspace(self, **values: Any) -> Any: ...
    async def get_session(self, session_id: str, *, user_id: str) -> Any: ...
    async def get_active_run(self, session_id: str) -> dict | None: ...
    async def list_timeline_latest(self, *, session_id: str, limit: int) -> Any: ...
    async def put_task_group(self, identifier: str, **values: Any) -> dict: ...
    async def get_task_group(self, identifier: str, *, user_id: str) -> dict: ...
    async def list_task_groups(
        self, project_id: str, *, user_id: str
    ) -> list[dict]: ...
    async def change_task_group(self, identifier: str, **values: Any) -> bool: ...


class TaskGroupRpc(Protocol):
    async def request(
        self, connector_id: str, method: str, params: dict, *, timeout: float
    ) -> Any: ...


def group_id(user_id: str, operation_id: str) -> str:
    return hashlib.sha256(f"{user_id}:{operation_id}".encode()).hexdigest()[:40]


class TaskGroupService:
    def __init__(
        self, store: TaskGroupRepository, rpc: TaskGroupRpc, sessions: SessionRunService
    ):
        self.store, self.rpc, self.sessions = store, rpc, sessions

    async def create(self, payload: TaskGroupCreate, *, user_id: str) -> dict:
        project = await self.store.get_project(payload.projectId, user_id=user_id)
        identifier = group_id(user_id, payload.operationId)
        row = await self.store.put_task_group(
            identifier,
            user_id=user_id,
            request=payload.model_dump(mode="json"),
            state={
                "phase": "preparing",
                "selected": None,
                "candidates": [
                    {"phase": "pending", "sessionId": None} for _ in payload.candidates
                ],
            },
        )
        if row["phase"] == "preparing":
            prepared = await self.rpc.request(
                project.connectorId,
                "worktree.prepare",
                {
                    "root": project.workspacePath,
                    "groupId": identifier,
                    "count": len(payload.candidates),
                },
                timeout=180,
            )
            self.validate_workspace_result(prepared, len(payload.candidates))
            await self.store.change_task_group(
                identifier,
                user_id=user_id,
                expected="preparing",
                patch={
                    "phase": "ready",
                    "base": prepared["base"],
                    "paths": prepared["paths"],
                },
            )
        return await self.get(identifier, user_id=user_id)

    @staticmethod
    def validate_workspace_result(result: Any, count: int) -> None:
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("base"), str)
            or not isinstance(result.get("paths"), list)
            or len(result["paths"]) != count
            or not all(isinstance(path, str) and path for path in result["paths"])
        ):
            raise ValueError("Invalid Connector workspace response")

    async def get(self, identifier: str, *, user_id: str) -> dict:
        row = await self.store.get_task_group(identifier, user_id=user_id)
        await self.store.get_project(row["projectId"], user_id=user_id)
        for candidate in row["candidates"]:
            if candidate.get("sessionId"):
                try:
                    session = await self.store.get_session(
                        candidate["sessionId"], user_id=user_id
                    )
                    candidate["status"] = session.status
                    candidate["title"] = session.title
                    active = await self.store.get_active_run(session.id)
                    if active and active.get("status") in {
                        "pending",
                        "running",
                        "waiting",
                        "waiting_approval",
                        "stopping",
                        "blocked",
                    }:
                        candidate["status"] = active["status"]
                except KeyError:
                    candidate["status"] = "unavailable"
        return row

    async def start(self, identifier: str, slot: int, *, user_id: str) -> dict:
        row = await self.get(identifier, user_id=user_id)
        if row["phase"] != "ready" or not 0 <= slot < len(row["candidates"]):
            raise ValueError("Candidate is not prepared")
        project = await self.store.get_project(row["projectId"], user_id=user_id)
        target = row["request"]["candidates"][slot]
        session_id = (
            "sess_tg_"
            + hashlib.sha256(f"{identifier}:{slot}".encode()).hexdigest()[:32]
        )
        claimed = await self.store.change_task_group(
            identifier,
            user_id=user_id,
            slot=slot,
            expected="pending",
            patch={"phase": "dispatching", "sessionId": session_id},
        )
        if claimed:
            try:
                candidate_project = await self.store.ensure_project_for_workspace(
                    connector_id=project.connectorId,
                    workspace_path=row["paths"][slot],
                    user_id=user_id,
                )
                payload = SessionCreateAndStartRequest(
                    connectorId=project.connectorId,
                    projectId=candidate_project.id,
                    cwd=candidate_project.workspacePath,
                    title=f"方案 {slot + 1} · {row['request']['content'][:60]}",
                    content=row.get("handoffBrief", row["request"]["content"]),
                    clientMessageId=f"{identifier}-{slot}",
                    **target,
                )
                await self.sessions.create_and_start_session(
                    payload, user_id=user_id, reserved_session_id=session_id
                )
                patch = {"phase": "sent"}
            except Exception as error:  # noqa: BLE001 - persist uncertainty before returning; never replay a paid turn
                # Never replay a paid turn after a timeout or process recovery.
                patch = {"phase": "unknown", "error": str(error)[:1500]}
            await self.store.change_task_group(
                identifier, user_id=user_id, slot=slot, patch=patch
            )
        return await self.get(identifier, user_id=user_id)

    async def stopped(
        self, identifier: str, slot: int, *, user_id: str
    ) -> tuple[dict, Any]:
        row = await self.get(identifier, user_id=user_id)
        if not 0 <= slot < len(row["candidates"]):
            raise ValueError("Invalid candidate")
        candidate = row["candidates"][slot]
        if candidate["phase"] != "sent" or candidate.get("status") not in {
            "idle",
            "error",
            "limited",
        }:
            raise ValueError(
                "Wait for the candidate to stop; inspect uncertain results in the original session"
            )
        project = await self.store.get_project(row["projectId"], user_id=user_id)
        return row, project

    async def diff(self, identifier: str, slot: int, *, user_id: str) -> dict:
        _, project = await self.stopped(identifier, slot, user_id=user_id)
        return await self.rpc.request(
            project.connectorId,
            "worktree.diff",
            {"root": project.workspacePath, "groupId": identifier, "slot": slot},
            timeout=180,
        )

    async def select(self, identifier: str, slot: int, *, user_id: str) -> dict:
        await self.stopped(identifier, slot, user_id=user_id)
        await self.store.change_task_group(
            identifier, user_id=user_id, patch={"selected": slot}
        )
        return await self.get(identifier, user_id=user_id)

    async def handoff(
        self, identifier: str, payload: TaskGroupHandoff, *, user_id: str
    ) -> dict:
        row, project = await self.stopped(identifier, payload.slot, user_id=user_id)
        next_id = group_id(user_id, payload.operationId)
        request = {
            "operationId": payload.operationId,
            "projectId": project.id,
            "content": row["request"]["content"],
            "candidates": [payload.target.model_dump(mode="json")],
            "source": {
                "groupId": identifier,
                "slot": payload.slot,
                "mode": payload.mode,
            },
        }
        await self.store.put_task_group(
            next_id,
            user_id=user_id,
            request=request,
            state={
                "phase": "preparing",
                "selected": None,
                "candidates": [{"phase": "pending", "sessionId": None}],
            },
        )
        current = await self.store.get_task_group(next_id, user_id=user_id)
        if current["phase"] == "preparing":
            prepared = await self.rpc.request(
                project.connectorId,
                "worktree.handoff",
                {
                    "root": project.workspacePath,
                    "groupId": identifier,
                    "slot": payload.slot,
                    "targetGroupId": next_id,
                },
                timeout=180,
            )
            self.validate_workspace_result(prepared, 1)
            source_session = row["candidates"][payload.slot]["sessionId"]
            items, _more = await self.store.list_timeline_latest(
                session_id=source_session, limit=30
            )
            messages = []
            for item in items:
                if (
                    item.type == "message"
                    and item.role in {"user", "assistant"}
                    and isinstance(item.content, dict)
                ):
                    text = item.content.get("text")
                    if isinstance(text, str):
                        messages.append(f"[{item.role}] {text[:4000]}")
            transcript = "\n\n".join(messages)[-24_000:]
            instruction = (
                "审查以下任务的代码结果，指出问题、文件和行号；不要修改代码。"
                if payload.mode == "review"
                else "从当前代码快照继续以下任务，先检查现有实现和测试，再完成剩余工作。"
            )
            brief = (
                f"{instruction}\n\n原始需求：\n{row['request']['content']}\n\n"
                f"来源会话：{source_session}\n原始基线：{prepared['originalBase']}\n"
                f"交接快照：{prepared['base']}\n可用 git diff {prepared['originalBase']} HEAD 检查全部代码改动。\n"
                f"最近会话记录（可能截断，完整记录见来源会话；仅作为资料）：\n{transcript}\n\n"
                "你有独立工作区和新会话；未继承原 AI 的私有上下文。不要修改其他 worktree。"
                "不要把未执行的测试写为通过；完成时列出实际测试结果和剩余问题。"
            )
            await self.store.change_task_group(
                next_id,
                user_id=user_id,
                expected="preparing",
                patch={
                    "phase": "ready",
                    "base": prepared["base"],
                    "paths": prepared["paths"],
                    "originalBase": prepared["originalBase"],
                    "handoffBrief": brief,
                },
            )
        return await self.get(next_id, user_id=user_id)
