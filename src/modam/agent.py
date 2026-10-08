from collections.abc import Callable
from time import perf_counter
from typing import Any, Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from modam.business import ToolResult
from modam.llm import Interpreter
from modam.models import User
from modam.schemas import Intent
from modam.security import allowed, has_action


class AgentState(TypedDict, total=False):
    message: str
    history: list[str]
    intent: dict[str, Any]
    status: Literal[
        "authorized",
        "denied",
        "clarification",
        "not_available",
        "failed",
        "completed",
        "awaiting_approval",
    ]
    reply: str
    data: dict[str, Any]
    evidence: list[dict[str, Any]]
    timings_ms: dict[str, float]


def interpret_and_authorize(
    interpreter: Interpreter,
    load_user: Callable[[], User],
    message: str,
    history: list[str],
    execute_tool: Callable[[Intent], ToolResult] | None = None,
) -> AgentState:
    timings: dict[str, float] = {}

    def interpret(state: AgentState) -> AgentState:
        started = perf_counter()
        intent = interpreter.interpret(state["message"], state["history"])
        timings["interpret"] = (perf_counter() - started) * 1000
        return {"intent": intent.model_dump()}

    def authorize(state: AgentState) -> AgentState:
        started = perf_counter()
        result = check(Intent.model_validate(state["intent"]), load_user())
        timings["authorize"] = (perf_counter() - started) * 1000
        return result

    def check(intent: Intent, user: User) -> AgentState:
        if not user.active:
            return {"status": "denied", "reply": "계정이 비활성화되었습니다."}
        if intent.action == "unsupported":
            return {"status": "not_available", "reply": "현재 지원하는 업무로 해석할 수 없습니다."}
        if not has_action(user, intent.action):
            return {"status": "denied", "reply": "해당 업무를 요청할 권한이 없습니다."}
        if intent.scope is None:
            return {"status": "clarification", "reply": "대상 창고 또는 문서 범위를 알려 주세요."}
        if not allowed(user, intent.action, intent.scope):
            return {"status": "denied", "reply": "해당 업무 대상에 접근할 권한이 없습니다."}
        missing = list(intent.missing_fields)
        if intent.action == "procurement.propose":
            for name in ("item_id", "quantity", "unit"):
                if getattr(intent, name) is None and name not in missing:
                    missing.append(name)
        if missing:
            return {
                "status": "clarification",
                "reply": "추가 정보가 필요합니다: " + ", ".join(missing),
            }
        return {"status": "authorized", "reply": "권한 확인 완료"}

    def tools(state: AgentState) -> AgentState:
        if state["status"] != "authorized":
            return {}
        if execute_tool is None:
            return {
                "status": "not_available",
                "reply": "업무 도구가 연결되지 않아 실행하지 않았습니다.",
            }
        started = perf_counter()
        result = execute_tool(Intent.model_validate(state["intent"]))
        timings["tools"] = (perf_counter() - started) * 1000
        return {
            "status": result.status,
            "reply": result.message,
            "data": result.data,
            "evidence": result.evidence,
        }

    graph = StateGraph(AgentState)
    graph.add_node("interpret", interpret)
    graph.add_node("authorize", authorize)
    graph.add_node("tools", tools)
    graph.add_edge(START, "interpret")
    graph.add_edge("interpret", "authorize")
    graph.add_edge("authorize", "tools")
    graph.add_edge("tools", END)
    with tracing_context(enabled=False):
        result = cast(AgentState, graph.compile().invoke({"message": message, "history": history}))
    result["timings_ms"] = {key: round(value, 3) for key, value in timings.items()}
    return result
