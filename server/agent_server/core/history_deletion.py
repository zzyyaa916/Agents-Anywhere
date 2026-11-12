from __future__ import annotations

import hashlib

BUSY_SESSION_STATUSES = frozenset(
    {"waiting", "pending", "running", "stopping", "waiting_approval"}
)


def source_key(
    connector_id: str, runtime_id: str, external_id: str | None
) -> str | None:
    if not external_id:
        return None
    return hashlib.sha256(
        f"{connector_id}\0{runtime_id}\0{external_id}".encode()
    ).hexdigest()


class SessionDeletedError(ValueError):
    """A native source was explicitly removed from the platform."""


class HistoryDeletionConflict(ValueError):
    def __init__(self, session_ids: list[str], code: str = "session_running") -> None:
        self.detail = {
            "code": code,
            "message": "会话正在运行，请先停止"
            if code == "session_running"
            else "此原生会话仍被其他会话引用，不能单独删除" if code == "shared_native_history"
            else "会话数量已变化，请重新确认",
            "sessionIds": session_ids,
        }
        super().__init__(self.detail["message"])


class DeviceCleanupIncomplete(RuntimeError):
    """The device did not acknowledge the requested cleanup phase."""
