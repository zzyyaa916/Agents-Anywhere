from __future__ import annotations

from datetime import UTC, datetime


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
