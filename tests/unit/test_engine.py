from datetime import UTC, datetime

from modam.config import Settings
from modam.engine import Engine
from modam.observability import ObservationError, Observer
from modam.schemas import Evidence, Grant, Plan, Request, ToolCall, ToolResult
from modam.tools import ToolError, ToolRegistry


class Authority:
    def __init__(self, grants=None):
        self.grants = (
            grants if grants is not None else [Grant(action="documents.read", scopes=["company"])]
        )
        self.active = True
        self.cloud_allowed = True

    async def is_active(self, subject):
        return self.active

    async def can_send(self, subject, scope):
        return self.active and self.cloud_allowed

    async def permits(self, subject, action, scope):
        return self.active and any(g.action == action and scope in g.scopes for g in self.grants)


class Model:
    provider = "boundary-fixture"
    model_id = "fixed-test-plan"

    def __init__(self, plans=None):
        self.plans = plans or [
            Plan(calls=[ToolCall(tool="rag.search", scope="company", arguments={"query": "규정"})])
        ]
        self.calls = 0
        self.answers = 0

    async def plan(self, request, observations, catalog):
        self.calls += 1
        return self.plans[min(self.calls - 1, len(self.plans) - 1)]

    async def answer(self, message, evidence):
        from modam.schemas import GroundedAnswer

        self.answers += 1
        return GroundedAnswer(answer="검증된 합성 규정", citation_ids=[e.ref for e in evidence])


def evidence(**changes):
    fields = dict(
        ref="doc:1:0",
        scope="company",
        freshness="current",
        source_ref="synthetic:policy",
        version="1",
        as_of=datetime.now(UTC),
        text="합성 규정",
        cloud_allowed=True,
    )
    fields.update(changes)
    return Evidence(**fields)


class Gateway:
    def __init__(self, results=None):
        self.calls = 0
        self.results = results or [ToolResult(status="completed", evidence=[evidence()])]
        self.callback = None

    async def call(self, call, context):
        self.calls += 1
        if self.callback:
            self.callback()
        value = self.results[min(self.calls - 1, len(self.results) - 1)]
        if isinstance(value, Exception):
            raise value
        return value


def engine(model=None, gateway=None, authority=None, **settings):
    observer = Observer()
    return Engine(
        model or Model(),
        gateway or Gateway(),
        authority or Authority(),
        ToolRegistry(),
        observer,
        Settings(**settings),
    ), observer


def request(**changes):
    return Request(
        request_id="r1",
        subject_ref="verified:test",
        message="규정 질문",
        cloud_allowed=True,
        **changes,
    )


async def test_completed_has_correlated_trace_without_raw_content():
    runner, observer = engine()
    result = await runner.run(request())
    assert result.status == "completed"
    assert result.evidence[0].ref == "doc:1:0"
    assert result.trace_id and result.run_id
    assert len(observer.spans()) >= 5
    assert {s.context.trace_id for s in observer.spans()} == {int(result.trace_id, 16)}
    assert all(e["run_id"] == result.run_id for e in observer.events)
    assert "규정 질문" not in str(observer.events)
    assert "합성 규정" not in str([dict(s.attributes) for s in observer.spans()])


async def test_no_cloud_consent_calls_model_zero_times():
    model = Model()
    runner, _ = engine(model=model)
    r = request().model_copy(update={"cloud_allowed": False})
    assert (await runner.run(r)).status == "denied"
    assert model.calls == 0


async def test_role_scope_pairs_and_revocation_before_answer():
    auth = Authority(
        [
            Grant(action="documents.read", scopes=["other"]),
            Grant(action="inventory.read", scopes=["company"]),
        ]
    )
    gateway = Gateway()
    runner, _ = engine(gateway=gateway, authority=auth)
    assert (await runner.run(request())).status == "denied"
    assert gateway.calls == 0
    auth.grants = [Grant(action="documents.read", scopes=["company"])]
    gateway.callback = lambda: setattr(auth, "active", False)
    model = Model()
    runner, _ = engine(model=model, gateway=gateway, authority=auth)
    result = await runner.run(request())
    assert result.status == "denied" and result.evidence == []
    assert model.answers == 0


async def test_unconnected_tool_and_unknown_tool_do_not_complete():
    gateway = Gateway([ToolResult(status="not_available", error_code="tool_not_connected")])
    runner, _ = engine(gateway=gateway)
    assert (await runner.run(request())).status == "not_available"
    model = Model([Plan(calls=[ToolCall(tool="arbitrary.sql", scope="company", arguments={})])])
    runner, _ = engine(model=model, gateway=gateway)
    assert (await runner.run(request())).error_code == "tool_not_allowed"
    assert gateway.calls == 1


async def test_read_error_replans_with_bounded_calls():
    gateway = Gateway(
        [
            ToolError("tool_timeout", retryable=True),
            ToolResult(status="completed", evidence=[evidence()]),
        ]
    )
    model = Model()
    runner, _ = engine(model=model, gateway=gateway)
    assert (await runner.run(request())).status == "completed"
    assert model.calls == 2 and gateway.calls == 2
    runner, _ = engine(
        gateway=Gateway([ToolError("tool_timeout", retryable=True)]), max_tool_calls=1
    )
    result = await runner.run(request())
    assert result.status == "failed" and result.error_code == "tool_budget_exceeded"


async def test_non_cloud_and_conflicting_evidence_never_sent_to_model():
    for value in [
        ToolResult(status="completed", evidence=[evidence(cloud_allowed=False)]),
        ToolResult(status="completed", evidence=[evidence(), evidence(version="2")]),
    ]:
        model = Model()
        runner, _ = engine(model=model, gateway=Gateway([value]))
        result = await runner.run(request())
        assert result.status == "clarification_required"
        assert model.answers == 0


async def test_no_evidence_and_invented_citation_fail_closed():
    runner, _ = engine(gateway=Gateway([ToolResult(status="completed")]))
    assert (await runner.run(request())).status == "clarification_required"

    class Invented(Model):
        async def answer(self, message, evidence):
            from modam.schemas import GroundedAnswer

            return GroundedAnswer(answer="invented", citation_ids=["unknown"])

    runner, _ = engine(model=Invented())
    assert (await runner.run(request())).error_code == "model_invalid_citation"


async def test_clarification_plan_and_argument_validation():
    model = Model([Plan(question="어떤 창고인가요?")])
    runner, _ = engine(model=model)
    assert (await runner.run(request())).status == "clarification_required"
    model = Model(
        [
            Plan(
                calls=[
                    ToolCall(
                        tool="rag.search",
                        scope="company",
                        arguments={"query": "규정", "user_id": "admin"},
                    )
                ]
            )
        ]
    )
    gateway = Gateway()
    runner, _ = engine(model=model, gateway=gateway)
    assert (await runner.run(request())).error_code == "tool_invalid_arguments"
    assert gateway.calls == 0


async def test_observation_failure_is_safe_and_request_timeout_is_bounded():
    class Broken(Observer):
        def emit(self, *args, **kwargs):
            raise ObservationError("secret-business-text")

    runner, _ = engine()
    runner.observer = Broken()
    result = await runner.run(request())
    assert result.status == "failed" and result.error_code == "observability_unavailable"
    assert "secret-business-text" not in result.model_dump_json()

    class Slow(Model):
        async def plan(self, *args):
            import asyncio

            await asyncio.sleep(1)

    runner, _ = engine(model=Slow(), run_timeout_seconds=0.01)
    assert (await runner.run(request())).error_code == "run_timeout"


async def test_inactive_identity_and_server_cloud_policy_block_before_model():
    for active, cloud in [(False, True), (True, False)]:
        auth = Authority()
        auth.active, auth.cloud_allowed = active, cloud
        model = Model()
        runner, _ = engine(model=model, authority=auth)
        assert (await runner.run(request())).status == "denied"
        assert model.calls == 0


async def test_cross_scope_and_stale_evidence_never_sent():
    for changes in [{"scope": "private"}, {"freshness": "stale"}]:
        model = Model()
        runner, _ = engine(
            model=model,
            gateway=Gateway([ToolResult(status="completed", evidence=[evidence(**changes)])]),
        )
        result = await runner.run(request())
        assert result.status in {"denied", "clarification_required"}
        assert model.answers == 0 and result.evidence == []


async def test_revocation_during_answer_masks_all_results():
    auth = Authority()

    class Revoking(Model):
        async def answer(self, message, evidence):
            answer = await super().answer(message, evidence)
            auth.active = False
            return answer

    runner, _ = engine(model=Revoking(), authority=auth)
    result = await runner.run(request())
    assert result.status == "denied" and result.evidence == []
    assert "검증된 합성 규정" not in result.message


async def test_engine_has_no_cross_request_state_leak():
    import asyncio

    runner, observer = engine()
    results = await asyncio.gather(
        *[runner.run(request().model_copy(update={"request_id": str(i)})) for i in range(4)]
    )
    assert all(
        r.status == "completed" and r.tool_calls == 1 and r.model_calls == 2 for r in results
    )
    assert len({r.trace_id for r in results}) == 4
    assert len({r.run_id for r in results}) == 4


async def test_model_budget_and_mutations_are_not_executed():
    from modam.tools import SearchArguments, ToolSpec

    gateway = Gateway()
    runner, _ = engine(gateway=gateway, max_model_calls=1)
    assert (await runner.run(request())).error_code == "model_budget_exceeded"
    runner, _ = engine(gateway=gateway)
    runner.registry = ToolRegistry(
        [ToolSpec("rag.search", "documents.read", SearchArguments, read_only=False)]
    )
    result = await runner.run(request())
    assert result.status == "not_available" and result.error_code == "mutation_not_supported"
    assert gateway.calls == 1


async def test_server_blocks_evidence_transmission_and_tool_timeout_replans():
    class Restricted(Authority):
        async def can_send(self, subject, scope):
            return scope is None

    model = Model()
    runner, _ = engine(model=model, authority=Restricted())
    assert (await runner.run(request())).status == "denied"
    assert model.answers == 0

    class SlowGateway(Gateway):
        async def call(self, call, context):
            import asyncio

            if self.calls == 0:
                self.calls += 1
                await asyncio.sleep(1)
            return await super().call(call, context)

    runner, _ = engine(gateway=SlowGateway(), tool_timeout_seconds=0.01)
    assert (await runner.run(request())).status == "completed"


async def test_conversation_context_is_explicitly_unavailable():
    model = Model()
    runner, _ = engine(model=model)
    result = await runner.run(request(conversation_id="past"))
    assert result.status == "not_available" and model.calls == 0
