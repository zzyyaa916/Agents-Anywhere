from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_server.core.models import RuntimeName


class CandidateTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime: RuntimeName
    runtimeId: str = Field(min_length=1, max_length=160)
    selections: dict[str, str | None] = Field(default_factory=dict, max_length=16)


class TaskGroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operationId: str = Field(pattern=r"^[a-zA-Z0-9-]{8,80}$")
    projectId: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=32_000)
    candidates: list[CandidateTarget] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def valid_candidates(self):
        if not self.content.strip():
            raise ValueError("Enter what you want the AI to do")
        return self


class TaskGroupSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: int = Field(ge=0, le=2)


class TaskGroupHandoff(TaskGroupSelection):
    operationId: str = Field(pattern=r"^[a-zA-Z0-9-]{8,80}$")
    mode: Literal["review", "continue"]
    target: CandidateTarget
    instructions: str = Field(default="", max_length=8000)
