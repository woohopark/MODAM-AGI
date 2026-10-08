from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("role_id", ForeignKey("roles.id"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    grants: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(50))
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("requester_id", "request_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(100))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    approver_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class ChatRun(Base):
    __tablename__ = "chat_runs"
    __table_args__ = (UniqueConstraint("user_id", "request_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    request_id: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(String(4000))
    status: Mapped[str] = mapped_column(String(30), default="processing")
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DatasetSeed(Base):
    __tablename__ = "dataset_seeds"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Ontology(Base):
    __tablename__ = "ontologies"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[int]
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    ontology_id: Mapped[str] = mapped_column(ForeignKey("ontologies.id"))
    kind: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(100), index=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(300))


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (UniqueConstraint("source_id", "target_id", "kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id"))
    target_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id"))
    kind: Mapped[str] = mapped_column(String(100))


class Stock(Base):
    __tablename__ = "stocks"
    __table_args__ = (UniqueConstraint("scope", "item_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    scope: Mapped[str] = mapped_column(String(100), index=True)
    item_id: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int]
    pending_quantity: Mapped[int] = mapped_column(default=0)
    unit: Mapped[str] = mapped_column(String(30))
    revision: Mapped[int] = mapped_column(default=1)
    inventory_node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id"))
    rule_node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id"))


class InventoryEvent(Base):
    __tablename__ = "inventory_events"
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(String(100))
    item_id: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int]
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "event_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("inventory_events.event_id"))
    scope: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PurchaseDraft(Base):
    __tablename__ = "purchase_drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id"), unique=True)
    scope: Mapped[str] = mapped_column(String(100), index=True)
    item_id: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int]
    unit: Mapped[str] = mapped_column(String(30))
    source_revision: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    scope: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(200))
    cloud_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    location: Mapped[str] = mapped_column(String(200))
    version: Mapped[int]
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    chunks: Mapped[list[DocumentChunk]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String(150), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    position: Mapped[int]
    content: Mapped[str] = mapped_column(String(1000))
    search_hits: Mapped[int] = mapped_column(default=0)
    context_hits: Mapped[int] = mapped_column(default=0)
    citations: Mapped[int] = mapped_column(default=0)
