"""Bounded, read-only plan/call/verify/replan state machine with injected boundaries."""

import asyncio
import hashlib
from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from modam.config import Settings
from modam.llm import Model, ModelError
from modam.observability import ObservationError, Observer
from modam.schemas import Evidence, Request, RunResult, Status, ToolCall, ToolResult
from modam.tools import Authority, CallContext, Gateway, ToolError, ToolRegistry


@dataclass
class RunState:
    request: Request
    run_id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: str = ""
    model_calls: int = 0
    tool_calls: int = 0
    started: float = field(default_factory=perf_counter)
    grants_used: list[tuple[str, str]] = field(default_factory=list)


class Engine:
    def __init__(
        self,
        model: Model,
        gateway: Gateway,
        authority: Authority,
        registry: ToolRegistry,
        observer: Observer,
        settings: Settings,
    ) -> None:
        self.model = model
        self.gateway = gateway
        self.authority = authority
        self.registry = registry
        self.observer = observer
        self.settings = settings

    async def run(self, request: Request) -> RunResult:
        state = RunState(request)
        with self.observer.span("request") as span:
            state.trace_id = f"{span.get_span_context().trace_id:032x}"
            span.set_attributes(
                {
                    "subject_ref": hashlib.sha256(request.subject_ref.encode()).hexdigest(),
                    "run_id": state.run_id,
                    "request_id": request.request_id,
                    "config_version": self.settings.config_version,
                    "prompt_version": self.settings.prompt_version,
                    "model_id": self.model.model_id,
                    "provider": self.model.provider,
                }
            )
            try:
                self._emit(state, "run.started", "processing")
                async with asyncio.timeout(self.settings.run_timeout_seconds):
                    result = await self._execute(state)
                self._emit(state, "run.finished", result.status, result.error_code)
            except TimeoutError:
                result = self._result(state, "failed", "run_timeout")
                self._best_effort(state, result)
            except ModelError as exc:
                result = self._result(state, "failed", exc.code)
                self._best_effort(state, result)
            except ObservationError:
                result = self._result(state, "failed", "observability_unavailable")
            except ValidationError:
                result = self._result(state, "failed", "boundary_invalid_response")
                self._best_effort(state, result)
            except Exception:
                result = self._result(state, "failed", "internal_error")
                self._best_effort(state, result)
            span.set_attribute("status", result.status)
            if result.error_code is not None:
                span.set_attribute("error_code", result.error_code)
        return result

    async def _execute(self, state: RunState) -> RunResult:
        with self.observer.span("identity"):
            if not await self.authority.is_active(state.request.subject_ref):
                return self._result(state, "denied", "identity_inactive")
        if not state.request.cloud_allowed or not await self.authority.can_send(
            state.request.subject_ref, None
        ):
            return self._result(state, "denied", "cloud_transmission_not_allowed")
        if state.request.conversation_id is not None:
            return self._result(state, "not_available", "conversation_not_supported")
        observations: list[str] = []
        for revision in range(self.settings.max_replans + 1):
            if state.model_calls >= self.settings.max_model_calls:
                return self._result(state, "failed", "model_budget_exceeded")
            with self.observer.span("model.plan"):
                state.model_calls += 1
                plan = await self.model.plan(state.request, observations, self.registry.catalog())
                self._emit(state, "plan.received", "planned")
            if plan.question:
                return self._result(state, "clarification_required", message=plan.question)
            if plan.unsupported:
                return self._result(state, "not_available", "unsupported_request")
            # Validate the complete plan before any call so a late invalid step cannot run.
            try:
                specs = [self.registry.validate(call) for call in plan.calls]
            except ValueError as exc:
                return self._result(state, "failed", str(exc))
            if any(not spec.read_only for spec in specs):
                return self._result(state, "not_available", "mutation_not_supported")
            evidence: list[Evidence] = []
            retry = False
            for call, spec in zip(plan.calls, specs, strict=True):
                if state.tool_calls >= self.settings.max_tool_calls:
                    return self._result(state, "failed", "tool_budget_exceeded")
                with self.observer.span("authorization"):
                    if not await self.authority.permits(
                        state.request.subject_ref, spec.action, call.scope
                    ):
                        return self._result(state, "denied", "permission_denied")
                    self._emit(state, "authorization.checked", "authorized")
                context = CallContext(
                    state.request.subject_ref,
                    spec.action,
                    call.scope,
                    state.request.request_id,
                    state.run_id,
                    state.trace_id,
                )
                state.grants_used.append((spec.action, call.scope))
                try:
                    response = await self._call(state, call, context)
                except ToolError as exc:
                    observations = [exc.code]  # Only safe failure codes reach re-planning.
                    if exc.retryable and revision < self.settings.max_replans:
                        retry = True
                        break
                    return self._result(state, "failed", exc.code)
                if response.status != "completed":
                    return self._result(state, response.status, response.error_code)
                for item in response.evidence:
                    if item.scope != call.scope or not await self.authority.permits(
                        state.request.subject_ref, spec.action, item.scope
                    ):
                        return self._result(state, "denied", "evidence_scope_denied")
                evidence.extend(response.evidence)
            if retry:
                self._emit(state, "plan.retry", "replanning")
                continue
            with self.observer.span("verify"):
                if not await self._still_authorized(state):
                    return self._result(state, "denied", "permission_denied")
                for item in evidence:
                    if not await self.authority.can_send(state.request.subject_ref, item.scope):
                        return self._result(state, "denied", "evidence_cloud_restricted")
                problem = self._evidence_problem(evidence)
                if problem:
                    return self._result(state, "clarification_required", problem)
                self._emit(state, "evidence.verified", "verified")
            if state.model_calls >= self.settings.max_model_calls:
                return self._result(state, "failed", "model_budget_exceeded")
            with self.observer.span("model.answer"):
                state.model_calls += 1
                answer = await self.model.answer(state.request.message, evidence)
                self._emit(state, "answer.received", "answered")
            if not set(answer.citation_ids) <= {e.ref for e in evidence}:
                return self._result(state, "failed", "model_invalid_citation")
            if not await self._still_authorized(state):
                return self._result(state, "denied", "permission_denied")
            result = self._result(state, "completed", message=answer.answer)
            result.evidence = list(
                {e.ref: e for e in evidence if e.ref in answer.citation_ids}.values()
            )
            return result
        return self._result(state, "failed", "replan_budget_exceeded")

    async def _call(self, state: RunState, call: ToolCall, context: CallContext) -> ToolResult:
        with self.observer.span("tool.call") as span:
            span.set_attributes({"tool": call.tool, "server": call.tool.split(".")[0]})
            state.tool_calls += 1
            try:
                async with asyncio.timeout(self.settings.tool_timeout_seconds):
                    response = ToolResult.model_validate(await self.gateway.call(call, context))
            except TimeoutError:
                raise ToolError("tool_timeout", retryable=True) from None
            self._emit(state, "tool.returned", response.status)
            return response

    async def _still_authorized(self, state: RunState) -> bool:
        if not await self.authority.is_active(state.request.subject_ref):
            return False
        for action, scope in state.grants_used:
            if not await self.authority.permits(state.request.subject_ref, action, scope):
                return False
        return True

    def _evidence_problem(self, evidence: list[Evidence]) -> str | None:
        if not evidence:
            return "evidence_missing"
        if sum(len(e.text) for e in evidence) > self.settings.max_evidence_chars:
            return "evidence_budget_exceeded"
        if any(not e.cloud_allowed for e in evidence):
            return "evidence_cloud_restricted"
        if any(e.freshness != "current" for e in evidence):
            return "evidence_stale_or_unknown"
        versions: dict[str, str] = {}
        refs: dict[str, Evidence] = {}
        for e in evidence:
            if e.source_ref in versions and versions[e.source_ref] != e.version:
                return "source_conflict"
            if e.ref in refs and refs[e.ref] != e:
                return "source_conflict"
            versions[e.source_ref], refs[e.ref] = e.version, e
        return None

    def _result(
        self,
        state: RunState,
        status: Status,
        code: str | None = None,
        *,
        message: str | None = None,
    ) -> RunResult:
        replies = {
            "completed": "조회 결과를 확인했습니다.",
            "clarification_required": "입력 또는 근거를 추가로 확인해야 합니다.",
            "awaiting_approval": "승인 대기 상태입니다. 실행 완료가 아닙니다.",
            "denied": "요청을 진행할 권한 또는 전송 허용이 없습니다.",
            "failed": "요청 처리를 중단했습니다.",
            "unknown": "실제 처리 결과를 확인할 수 없습니다.",
            "not_available": "필요한 업무 도구가 준비되지 않았습니다.",
        }
        return RunResult(
            request_id=state.request.request_id,
            run_id=state.run_id,
            trace_id=state.trace_id,
            status=status,
            message=message or replies[status],
            error_code=code,
            model_calls=state.model_calls,
            tool_calls=state.tool_calls,
            elapsed_ms=round((perf_counter() - state.started) * 1000, 3),
        )

    def _emit(self, state: RunState, event: str, status: str, code: str | None = None) -> None:
        self.observer.emit(
            event,
            request_id=state.request.request_id,
            run_id=state.run_id,
            trace_id=state.trace_id,
            status=status,
            model_calls=state.model_calls,
            tool_calls=state.tool_calls,
            duration_ms=round((perf_counter() - state.started) * 1000, 3),
            error_code=code,
        )

    def _best_effort(self, state: RunState, result: RunResult) -> None:
        try:
            self._emit(state, "run.finished", result.status, result.error_code)
        except ObservationError:
            result.status, result.error_code = "failed", "observability_unavailable"
