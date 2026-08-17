"""Add durable adaptive interview sessions and immutable evaluation events.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interview_map_schema_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("question_budget", sa.Integer(), nullable=False),
        sa.Column("questions_asked", sa.Integer(), nullable=False),
        sa.Column("current_turn_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("final_report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'COMPLETED', 'FAILED')",
            name="ck_interview_sessions_status",
        ),
        sa.CheckConstraint(
            "question_budget BETWEEN 5 AND 8", name="ck_interview_sessions_question_budget"
        ),
        sa.CheckConstraint(
            "questions_asked >= 0 AND questions_asked <= question_budget",
            name="ck_interview_sessions_questions_asked",
        ),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_interview_sessions_application_created",
        "interview_sessions",
        ["application_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_interview_sessions_analysis_run",
        "interview_sessions",
        ["analysis_run_id"],
    )
    op.create_index(
        "uq_interview_sessions_active_application",
        "interview_sessions",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'ACTIVE')"),
    )

    op.create_table(
        "interview_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("risk_id", sa.String(), nullable=False),
        sa.Column("objective_id", sa.String(), nullable=False),
        sa.Column("question_type", sa.String(), nullable=False),
        sa.Column("target_condition_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("followup_index", sa.Integer(), nullable=False),
        sa.Column("parent_turn_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ASKED', 'ANSWERED', 'EVALUATED')", name="ck_interview_turns_status"
        ),
        sa.CheckConstraint("sequence_number >= 1", name="ck_interview_turns_sequence"),
        sa.CheckConstraint("followup_index BETWEEN 0 AND 2", name="ck_interview_turns_followup"),
        sa.ForeignKeyConstraint(["parent_turn_id"], ["interview_turns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence_number", name="uq_interview_turns_session_sequence"),
    )
    op.create_index(
        "ix_interview_turns_session",
        "interview_turns",
        ["session_id", "sequence_number"],
    )
    op.create_index(
        "uq_interview_turns_open_question",
        "interview_turns",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ASKED'"),
    )

    op.create_table(
        "interview_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["interview_turns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id", name="uq_interview_evaluations_turn"),
    )


def downgrade() -> None:
    op.drop_table("interview_evaluations")
    op.drop_index("uq_interview_turns_open_question", table_name="interview_turns")
    op.drop_index("ix_interview_turns_session", table_name="interview_turns")
    op.drop_table("interview_turns")
    op.drop_index("uq_interview_sessions_active_application", table_name="interview_sessions")
    op.drop_index("ix_interview_sessions_analysis_run", table_name="interview_sessions")
    op.drop_index("ix_interview_sessions_application_created", table_name="interview_sessions")
    op.drop_table("interview_sessions")
