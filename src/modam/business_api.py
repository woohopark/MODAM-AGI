from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from modam.api import DB, Admin, CurrentUser, require
from modam.business import draft_view, execute_approval, find_stock, record_issue, stock_view
from modam.knowledge import graph_view, ingest_document, save_ontology
from modam.models import Document, Notification, Ontology, PurchaseDraft
from modam.schemas import DocumentCreate, InventoryIssue, OntologyDefinition
from modam.security import allowed, audit

router = APIRouter(prefix="/v1")


@router.get("/inventory/{scope}/{item_id}")
def inventory(scope: str, item_id: str, db: DB, user: CurrentUser) -> dict[str, Any]:
    require(db, user, "inventory.read", scope)
    stock = find_stock(db, scope, item_id)
    if stock is None:
        raise HTTPException(404, "stock_not_found")
    return stock_view(db, stock)


@router.post("/inventory/events")
def issue(payload: InventoryIssue, db: DB, user: CurrentUser) -> dict[str, Any]:
    require(db, user, "inventory.record", payload.scope)
    try:
        result = record_issue(db, user, payload)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        # A concurrent equal event must not decrement twice; inspect the committed event.
        result = record_issue(db, user, payload)
        db.commit()
        return result


@router.get("/graph")
def graph(
    scope: str, start: str, db: DB, user: CurrentUser, depth: Annotated[int, Query(ge=0, le=5)] = 3
) -> dict[str, Any]:
    return graph_view(db, user, scope, start, depth)


@router.post("/admin/ontologies", status_code=201)
def ontology_create(payload: OntologyDefinition, db: DB, admin: Admin) -> dict[str, Any]:
    row = save_ontology(db, payload)
    audit(db, admin, "ontology.save", "completed", {"ontology_id": row.id})
    db.commit()
    return row.definition


@router.get("/admin/ontologies")
def ontologies(db: DB, admin: Admin) -> list[dict[str, Any]]:
    return [row.definition for row in db.scalars(select(Ontology))]


@router.post("/admin/documents", status_code=201)
def documents_create(payload: DocumentCreate, db: DB, admin: Admin) -> dict[str, Any]:
    row = ingest_document(db, payload)
    audit(db, admin, "document.ingest", "completed", {"document_id": row.id})
    db.commit()
    return {"id": row.id, "version": row.version, "chunks": len(row.chunks)}


@router.get("/admin/documents/metrics")
def document_metrics(db: DB, admin: Admin) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "search_hits": sum(c.search_hits for c in row.chunks),
            "context_hits": sum(c.context_hits for c in row.chunks),
            "citations": sum(c.citations for c in row.chunks),
        }
        for row in db.scalars(select(Document))
    ]


@router.get("/notifications")
def notifications(db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id))
    return [
        {"id": row.id, "event_id": row.event_id, "details": row.details}
        for row in rows
        if allowed(user, "inventory.read", row.scope)
    ]


@router.post("/approvals/{approval_id}/execute")
def execute(approval_id: str, db: DB, user: CurrentUser) -> dict[str, Any]:
    try:
        result = execute_approval(db, user, approval_id)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        result = execute_approval(db, user, approval_id)
        db.commit()
        return result


@router.get("/purchase-drafts")
def drafts(db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    rows = db.scalars(select(PurchaseDraft))
    return [
        draft_view(row)
        for row in rows
        if allowed(user, "procurement.propose", row.scope)
        or allowed(user, "procurement.execute", row.scope)
    ]
