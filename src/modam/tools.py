"""Trusted read-tool catalog; MCP transport and delegation live in mcp_gateway."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import Field, ValidationError

from modam.schemas import Contract, ToolCall, ToolResult


class SearchArguments(Contract):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=10, strict=True)


class ObjectArguments(Contract):
    object_ref: str = Field(min_length=1, max_length=200)


class PathArguments(Contract):
    start_ref: str = Field(min_length=1, max_length=200)
    relationship_kinds: list[str] = Field(min_length=1, max_length=20)
    depth: int = Field(default=3, ge=1, le=5, strict=True)
    limit: int = Field(default=20, ge=1, le=100, strict=True)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    action: str
    arguments: type[Contract]
    read_only: bool = True


@dataclass(frozen=True)
class CallContext:
    subject_ref: str
    action: str
    scope: str
    request_id: str
    run_id: str
    trace_id: str
    # Gateway signs delegation; services introspect current policy before returning data.


class Authority(Protocol):
    async def is_active(self, subject: str) -> bool: ...

    async def can_send(self, subject: str, scope: str | None) -> bool: ...

    async def permits(self, subject: str, action: str, scope: str) -> bool: ...


class Gateway(Protocol):
    async def call(self, call: ToolCall, context: CallContext) -> ToolResult: ...


class ToolError(Exception):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = (
            code if code in {"tool_timeout", "tool_unavailable", "tool_denied"} else "tool_failed"
        )
        self.retryable = retryable
        super().__init__(self.code)


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        items = (
            specs
            if specs is not None
            else [
                ToolSpec("rag.search", "documents.read", SearchArguments),
                ToolSpec("ontology.objects.get", "inventory.read", ObjectArguments),
                ToolSpec("ontology.paths.query", "inventory.read", PathArguments),
            ]
        )
        self._specs = {s.name: s for s in items}
        if len(items) != len(self._specs):
            raise ValueError("Duplicate trusted tool names")

    def validate(self, call: ToolCall) -> ToolSpec:
        spec = self._specs.get(call.tool)
        if spec is None:
            raise ValueError("tool_not_allowed")
        try:
            spec.arguments.model_validate(call.arguments)
        except ValidationError:
            raise ValueError("tool_invalid_arguments") from None
        return spec

    def catalog(self) -> list[dict[str, object]]:
        return [
            {"name": s.name, "action": s.action, "input_schema": s.arguments.model_json_schema()}
            for s in self._specs.values()
        ]


class DisconnectedGateway:
    async def call(self, call: ToolCall, context: CallContext) -> ToolResult:
        return ToolResult(status="not_available", error_code="tool_not_connected")
