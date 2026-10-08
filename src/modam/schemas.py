from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Action = Literal[
    "admin.manage",
    "inventory.read",
    "inventory.record",
    "procurement.propose",
    "procurement.approve",
    "procurement.execute",
    "documents.read",
]
BusinessAction = Literal["inventory.read", "procurement.propose", "documents.read", "unsupported"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Grant(Contract):
    action: Action
    scopes: list[str] = Field(min_length=1, max_length=100)

    @field_validator("scopes")
    @classmethod
    def nonempty_scopes(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("Scopes must be nonempty identifiers up to 100 characters")
        return sorted(set(values))


class RoleCreate(Contract):
    name: str = Field(min_length=1, max_length=100, pattern=r"^\S(?:.*\S)?$")
    grants: list[Grant] = Field(min_length=1, max_length=100)


class RoleView(Contract):
    id: str
    name: str
    grants: list[Grant]


class UserCreate(Contract):
    username: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(min_length=12, max_length=256)
    role_ids: list[str] = Field(min_length=1, max_length=100)


class UserPatch(Contract):
    role_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    active: bool | None = None


class UserView(Contract):
    id: str
    username: str
    active: bool
    roles: list[RoleView]


class Login(Contract):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class TokenView(Contract):
    token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class PermissionCheck(Contract):
    action: Action
    scope: str = Field(min_length=1, max_length=100)


class ProcurementParameters(Contract):
    item_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, le=1000000, strict=True)
    unit: str = Field(min_length=1, max_length=30)
    expected_revision: int | None = Field(default=None, gt=0)


class ApprovalCreate(Contract):
    request_key: str = Field(min_length=1, max_length=100)
    action: Literal["procurement.propose"] = "procurement.propose"
    scope: str = Field(min_length=1, max_length=100)
    parameters: ProcurementParameters


class Decision(Contract):
    decision: Literal["approved", "rejected"]


class ApprovalView(Contract):
    id: str
    requester_id: str
    request_key: str
    action: str
    scope: str
    parameters: dict[str, Any]
    status: str
    approver_id: str | None
    created_at: datetime
    decided_at: datetime | None


class ChatRequest(Contract):
    request_id: str = Field(min_length=1, max_length=100)
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    cloud_allowed: bool = False


class Intent(Contract):
    action: BusinessAction
    scope: str | None = Field(default=None, min_length=1, max_length=100)
    item_id: str | None = Field(default=None, min_length=1, max_length=100)
    quantity: int | None = Field(default=None, gt=0, le=1000000, strict=True)
    unit: str | None = Field(default=None, min_length=1, max_length=30)
    missing_fields: list[str] = Field(default_factory=list, max_length=10)


ChatStatus = Literal[
    "denied", "clarification", "not_available", "failed", "completed", "awaiting_approval"
]


class ChatResponse(Contract):
    request_id: str
    conversation_id: str
    status: ChatStatus
    message: str
    intent: Intent | None = None
    provider: str
    model: str
    error_code: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    model_calls: int = 0


class AuditView(Contract):
    id: str
    user_id: str | None
    event: str
    outcome: str
    request_id: str | None
    details: dict[str, Any]
    created_at: datetime


class InventoryIssue(Contract):
    event_id: str = Field(min_length=1, max_length=100)
    scope: str = Field(min_length=1, max_length=100)
    item_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, le=1000000, strict=True)
    confirmed: Literal[True]


class DocumentCreate(Contract):
    id: str = Field(min_length=1, max_length=100)
    scope: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=200)
    version: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=50000)
    cloud_allowed: bool = False
    facts: dict[str, Any] = Field(default_factory=dict)


class GroundedAnswer(Contract):
    answer: str = Field(min_length=1, max_length=6000)
    citation_ids: list[str] = Field(min_length=1, max_length=5)


class OntologyDefinition(Contract):
    id: str = Field(min_length=1, max_length=100)
    version: int = Field(gt=0)
    types: list[str] = Field(min_length=1, max_length=100)
    relations: list[dict[str, str]] = Field(max_length=100)

    @field_validator("relations")
    @classmethod
    def validate_relations(cls, values: list[dict[str, str]]) -> list[dict[str, str]]:
        if any(set(row) != {"kind", "source", "target"} for row in values):
            raise ValueError("Each relation needs kind, source and target")
        return values
