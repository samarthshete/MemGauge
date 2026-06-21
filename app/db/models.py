"""SQLAlchemy models for MemGauge persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for database models."""


class Memory(Base):
    """Stored memory record and embedding."""

    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_user_id", "user_id"),
        Index(
            "ix_memories_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_memories_active",
            "is_active",
            postgresql_where="is_active",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    superseded_by: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("memories.id"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    events: Mapped[list[MemoryEvent]] = relationship(back_populates="memory")


class MemoryEvent(Base):
    """Audit trail for memory mutations."""

    __tablename__ = "memory_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('ADD','UPDATE','DELETE','NOOP')",
            name="ck_memory_events_event_type",
        ),
        Index("ix_memory_events_memory_id", "memory_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    memory_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("memories.id"),
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    old_content: Mapped[str | None] = mapped_column(Text)
    new_content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    memory: Mapped[Memory | None] = relationship(back_populates="events")


class EvalRun(Base):
    """Aggregate metrics for one evaluation run."""

    __tablename__ = "eval_runs"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    git_sha: Mapped[str | None] = mapped_column(Text)
    backend_mode: Mapped[str] = mapped_column(Text, nullable=False)
    recall_at_5: Mapped[float] = mapped_column(Float, nullable=False)
    precision: Mapped[float] = mapped_column(Float, nullable=False)
    staleness_rate: Mapped[float] = mapped_column(Float, nullable=False)
    false_fact_rate: Mapped[float] = mapped_column(Float, nullable=False)
    p95_search_ms: Mapped[float] = mapped_column(Float, nullable=False)
    p95_add_ms: Mapped[float] = mapped_column(Float, nullable=False)
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    baseline_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))

    case_results: Mapped[list[EvalCaseResult]] = relationship(back_populates="run")


class EvalCaseResult(Base):
    """Per-case evaluation result."""

    __tablename__ = "eval_case_results"
    __table_args__ = (
        CheckConstraint(
            "failure_mode IN ('none','retrieval_miss','stale_fact','false_fact')",
            name="ck_eval_case_results_failure_mode",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("eval_runs.id"),
        nullable=False,
    )
    case_id: Mapped[str] = mapped_column(Text, nullable=False)
    failure_mode: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    retrieved: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped[EvalRun] = relationship(back_populates="case_results")
