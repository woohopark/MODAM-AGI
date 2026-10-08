"""Persisted graph and access-filtered sparse-vector retrieval reference implementation."""

import math
import re
from collections import Counter
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from modam.models import Document, DocumentChunk, GraphEdge, GraphNode, Ontology, User
from modam.schemas import DocumentCreate, OntologyDefinition
from modam.security import allowed


def save_ontology(db: Session, definition: OntologyDefinition) -> Ontology:
    if len(set(definition.types)) != len(definition.types):
        raise HTTPException(422, "duplicate_object_type")
    if any(
        r[side] not in definition.types
        for r in definition.relations
        for side in ("source", "target")
    ):
        raise HTTPException(422, "unknown_relation_endpoint")
    existing = db.get(Ontology, definition.id)
    payload = definition.model_dump()
    if existing:
        if existing.definition != payload:
            raise HTTPException(409, "ontology_version_immutable")
        return existing
    row = Ontology(id=definition.id, version=definition.version, definition=payload)
    db.add(row)
    db.flush()
    return row


def add_edge(db: Session, source_id: str, target_id: str, kind: str) -> None:
    source, target = db.get(GraphNode, source_id), db.get(GraphNode, target_id)
    if source is None or target is None or source.ontology_id != target.ontology_id:
        raise HTTPException(422, "invalid_graph_endpoint")
    ontology = db.get(Ontology, source.ontology_id)
    if ontology is None or not any(
        r == {"kind": kind, "source": source.kind, "target": target.kind}
        for r in ontology.definition["relations"]
    ):
        raise HTTPException(422, "relation_not_defined")
    existing = db.scalar(
        select(GraphEdge.id).where(
            GraphEdge.source_id == source_id,
            GraphEdge.target_id == target_id,
            GraphEdge.kind == kind,
        )
    )
    if existing is None:
        db.add(GraphEdge(source_id=source_id, target_id=target_id, kind=kind))
        db.flush()


def graph_view(db: Session, user: User, scope: str, start: str, depth: int = 3) -> dict[str, Any]:
    if not allowed(user, "inventory.read", scope):
        raise HTTPException(403, "permission_denied")
    root = db.get(GraphNode, start)
    if root is None or root.scope != scope:
        raise HTTPException(404, "graph_node_not_found")
    nodes = {n.id: n for n in db.scalars(select(GraphNode).where(GraphNode.scope == scope))}
    edges = list(
        db.scalars(
            select(GraphEdge).where(GraphEdge.source_id.in_(nodes), GraphEdge.target_id.in_(nodes))
        )
    )
    visited, frontier = {start}, {start}
    for _ in range(depth):
        neighbors = {e.target_id for e in edges if e.source_id in frontier}
        frontier = neighbors - visited
        visited |= frontier
        if len(visited) > 100:
            raise HTTPException(422, "graph_result_limit")
    return {
        "backend": "sql-property-graph",
        "nodes": [
            {
                "id": key,
                "kind": nodes[key].kind,
                "attributes": nodes[key].attributes,
                "source": nodes[key].source,
                "ontology_id": nodes[key].ontology_id,
            }
            for key in sorted(visited)
        ],
        "edges": [
            {"source": e.source_id, "target": e.target_id, "kind": e.kind}
            for e in edges
            if e.source_id in visited and e.target_id in visited
        ],
    }


def ingest_document(db: Session, payload: DocumentCreate) -> Document:
    row = db.get(Document, payload.id)
    contents = [payload.text[i : i + 700] for i in range(0, len(payload.text), 600)]
    if row:
        same = (
            row.scope == payload.scope
            and row.title == payload.title
            and row.location == payload.location
            and row.version == payload.version
            and row.facts == payload.facts
            and row.cloud_allowed == payload.cloud_allowed
            and [c.content for c in sorted(row.chunks, key=lambda c: c.position)] == contents
        )
        if not same:
            raise HTTPException(409, "document_version_immutable")
        return row
    row = Document(
        id=payload.id,
        scope=payload.scope,
        title=payload.title,
        location=payload.location,
        version=payload.version,
        facts=payload.facts,
        cloud_allowed=payload.cloud_allowed,
    )
    db.add(row)
    db.flush()
    row.chunks = [
        DocumentChunk(id=f"{row.id}:{i}", document_id=row.id, position=i, content=value)
        for i, value in enumerate(contents)
    ]
    db.flush()
    return row


def terms(text: str) -> Counter[str]:
    for stop in ("알려줘", "알려주세요", "규정", "회사", "몇 개인가요", "얼마인가요", "어떻게"):
        text = text.replace(stop, " ")
    words = re.findall(r"[a-zA-Z0-9가-힣]+", text.lower())
    return Counter(word[i : i + 2] for word in words for i in range(max(1, len(word) - 1)))


def retrieve(db: Session, user: User, scope: str, question: str) -> list[dict[str, Any]]:
    if not allowed(user, "documents.read", scope):
        raise HTTPException(403, "permission_denied")
    documents = list(db.scalars(select(Document).where(Document.scope == scope)))
    rows = [(doc, chunk) for doc in documents for chunk in doc.chunks]
    vectors = [terms(doc.title + " " + chunk.content) for doc, chunk in rows]
    query = terms(question)
    frequency: Counter[str] = Counter()
    for vector in vectors:
        frequency.update(vector.keys())
    idf = {term: math.log((1 + len(rows)) / (1 + count)) + 1 for term, count in frequency.items()}

    def weighted(vector: Counter[str]) -> dict[str, float]:
        return {term: count * idf.get(term, 0) for term, count in vector.items()}

    query_vector = weighted(query)
    query_norm = math.sqrt(sum(v * v for v in query_vector.values()))
    ranked = []
    for (doc, chunk), vector in zip(rows, vectors, strict=True):
        values = weighted(vector)
        norm = math.sqrt(sum(v * v for v in values.values()))
        score = (
            sum(v * values.get(k, 0) for k, v in query_vector.items()) / (query_norm * norm)
            if query_norm and norm
            else 0
        )
        if score >= 0.1:
            ranked.append((score, doc, chunk))
    ranked.sort(key=lambda row: (-row[0], row[2].id))
    results = []
    for score, doc, chunk in ranked[:3]:
        db.execute(
            update(DocumentChunk)
            .where(DocumentChunk.id == chunk.id)
            .values(search_hits=DocumentChunk.search_hits + 1)
        )
        results.append(
            {
                "source_id": doc.id,
                "chunk_id": chunk.id,
                "scope": doc.scope,
                "location": doc.location,
                "version": doc.version,
                "text": chunk.content,
                "score": round(score, 6),
                "facts": doc.facts,
                "cloud_allowed": doc.cloud_allowed,
            }
        )
    return results


def conflicts(contexts: list[dict[str, Any]]) -> bool:
    values: dict[str, object] = {}
    for context in contexts:
        for key, value in context["facts"].items():
            if key in values and values[key] != value:
                return True
            values[key] = value
    return False
