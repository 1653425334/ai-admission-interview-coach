from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'COMPLETED', 'FAILED')",
            name="ck_interview_sessions_status",
        ),
        CheckConstraint(
            "question_budget BETWEEN 5 AND 8",
            name="ck_interview_sessions_question_budget",
        ),
        CheckConstraint(
            "questions_asked >= 0 AND questions_asked <= question_budget",
            name="ck_interview_sessions_questions_asked",
        ),
        Index(
            "ix_interview_sessions_application_created",
            "application_id",
            text("created_at DESC"),
        ),
        Index("ix_interview_sessions_analysis_run", "analysis_run_id"),
        Index(
            "uq_interview_sessions_active_application",
            "application_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'ACTIVE')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    application_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    interview_map_schema_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    question_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    questions_asked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_turn_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    final_report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application: Mapped["Application"] = relationship(back_populates="interview_sessions")
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="interview_sessions")
    turns: Mapped[list["InterviewTurn"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="InterviewTurn.sequence_number"
    )
    evaluations: Mapped[list["InterviewEvaluation"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
