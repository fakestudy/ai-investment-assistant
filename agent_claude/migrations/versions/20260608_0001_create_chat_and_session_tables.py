"""create chat and session tables

Revision ID: 20260608_0001
Revises:
Create Date: 2026-06-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260608_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "seq",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index(
        op.f("ix_messages_conversation_id"),
        "messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("args", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tool_invocations_message_id"),
        "tool_invocations",
        ["message_id"],
        unique=False,
    )
    op.create_table(
        "message_parts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tool_invocation_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_invocation_id"],
            ["tool_invocations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_message_parts_message_id"),
        "message_parts",
        ["message_id"],
        unique=False,
    )
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("sdk_session_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id"),
    )
    op.create_index(
        op.f("ix_agent_sessions_sdk_session_id"),
        "agent_sessions",
        ["sdk_session_id"],
        unique=False,
    )
    op.create_table(
        "agent_session_entries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_key", sa.String(), nullable=False),
        sa.Column("sdk_session_id", sa.String(), nullable=False),
        sa.Column("subpath", sa.String(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("entry_uuid", sa.String(), nullable=True),
        sa.Column("entry_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_session_entries_sdk_session_id"),
        "agent_session_entries",
        ["sdk_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_session_entries_session_sequence",
        "agent_session_entries",
        ["project_key", "sdk_session_id", "subpath", "sequence_no"],
        unique=True,
    )
    op.create_index(
        "ix_agent_session_entries_session_entry_uuid",
        "agent_session_entries",
        ["project_key", "sdk_session_id", "subpath", "entry_uuid"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_session_entries_session_entry_uuid",
        table_name="agent_session_entries",
    )
    op.drop_index(
        "ix_agent_session_entries_session_sequence",
        table_name="agent_session_entries",
    )
    op.drop_index(
        op.f("ix_agent_session_entries_sdk_session_id"),
        table_name="agent_session_entries",
    )
    op.drop_table("agent_session_entries")
    op.drop_index(
        op.f("ix_agent_sessions_sdk_session_id"),
        table_name="agent_sessions",
    )
    op.drop_table("agent_sessions")
    op.drop_index(op.f("ix_message_parts_message_id"), table_name="message_parts")
    op.drop_table("message_parts")
    op.drop_index(
        op.f("ix_tool_invocations_message_id"),
        table_name="tool_invocations",
    )
    op.drop_table("tool_invocations")
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_table("conversations")
