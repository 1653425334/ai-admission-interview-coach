from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InterviewTurn(Base):
    __tablename__ = "interview_turns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ASKED', 'ANSWERED', 'EVALUATED')",
            name="ck_interview_turns_status",
        ),
        CheckConstraint("sequence_number >= 1", name="ck_interview_turns_sequence"),
        CheckConstraint("followup_index BETWEEN 0 AND 2", name="ck_interview_turns_followup"),
        UniqueConstraint("session_id", "sequence_number", name="uq_interview_turns_session_sequence"),
        Index(
            "uq_interview_turns_open_question",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'ASKED'"),
        ),
        Index("ix_interview_turns_session", "session_id", "sequence_number"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_id: Mapped[str] = mapped_column(String, nullable=False)
    objective_id: Mapped[str] = mapped_column(String, nullable=False)
    question_type: Mapped[str] = mapped_column(String, nullable=False)
    target_condition_ids_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    followup_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_turn_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("interview_turns.id", ondelete="SET NULL"),
        nullable=True,
    )
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ASKED")
    asked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["InterviewSession"] = relationship(back_populates="turns")
    parent_turn: Mapped["InterviewTurn | None"] = relationship(remote_side=[id])
    evaluation: Mapped["InterviewEvaluation | None"] = relationship(
        back_populates="turn", cascade="all, delete-orphan", uselist=False
    )
