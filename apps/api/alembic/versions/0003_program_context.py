"""Add optional target-program context to applications.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("program_url", sa.String(), nullable=True))
    op.add_column("applications", sa.Column("program_description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "program_description")
    op.drop_column("applications", "program_url")
