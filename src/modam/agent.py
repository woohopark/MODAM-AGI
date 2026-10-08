from collections.abc import Callable
from typing import Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from modam.llm import Interpreter
from modam.models import User
from modam.schemas import Intent
from modam.security import allowed, has_action


class AgentState(TypedDict, total=False):
    message: str
    history: list[str]
    intent: dict[str, object]
    status: Literal["denied", "clarification", "not_available", "failed"]
    reply: str


def interpret_and_authorize(
    interpreter: Interpreter, load_user: Callable[[], User], message: str, history: list[str]
) -> AgentState:
    def interpret(state: AgentState) -> AgentState:
        intent = interpreter.interpret(state["message"], state["history"])
        return {"intent": intent.model_dump()}

    def authorize(state: AgentState) -> AgentState:
        intent = Intent.model_validate(state["intent"])
        user = load_user()
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
            for field in ("item_id", "quantity", "unit"):
                if getattr(intent, field) is None and field not in missing:
                    missing.append(field)
        if missing:
            return {
                "status": "clarification",
                "reply": "추가 정보가 필요합니다: " + ", ".join(missing),
            }
        return {
            "status": "not_available",
            "reply": (
                "업무 권한을 확인했습니다. 해당 업무 도구는 아직 연결되지 않아 실행하지 않았습니다."
            ),
        }

    graph = StateGraph(AgentState)
    graph.add_node("interpret", interpret)
    graph.add_node("authorize", authorize)
    graph.add_edge(START, "interpret")
    graph.add_edge("interpret", "authorize")
    graph.add_edge("authorize", END)
    with tracing_context(enabled=False):
        result = graph.compile().invoke({"message": message, "history": history})
    return cast(AgentState, result)
