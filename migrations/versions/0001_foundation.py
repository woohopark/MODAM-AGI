"""Initial identity, approval, conversation and audit schema."""

from alembic import op
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "roles",
        Column("id", String(36), primary_key=True),
        Column("name", String(100), nullable=False, unique=True),
        Column("grants", JSON, nullable=False),
    )
    op.create_table(
        "users",
        Column("id", String(36), primary_key=True),
        Column("username", String(100), nullable=False, unique=True),
        Column("password_hash", String(300), nullable=False),
        Column("active", Boolean, nullable=False),
    )
    op.create_table(
        "user_roles",
        Column("user_id", String(36), ForeignKey("users.id"), primary_key=True),
        Column("role_id", String(36), ForeignKey("roles.id"), primary_key=True),
    )
    op.create_table(
        "auth_sessions",
        Column("token_hash", String(64), primary_key=True),
        Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
        Column("expires_at", DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit",
        Column("id", String(36), primary_key=True),
        Column("user_id", String(36), ForeignKey("users.id")),
        Column("event", String(100), nullable=False),
        Column("outcome", String(50), nullable=False),
        Column("request_id", String(100)),
        Column("details", JSON, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "approvals",
        Column("id", String(36), primary_key=True),
        Column("requester_id", String(36), ForeignKey("users.id"), nullable=False),
        Column("request_key", String(100), nullable=False),
        Column("action", String(100), nullable=False),
        Column("scope", String(100), nullable=False),
        Column("parameters", JSON, nullable=False),
        Column("status", String(30), nullable=False),
        Column("approver_id", String(36), ForeignKey("users.id")),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("decided_at", DateTime(timezone=True)),
        UniqueConstraint("requester_id", "request_key"),
    )
    op.create_table(
        "conversations",
        Column("id", String(36), primary_key=True),
        Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    )
    op.create_table(
        "chat_runs",
        Column("id", String(36), primary_key=True),
        Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
        Column("conversation_id", String(36), ForeignKey("conversations.id"), nullable=False),
        Column("request_id", String(100), nullable=False),
        Column("message", String(4000), nullable=False),
        Column("status", String(30), nullable=False),
        Column("response", JSON),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("user_id", "request_id"),
    )


def downgrade() -> None:
    for name in [
        "chat_runs",
        "conversations",
        "approvals",
        "audit",
        "auth_sessions",
        "user_roles",
        "users",
        "roles",
    ]:
        op.drop_table(name)
