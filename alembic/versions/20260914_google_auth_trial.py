"""google-only identity and one-question trial

Revision ID: 20260914_01
Revises: 20260831_01
Create Date: 2026-09-14
"""

from alembic import op
import sqlalchemy as sa


revision = "20260914_01"
down_revision = "20260831_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
    op.add_column("users", sa.Column("trial_questions_used", sa.Integer(), nullable=False, server_default="0"))
    op.create_index(op.f("ix_users_google_sub"), "users", ["google_sub"], unique=True)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_google_sub"), table_name="users")
    op.drop_column("users", "trial_questions_used")
    op.drop_column("users", "email")
    op.drop_column("users", "google_sub")
