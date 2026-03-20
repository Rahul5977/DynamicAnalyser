import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Float,
    ForeignKey,
    Text,
    Index,
    Boolean,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class TrackedRepository(Base):
    __tablename__ = "tracked_repositories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(255), unique=True, nullable=False, index=True)
    owner = Column(String(128), nullable=False)
    name = Column(String(128), nullable=False)
    default_branch = Column(String(128), default="main")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    runs = relationship(
        "PipelineRun", back_populates="repository", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<TrackedRepository {self.full_name}>"


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repository_id = Column(
        Integer, ForeignKey("tracked_repositories.id"), nullable=False
    )
    github_run_id = Column(Integer, nullable=False, index=True)
    run_number = Column(Integer, nullable=False)
    workflow_name = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False)
    conclusion = Column(String(32), nullable=True)
    head_branch = Column(String(255), nullable=True)
    head_sha = Column(String(64), nullable=True)
    total_duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False)
    ingested_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    repository = relationship("TrackedRepository", back_populates="runs")
    step_timings = relationship(
        "StepTiming", back_populates="pipeline_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_run_repo_github", "repository_id", "github_run_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<PipelineRun #{self.run_number} ({self.status})>"


class StepTiming(Base):
    __tablename__ = "step_timings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_run_id = Column(
        Integer, ForeignKey("pipeline_runs.id"), nullable=False
    )
    step_name = Column(String(512), nullable=False)
    step_number = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="success")
    annotation = Column(String(32), nullable=True)
    log_excerpt = Column(Text, nullable=True)

    pipeline_run = relationship("PipelineRun", back_populates="step_timings")

    __table_args__ = (
        Index("ix_step_name_run", "pipeline_run_id", "step_name"),
        Index("ix_step_duration", "step_name", "duration_ms"),
    )

    def __repr__(self) -> str:
        return f"<StepTiming {self.step_name}: {self.duration_ms}ms>"
