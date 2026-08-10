"""Add durable Milestone 2 analysis persistence.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("parser_version", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))

    op.create_table(
        "analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("input_manifest_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("interview_map_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="ck_analysis_runs_status",
        ),
        sa.CheckConstraint(
            "stage IN ('QUEUED', 'PARSE_DOCUMENTS', 'BUILD_INTERVIEW_MAP', 'COMPLETED', 'FAILED')",
            name="ck_analysis_runs_stage",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_analysis_runs_application_created",
        "analysis_runs",
        ["application_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "uq_analysis_runs_active_application",
        "analysis_runs",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING')"),
    )
    op.create_index(
        "uq_analysis_runs_idempotency_key",
        "analysis_runs",
        ["application_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("job_type IN ('ANALYZE_APPLICATION')", name="ck_jobs_job_type"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')", name="ck_jobs_status"
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_attempts_nonnegative"),
        sa.ForeignKeyConstraint(["entity_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_type", "entity_id", name="uq_jobs_type_entity"),
    )
    op.create_index("ix_jobs_claim", "jobs", ["status", "available_at", "created_at"])

    op.create_table(
        "llm_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')", name="ck_llm_runs_status"
        ),
        sa.ForeignKeyConstraint(["entity_id"], ["analysis_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_llm_runs_entity_created", "llm_runs", ["entity_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_llm_runs_entity_created", table_name="llm_runs")
    op.drop_table("llm_runs")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("uq_analysis_runs_idempotency_key", table_name="analysis_runs")
    op.drop_index("uq_analysis_runs_active_application", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_application_created", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    op.drop_column("documents", "page_count")
    op.drop_column("documents", "parser_version")
    op.drop_column("documents", "parsed_at")
