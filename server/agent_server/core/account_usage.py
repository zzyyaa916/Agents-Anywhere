from __future__ import annotations

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


class UsageResponse(Wire):
    snapshots: list[UsageSnapshot]
    unavailable: list[Runtime]
    server_time: str
