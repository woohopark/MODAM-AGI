"""Versioned boundary contracts; user claims never establish server authority."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Status = Literal[
    "completed",
    "clarification_required",
    "awaiting_approval",
    "denied",
    "failed",
    "unknown",
    "not_available",
]
JsonValue = str | int | float | bool | None | list[object] | dict[str, object]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Grant(Contract):
    action: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=100)


class Request(Contract):
    """Internal command. subject_ref must be supplied by a verified identity adapter."""

    request_id: str = Field(min_length=1, max_length=100)
    subject_ref: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
    cloud_allowed: bool = Field(default=False, strict=True)
    conversation_id: str | None = None


class ToolCall(Contract):
    tool: str = Field(min_length=1, max_length=100)
    scope: str = Field(
        min_length=1,
        max_length=100,
        description="Exact data scope identifier stated by the user; never a tool/action name.",
    )
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class Plan(Contract):
    calls: list[ToolCall] = Field(default_factory=list, max_length=8)
    question: str | None = Field(default=None, min_length=1, max_length=500)
    unsupported: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def one_outcome(self) -> "Plan":
        if sum([bool(self.calls), self.question is not None, self.unsupported]) != 1:
            raise ValueError("Exactly one plan outcome is required")
        return self


class Evidence(Contract):
    scope: str = Field(min_length=1, max_length=100)
    freshness: Literal["current", "stale", "unknown"] = "unknown"
    ref: str = Field(min_length=1, max_length=200)
    source_ref: str = Field(min_length=1, max_length=300)
    version: str = Field(min_length=1, max_length=100)
    as_of: datetime
    text: str = Field(min_length=1, max_length=6000)
    cloud_allowed: bool = Field(default=False, strict=True)

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Evidence timestamp must include a timezone")
        return value


class ToolResult(Contract):
    status: Status
    contract_version: Literal["0.1"] = "0.1"
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    # Raw tool data does not go into model prompts. Normalized evidence is explicit.
    error_code: (
        Literal[
            "tool_not_connected",
            "tool_denied",
            "tool_failed",
            "tool_timeout",
            "source_conflict",
            "evidence_missing",
            "result_unknown",
        ]
        | None
    ) = None


class GroundedAnswer(Contract):
    answer: str = Field(min_length=1, max_length=6000)
    citation_ids: list[str] = Field(min_length=1, max_length=20)


class RunResult(Contract):
    grants_used: list[Grant] = Field(default_factory=list)
    request_id: str
    run_id: str
    trace_id: str
    status: Status
    message: str
    error_code: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    model_calls: int = 0
    tool_calls: int = 0
    elapsed_ms: float = 0
    contract_version: Literal["0.1"] = "0.1"
