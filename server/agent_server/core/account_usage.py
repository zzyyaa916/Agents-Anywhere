from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    model_validator,
)
from pydantic.alias_generators import to_camel

MINIMUM = {"codex": 60, "claude_code": 300}
Runtime = Literal["codex", "claude_code", "dsh"]
Plan = Literal[
    "free", "plus", "pro", "max", "team", "business", "enterprise", "edu", "go"
]
ErrorCode = Literal[
    "unavailable",
    "rate_limited",
    "invalid_response",
    "account_changed",
    "account_unavailable",
    "unsupported_auth",
]


class Wire(BaseModel):
    model_config = ConfigDict(
        extra="forbid", alias_generator=to_camel, populate_by_name=True
    )


class UsageWindow(Wire):
    kind: Literal["five_hour", "weekly", "seven_day", "weekly_scoped", "other"]
    model_scope: Literal["opus", "sonnet", "haiku", "unknown"] | None = None
    used_percent: FiniteFloat = Field(ge=0, le=100)
    remaining_percent: FiniteFloat = Field(ge=0, le=100)
    resets_at: AwareDatetime
    window_duration_mins: int = Field(gt=0, le=525600)
    source: Literal["event", "probe"] | None = None
    received_at: AwareDatetime | None = None
    age_seconds: FiniteFloat | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def consistent(self):
        if abs(self.remaining_percent + self.used_percent - 100) > 0.001:
            raise ValueError("invalid percentages")
        if self.kind == "five_hour" and self.window_duration_mins != 300:
            raise ValueError("invalid window duration")
        return self


class UsageIdentity(Wire):
    runtime: Runtime
    account_key: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    plan_type: Plan | None = None
    error_code: ErrorCode | None = None


class UsageCollection(UsageIdentity):
    windows: list[UsageWindow] = Field(default_factory=list, max_length=32)
    fetched_at: AwareDatetime | None = None
    stale: bool = True
    next_attempt_at: FiniteFloat = 0


class UsageBinding(Wire):
    connector_id: str
    runtime_id: str


class UsageSnapshot(Wire):
    runtime: Runtime
    account_key: str
    bindings: list[UsageBinding] = Field(default_factory=list)
    account_label: str
    plan_type: Plan | None = None
    windows: list[UsageWindow]
    fetched_at: AwareDatetime | None = None
    stale: bool
    error_code: ErrorCode | None = None
    next_attempt_at: float


class ProbeRefresh(Wire):
    status: Literal["idle", "running", "success", "retry", "offline", "circuit", "disabled"] = "idle"
    next_allowed_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    error_code: ErrorCode | Literal["timeout", "node_offline", "probe_not_configured"] | None = None


class ClaudeUsageEvent(Wire):
    runtime_id: str
    account_key: str = Field(pattern="^[a-f0-9]{64}$")
    event_id: str = Field(pattern="^[a-f0-9]{32}$")
    windows: list[UsageWindow] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def known_windows(self):
        if any(w.kind not in {"five_hour", "seven_day"} for w in self.windows):
            raise ValueError("unsupported Claude window")
        return self


class ClaudeProbeResult(UsageIdentity):
    windows: list[UsageWindow] = Field(default_factory=list, max_length=2)
    retry_after_seconds: FiniteFloat | None = Field(default=None, ge=0)
    retry_after_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def known_windows(self):
        if any(w.kind not in {"five_hour", "seven_day"} for w in self.windows):
            raise ValueError("unsupported Claude window")
        return self


class UsageResponse(Wire):
    snapshots: list[UsageSnapshot]
    unavailable: list[Runtime]
    server_time: str
    refresh: ProbeRefresh = Field(default_factory=ProbeRefresh)


def probe_failure(state, now, error_code, *, retry_after_seconds=None, retry_after_at=None):
    """One server-clock retry policy; failures never change cached windows."""
    if retry_after_seconds is not None:
        try:
            datetime.fromtimestamp(now + retry_after_seconds, UTC)
        except (OverflowError, OSError, ValueError):
            retry_after_seconds = None
    value = dict(state)
    value.update(status="offline" if error_code == "node_offline" else "retry", error_code=error_code, attempt_id=None, lease_until=0)
    if error_code == "rate_limited":
        value["consecutive_429"] = value.get("consecutive_429", 0) + 1
    if retry_after_seconds is not None:
        deadline = now + retry_after_seconds
        value["interval"] = max(300, retry_after_seconds)
    elif retry_after_at is not None:
        deadline = max(now, retry_after_at.timestamp())
        value["interval"] = max(300, deadline - now)
    else:
        value["interval"] = value.get("interval", 300) * 2
        deadline = now + value["interval"]
    if value.get("consecutive_429", 0) >= 3:
        tomorrow = datetime.fromtimestamp(now, UTC).date() + timedelta(days=1)
        circuit = datetime.combine(tomorrow, datetime.min.time(), UTC).timestamp()
        value.update(status="circuit", circuit_until=circuit)
        deadline = max(deadline if retry_after_seconds is not None or retry_after_at is not None else now, circuit)
    value["next_allowed_at"] = deadline
    return value


def normalize_probe_state(state, now):
    value = dict(state)
    if value.get("circuit_until", 0) and now >= value["circuit_until"]:
        value.update(circuit_until=0, consecutive_429=0, interval=300, error_code=None)
        value["status"] = "retry" if value.get("next_allowed_at", 0) > now else "idle"
    if value.get("status") == "running" and now >= value.get("lease_until", 0):
        value = probe_failure(value, now, "timeout")
    return value


def merged_claude_windows(data, legacy_windows, now):
    """Per-window selection uses only server receipts, preserving legacy values with unknown age."""
    selected = {}
    for window in legacy_windows:
        kind = "seven_day" if window.kind == "weekly" and window.window_duration_mins == 10080 and window.model_scope is None else window.kind
        if kind in {"five_hour", "seven_day"}:
            selected[kind] = window.model_copy(update={"kind": kind, "source": None, "received_at": None, "age_seconds": None})
    for kind in ("five_hour", "seven_day"):
        entries = list(data.get(kind, {}).values())
        if not entries:
            continue
        newest = max(entries, key=lambda item: (item["received_at"], item["source"] == "probe"))
        received = datetime.fromisoformat(newest["received_at"])
        selected[kind] = UsageWindow.model_validate({**newest["window"], "source": newest["source"],
            "receivedAt": received, "ageSeconds": max(0, now - received.timestamp())})
    return [selected[kind] for kind in ("five_hour", "seven_day") if kind in selected]
