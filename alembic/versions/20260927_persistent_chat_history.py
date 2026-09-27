"""store chat history in the main persistent database

Revision ID: 20260927_01
Revises: 20260916_01
Create Date: 2026-09-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260927_01"
down_revision = "20260916_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="New Chat"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_conversations_user_id", "chat_conversations", ["user_id"])
    op.create_index("ix_chat_conversations_updated_at", "chat_conversations", ["updated_at"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), sa.ForeignKey("chat_conversations.id"), nullable=False),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")
