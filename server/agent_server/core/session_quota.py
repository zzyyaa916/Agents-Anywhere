from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def effective_quota(value, *, now=None):
    if not value:
        return None
    value = dict(value)
    now = now or datetime.now(UTC)
    if (
        value.get("state") == "limited"
        and value.get("resetsAt")
        and datetime.fromisoformat(value["resetsAt"]) <= now
    ):
        value["state"] = "ready"
    return value


def quota_status(status, quota):
    quota = effective_quota(quota)
    if quota and quota.get("state") == "limited":
        return "limited"
    if status == "limited":
        return "idle"
    if quota and quota.get("state") == "ready" and status == "error":
        return "idle"
    return status


def project_quota_state(session, state):
    quota = effective_quota(session.quotaLimit)
    if not quota:
        return state
    return state.model_copy(
        update={
            "status": quota_status(state.status, quota),
            "metadata": {**state.metadata, "quotaLimit": quota},
        }
    )


def closed_quota_notice(session):
    return {
        "noticeId": f"quota_limit_{session.id}", "sessionId": session.id,
        "type": "notification", "source": {"runtime": session.runtime, "component": "runtime"},
        "title": "因限额中断", "message": "限额等待已结束。", "severity": "info",
        "status": "closed", "context": {"reason": "usage_limit", "quotaLimit": session.quotaLimit},
        "updatedSeq": session.updatedSeq, "resolvedAt": datetime.now(UTC).isoformat(),
    }


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _quota_reset_at(value: Any) -> datetime | None:
    """Parse a cached reset time; a null or malformed value simply has no deadline."""
    if isinstance(value, datetime):
        return _aware(value)
    if not isinstance(value, str):
        return None
    try:
        return _aware(datetime.fromisoformat(value))
    except ValueError:
        return None


def limited_quota_windows(values: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Windows that still consume the whole quota; a null reset is not a deadline."""
    result = []
    for window in values:
        if window.get("remainingPercent") != 0:
            continue
        reset = _quota_reset_at(window.get("resetsAt"))
        if reset is not None and reset > now:
            result.append(window)
    return result


def recheck_window_usable(window: Any, interrupted_at: datetime, server_time: datetime) -> bool:
    """A Claude window may end the wait only if it was received after the interrupt and resets later."""
    return bool(
        window.received_at is not None
        and _aware(window.received_at) > interrupted_at
        and window.resets_at is not None
        and _aware(window.resets_at) > server_time
    )
