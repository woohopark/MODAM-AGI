import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from modam.knowledge import add_edge, conflicts, graph_view, retrieve
from modam.llm import Interpreter, ModelError
from modam.models import (
    Approval,
    DocumentChunk,
    GraphNode,
    InventoryEvent,
    Notification,
    PurchaseDraft,
    Stock,
    User,
)
from modam.schemas import GroundedAnswer, Intent, InventoryIssue
from modam.security import allowed, audit

ToolStatus = Literal["completed", "awaiting_approval", "not_available", "clarification"]


@dataclass
class ToolResult:
    status: ToolStatus
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)


def find_stock(db: Session, scope: str, item_id: str, lock: bool = False) -> Stock | None:
    query = select(Stock).where(Stock.scope == scope, Stock.item_id == item_id)
    return db.scalar(query.with_for_update() if lock else query)


def stock_view(db: Session, stock: Stock) -> dict[str, Any]:
    rule = db.get(GraphNode, stock.rule_node_id)
    from modam.models import GraphEdge

    linked = db.scalar(
        select(GraphEdge.id).where(
            GraphEdge.source_id == stock.inventory_node_id,
            GraphEdge.target_id == stock.rule_node_id,
            GraphEdge.kind == "triggers",
        )
    )
    if rule is None or rule.kind != "ProcurementRule" or linked is None:
        raise HTTPException(409, "inventory_rule_not_linked")
    threshold, target = rule.attributes.get("threshold"), rule.attributes.get("target")
    if type(threshold) is not int or type(target) is not int or target < threshold or threshold < 0:
        raise HTTPException(409, "invalid_inventory_rule")
    suggested = (
        max(0, target - stock.quantity - stock.pending_quantity)
        if stock.quantity < threshold
        else 0
    )
    return {
        "scope": stock.scope,
        "item_id": stock.item_id,
        "quantity": stock.quantity,
        "pending_quantity": stock.pending_quantity,
        "unit": stock.unit,
        "revision": stock.revision,
        "threshold": threshold,
        "target": target,
        "suggested_quantity": suggested,
        "needs_reorder": suggested > 0,
        "inventory_node_id": stock.inventory_node_id,
        "rule_node_id": stock.rule_node_id,
    }


def synchronize_node(db: Session, stock: Stock) -> None:
    node = db.get(GraphNode, stock.inventory_node_id)
    if node:
        node.attributes = {
            **node.attributes,
            "quantity": stock.quantity,
            "pending_quantity": stock.pending_quantity,
            "revision": stock.revision,
        }


def record_issue(db: Session, user: User, payload: InventoryIssue) -> dict[str, Any]:
    previous = db.get(InventoryEvent, payload.event_id)
    if previous:
        if (previous.scope, previous.item_id, previous.quantity) != (
            payload.scope,
            payload.item_id,
            payload.quantity,
        ):
            raise HTTPException(409, "event_content_conflict")
        return previous.result
    stock = find_stock(db, payload.scope, payload.item_id, lock=True)
    if stock is None:
        raise HTTPException(404, "stock_not_found")
    # Another writer may have committed this event while we waited for the stock lock.
    previous = db.get(InventoryEvent, payload.event_id)
    if previous:
        if (previous.scope, previous.item_id, previous.quantity) != (
            payload.scope,
            payload.item_id,
            payload.quantity,
        ):
            raise HTTPException(409, "event_content_conflict")
        return previous.result
    # The row lock serializes PostgreSQL writers; the version condition protects SQLite too.
    changed = db.execute(
        update(Stock)
        .where(
            Stock.id == stock.id,
            Stock.revision == stock.revision,
            Stock.quantity >= payload.quantity,
        )
        .values(quantity=Stock.quantity - payload.quantity, revision=Stock.revision + 1)
    )
    if changed.rowcount != 1:  # type: ignore[attr-defined]
        raise HTTPException(409, "insufficient_or_changed_stock")
    db.refresh(stock)
    synchronize_node(db, stock)
    result = stock_view(db, stock)
    event = InventoryEvent(
        event_id=payload.event_id,
        user_id=user.id,
        scope=payload.scope,
        item_id=payload.item_id,
        quantity=payload.quantity,
        result=result,
    )
    db.add(event)
    db.flush()
    if result["needs_reorder"]:
        for recipient in db.scalars(select(User).where(User.active.is_(True))):
            if allowed(recipient, "inventory.read", payload.scope):
                db.add(
                    Notification(
                        user_id=recipient.id,
                        event_id=event.event_id,
                        scope=payload.scope,
                        details={"kind": "low_stock", **result},
                    )
                )
    audit(
        db,
        user,
        "inventory.issue",
        "completed",
        {
            "event_id": event.event_id,
            "scope": stock.scope,
            "item_id": stock.item_id,
            "revision": stock.revision,
        },
    )
    return result


def snapshot_parameters(db: Session, scope: str, parameters: dict[str, Any]) -> dict[str, Any]:
    stock = find_stock(db, scope, str(parameters["item_id"]))
    if stock is None:
        return parameters
    supplied = parameters.get("expected_revision")
    if supplied is not None and supplied != stock.revision:
        raise HTTPException(409, "source_state_changed")
    if parameters["unit"] != stock.unit:
        raise HTTPException(422, "unit_mismatch")
    return {**parameters, "expected_revision": stock.revision}


def draft_view(draft: PurchaseDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "approval_id": draft.approval_id,
        "scope": draft.scope,
        "item_id": draft.item_id,
        "quantity": draft.quantity,
        "unit": draft.unit,
        "source_revision": draft.source_revision,
        "status": "draft",
        "erp_registered": False,
    }


def execute_approval(db: Session, user: User, approval_id: str) -> dict[str, Any]:
    row = db.scalar(select(Approval).where(Approval.id == approval_id).with_for_update())
    if row is None or not allowed(user, "procurement.execute", row.scope):
        raise HTTPException(404, "approval_not_found")
    requester = db.get(User, row.requester_id)
    approver = db.get(User, row.approver_id) if row.approver_id else None
    if requester is None or not allowed(requester, "procurement.propose", row.scope):
        raise HTTPException(409, "requester_permission_changed")
    if approver is None or not allowed(approver, "procurement.approve", row.scope):
        raise HTTPException(409, "approver_permission_changed")
    existing = db.scalar(select(PurchaseDraft).where(PurchaseDraft.approval_id == row.id))
    if existing:
        return draft_view(existing)
    if row.status != "approved":
        raise HTTPException(409, "approval_required")
    stock = find_stock(db, row.scope, str(row.parameters["item_id"]), lock=True)
    if stock is None:
        raise HTTPException(404, "stock_not_found")
    if row.parameters.get("expected_revision") != stock.revision:
        raise HTTPException(409, "source_state_changed_reapproval_required")
    if row.parameters["unit"] != stock.unit:
        raise HTTPException(409, "source_unit_changed")
    draft = PurchaseDraft(
        approval_id=row.id,
        scope=row.scope,
        item_id=stock.item_id,
        quantity=row.parameters["quantity"],
        unit=stock.unit,
        source_revision=stock.revision,
    )
    db.add(draft)
    db.flush()
    changed = db.execute(
        update(Stock)
        .where(Stock.id == stock.id, Stock.revision == draft.source_revision)
        .values(
            pending_quantity=Stock.pending_quantity + draft.quantity, revision=Stock.revision + 1
        )
    )
    if changed.rowcount != 1:  # type: ignore[attr-defined]
        raise HTTPException(409, "source_state_changed_reapproval_required")
    db.refresh(stock)
    synchronize_node(db, stock)
    inventory_node = db.get(GraphNode, stock.inventory_node_id)
    if inventory_node is None:
        raise HTTPException(409, "source_graph_missing")
    node_id = "draft:" + draft.id
    db.add(
        GraphNode(
            id=node_id,
            kind="PurchaseDraft",
            scope=stock.scope,
            ontology_id=inventory_node.ontology_id,
            attributes=draft_view(draft),
            source="approval:" + row.id,
        )
    )
    db.flush()
    item_edge_target = None
    from modam.models import GraphEdge

    item_edge_target = db.scalar(
        select(GraphEdge.target_id).where(
            GraphEdge.source_id == stock.inventory_node_id, GraphEdge.kind == "of_item"
        )
    )
    if item_edge_target is None:
        raise HTTPException(409, "item_relation_missing")
    add_edge(db, node_id, item_edge_target, "for_item")
    warehouses = list(
        db.scalars(
            select(GraphEdge.source_id).where(
                GraphEdge.target_id == stock.inventory_node_id, GraphEdge.kind == "stores"
            )
        )
    )
    for warehouse in warehouses:
        add_edge(db, warehouse, node_id, "receives")
    row.status = "executed"
    audit(db, user, "procurement.draft", "completed", {"approval_id": row.id, "draft_id": draft.id})
    return draft_view(draft)


def run_tool(
    db: Session,
    user: User,
    interpreter: Interpreter,
    intent: Intent,
    question: str,
    request_id: str,
) -> ToolResult:
    scope = intent.scope or ""
    if not allowed(user, intent.action, scope):
        return ToolResult("clarification", "현재 권한을 다시 확인해야 합니다.")
    if intent.action == "inventory.read":
        if not intent.item_id:
            return ToolResult(
                "not_available", "조회할 물품이 없거나 아직 연결되지 않아 실행하지 않았습니다."
            )
        stock = find_stock(db, scope, intent.item_id)
        if stock is None:
            return ToolResult(
                "not_available", "해당 재고 데이터가 아직 연결되지 않아 실행하지 않았습니다."
            )
        data = stock_view(db, stock)
        graph = graph_view(db, user, scope, stock.inventory_node_id)
        data["related_graph"] = graph
        reply = f"물품 {stock.item_id} 재고는 {stock.quantity}{stock.unit}입니다."
        if data["needs_reorder"]:
            reply += (
                f" 기준 {data['threshold']}개 미만이므로 "
                f"{data['suggested_quantity']}개 발주를 제안합니다. 승인이 필요합니다."
            )
        return ToolResult(
            "completed",
            reply,
            data,
            [
                {
                    "source_id": stock.inventory_node_id,
                    "scope": scope,
                    "type": "erp",
                    "revision": stock.revision,
                    "source": next(
                        n["source"] for n in graph["nodes"] if n["id"] == stock.inventory_node_id
                    ),
                }
            ],
        )
    if intent.action == "procurement.propose":
        stock = find_stock(db, scope, intent.item_id or "")
        if stock is None:
            return ToolResult(
                "not_available", "해당 발주 대상이 아직 연결되지 않아 실행하지 않았습니다."
            )
        key = "chat:" + hashlib.sha256(request_id.encode()).hexdigest()
        existing = db.scalar(
            select(Approval).where(Approval.requester_id == user.id, Approval.request_key == key)
        )
        if existing is None:
            params = snapshot_parameters(
                db,
                scope,
                {
                    "item_id": intent.item_id,
                    "quantity": intent.quantity,
                    "unit": intent.unit,
                    "expected_revision": None,
                },
            )
            existing = Approval(
                requester_id=user.id,
                request_key=key,
                action="procurement.propose",
                scope=scope,
                parameters=params,
            )
            db.add(existing)
            db.flush()
            audit(db, user, "approval.create", "pending", {"approval_id": existing.id})
        return ToolResult(
            "awaiting_approval",
            "발주 제안을 등록했습니다. 승인 전에는 초안을 작성하지 않습니다.",
            {"approval_id": existing.id, "parameters": existing.parameters},
        )
    if intent.action == "documents.read":
        contexts = retrieve(db, user, scope, question)
        if not contexts:
            return ToolResult(
                "clarification", "질문에 답할 문서 근거가 부족합니다. 관련 문서를 알려 주세요."
            )
        if conflicts(contexts):
            return ToolResult(
                "clarification",
                "문서 근거가 상충합니다. 적용 규정을 확인해 주세요.",
                evidence=contexts,
            )
        if interpreter.provider == "groq" and any(not row["cloud_allowed"] for row in contexts):
            return ToolResult("clarification", "문서의 Cloud 전송이 허용되지 않았습니다.")
        for context in contexts:
            db.execute(
                update(DocumentChunk)
                .where(DocumentChunk.id == context["chunk_id"])
                .values(context_hits=DocumentChunk.context_hits + 1)
            )
        # Persist read-only search/transmission telemetry before a potentially failing model call.
        db.commit()
        answer: GroundedAnswer = interpreter.answer(question, contexts)
        available = {row["chunk_id"] for row in contexts}
        if not set(answer.citation_ids) <= available:
            raise ModelError("model_invalid_citation")
        for context in contexts:
            db.execute(
                update(DocumentChunk)
                .where(DocumentChunk.id == context["chunk_id"])
                .values(
                    citations=DocumentChunk.citations
                    + (1 if context["chunk_id"] in answer.citation_ids else 0)
                )
            )
        return ToolResult(
            "completed",
            answer.answer,
            evidence=[row for row in contexts if row["chunk_id"] in answer.citation_ids],
        )
    return ToolResult("not_available", "아직 지원하지 않는 업무입니다.")
