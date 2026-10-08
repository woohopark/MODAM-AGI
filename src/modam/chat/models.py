"""AGI-owned state. No source documents, vectors or ontology objects live here."""

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "chat_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    cloud_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    grants: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)


class SessionToken(Base):
    __tablename__ = "chat_sessions"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("chat_users.id"))
    expires: Mapped[float] = mapped_column(Float)


class Conversation(Base):
    __tablename__ = "chat_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("chat_users.id"), index=True)
    title: Mapped[str] = mapped_column(String(100), default="새 대화")
    mode: Mapped[str] = mapped_column(String(20))
    created: Mapped[float] = mapped_column(Float)
    updated: Mapped[float] = mapped_column(Float)


class Run(Base):
    __tablename__ = "chat_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id"),
        Index(
            "one_active_chat_run",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("chat_conversations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("chat_users.id"))
    request_id: Mapped[str] = mapped_column(String(100))
    fingerprint: Mapped[str] = mapped_column(String(64))
    input: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    answer: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created: Mapped[float] = mapped_column(Float)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # References and policy labels only. Never persist raw retrieved documents.
    evidence_labels: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)


class Event(Base):
    __tablename__ = "chat_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("chat_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict[str, object]] = mapped_column(JSON)


class Cancellation(Base):
    __tablename__ = "chat_cancellations"
    __table_args__ = (UniqueConstraint("user_id", "request_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("chat_users.id"))
    request_id: Mapped[str] = mapped_column(String(100))
    created: Mapped[float] = mapped_column(Float)
