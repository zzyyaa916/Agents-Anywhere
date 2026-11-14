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


def cleanup_failure_message(error: Exception, fallback: str) -> str:
    messages = {
        "native_history_deletion_unsupported": "当前运行时尚不支持原生聊天历史删除，无法完成永久删除；重复重试无法解决。",
        "cleanup_shared_project_path": "项目目录与其他项目或会话的工作目录重叠，已阻止删除以保护其他数据。请先检查共享目录关系。",
        "protected_cleanup_path": "此目录包含受保护的数据，不能作为项目目录整体删除。",
        "cleanup_permission_denied": "Connector 没有清理项目目录的权限，请检查工作设备上的目录权限。",
    }
    for candidate in (getattr(error, "code", None), getattr(error, "message", None), str(error)):
        if isinstance(candidate, str) and candidate in messages:
            return messages[candidate]
    return fallback
