"""track user login and activity timestamps

Revision ID: 20260916_01
Revises: 20260914_01
Create Date: 2026-09-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260916_01"
down_revision = "20260914_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("login_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "login_count")
    op.drop_column("users", "last_seen_at")
    op.drop_column("users", "last_login_at")