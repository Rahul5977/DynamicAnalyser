import datetime
from sqlalchemy import (
    BigInteger,
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
    github_run_id = Column(BigInteger, nullable=False, index=True)
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
    source_function = Column(String(512), nullable=True)

    pipeline_run = relationship("PipelineRun", back_populates="step_timings")

    __table_args__ = (
        Index("ix_step_name_run", "pipeline_run_id", "step_name"),
        Index("ix_step_duration", "step_name", "duration_ms"),
    )

    def __repr__(self) -> str:
        return f"<StepTiming {self.step_name}: {self.duration_ms}ms>"


class CodeIndex(Base):
    __tablename__ = "code_indexes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repository_id = Column(
        Integer, ForeignKey("tracked_repositories.id"), nullable=False
    )
    commit_sha = Column(String(64), nullable=False)
    language_breakdown = Column(Text, nullable=True)
    total_functions = Column(Integer, default=0)
    total_log_calls = Column(Integer, default=0)
    status = Column(String(32), default="pending", nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    repository = relationship("TrackedRepository")
    functions = relationship(
        "IndexedFunction", back_populates="code_index", cascade="all, delete-orphan"
    )
    log_calls = relationship(
        "IndexedLogCall", back_populates="code_index", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_code_index_repo_sha", "repository_id", "commit_sha", unique=True),
    )

    def __repr__(self) -> str:
        return f"<CodeIndex {self.commit_sha[:8]} ({self.status})>"


class IndexedFunction(Base):
    __tablename__ = "indexed_functions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code_index_id = Column(
        Integer, ForeignKey("code_indexes.id"), nullable=False
    )
    function_name = Column(String(512), nullable=False)
    qualified_name = Column(String(1024), nullable=True)
    file_path = Column(String(1024), nullable=False)
    line_number = Column(Integer, nullable=False)
    end_line_number = Column(Integer, nullable=True)
    language = Column(String(32), nullable=False)
    calls_json = Column(Text, nullable=True)

    code_index = relationship("CodeIndex", back_populates="functions")

    __table_args__ = (
        Index("ix_func_name", "code_index_id", "function_name"),
    )

    def __repr__(self) -> str:
        return f"<IndexedFunction {self.function_name} @ {self.file_path}:{self.line_number}>"


class IndexedLogCall(Base):
    __tablename__ = "indexed_log_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code_index_id = Column(
        Integer, ForeignKey("code_indexes.id"), nullable=False
    )
    log_string = Column(Text, nullable=False)
    file_path = Column(String(1024), nullable=False)
    line_number = Column(Integer, nullable=False)
    function_name = Column(String(512), nullable=True)
    log_level = Column(String(32), nullable=True)
    language = Column(String(32), nullable=False)

    code_index = relationship("CodeIndex", back_populates="log_calls")

    __table_args__ = (
        Index("ix_log_call_index", "code_index_id"),
    )

    def __repr__(self) -> str:
        return f"<IndexedLogCall '{self.log_string[:30]}' @ {self.file_path}:{self.line_number}>"


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_run_id = Column(
        Integer, ForeignKey("pipeline_runs.id"), nullable=False
    )
    repository_id = Column(
        Integer, ForeignKey("tracked_repositories.id"), nullable=False
    )
    status = Column(String(32), default="pending", nullable=False)
    root_cause = Column(Text, nullable=True)
    primary_bottleneck = Column(String(512), nullable=True)
    anti_patterns_json = Column(Text, nullable=True)
    estimated_total_saving_ms = Column(Integer, nullable=True)
    raw_llm_response = Column(Text, nullable=True)
    llm_model = Column(String(128), nullable=True)
    llm_prompt_tokens = Column(Integer, nullable=True)
    llm_completion_tokens = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    pipeline_run = relationship("PipelineRun")
    repository = relationship("TrackedRepository")
    suggestions = relationship(
        "AnalysisSuggestion", back_populates="analysis", cascade="all, delete-orphan"
    )
    feedback = relationship(
        "AnalysisFeedback", back_populates="analysis", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_analysis_run", "pipeline_run_id"),
        Index("ix_analysis_repo", "repository_id"),
    )

    def __repr__(self) -> str:
        return f"<Analysis run={self.pipeline_run_id} ({self.status})>"


class AnalysisSuggestion(Base):
    __tablename__ = "analysis_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(
        Integer, ForeignKey("analyses.id"), nullable=False
    )
    rank = Column(Integer, nullable=False)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=False)
    target_function = Column(String(512), nullable=True)
    target_file = Column(String(1024), nullable=True)
    estimated_saving_ms = Column(Integer, nullable=False, default=0)
    effort = Column(String(32), nullable=False, default="medium")
    diff_hint = Column(Text, nullable=True)
    enriched_diff = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)
    anti_pattern = Column(String(256), nullable=True)

    analysis = relationship("Analysis", back_populates="suggestions")

    __table_args__ = (
        Index("ix_suggestion_analysis", "analysis_id"),
    )

    def __repr__(self) -> str:
        return f"<AnalysisSuggestion #{self.rank}: {self.title}>"


class AnalysisFeedback(Base):
    __tablename__ = "analysis_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(
        Integer, ForeignKey("analyses.id"), nullable=False
    )
    suggestion_id = Column(
        Integer, ForeignKey("analysis_suggestions.id"), nullable=True
    )
    verdict = Column(String(32), nullable=False)  # accepted / rejected / partial
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    analysis = relationship("Analysis", back_populates="feedback")

    __table_args__ = (
        Index("ix_feedback_analysis", "analysis_id"),
    )


# ── App Log Analysis Tables ───────────────────────────────────────────────────

class AppLogSession(Base):
    """A single uploaded application log file to be analysed."""

    __tablename__ = "app_log_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    app_name = Column(String(255), nullable=False)          # e.g. "nginx", "tshark"
    log_file_path = Column(String(512), nullable=False)     # saved upload path
    log_format = Column(String(64), nullable=False)         # auto|tshark|syslog|json|custom
    source_repo = Column(String(255), nullable=True)        # GitHub URL or None
    custom_pattern = Column(String(512), nullable=True)     # user regex for custom format
    total_duration_ms = Column(Integer, nullable=True)      # sum of all function call durations
    total_calls = Column(Integer, nullable=True)            # number of parsed function calls
    status = Column(String(32), nullable=False, default="pending")  # pending|completed|failed
    error_message = Column(Text, nullable=True)
    ai_analysis = Column(Text, nullable=True)               # JSON blob from LLM
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    function_calls = relationship(
        "AppFunctionCall", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_app_session_status", "status"),
        Index("ix_app_session_app_name", "app_name"),
    )

    def __repr__(self) -> str:
        return f"<AppLogSession id={self.id} app={self.app_name} status={self.status}>"


class AppFunctionCall(Base):
    """A single function-call timing entry extracted from an application log."""

    __tablename__ = "app_function_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("app_log_sessions.id"), nullable=False)
    function_name = Column(String(512), nullable=False)
    call_number = Column(Integer, nullable=False, default=1)    # nth call of this function
    duration_ms = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    log_excerpt = Column(Text, nullable=True)                   # surrounding log lines
    source_function = Column(String(512), nullable=True)        # correlated source symbol

    session = relationship("AppLogSession", back_populates="function_calls")

    __table_args__ = (
        Index("ix_appcall_session", "session_id"),
        Index("ix_appcall_func_name", "session_id", "function_name"),
    )

    def __repr__(self) -> str:
        return f"<AppFunctionCall {self.function_name} #{self.call_number} {self.duration_ms}ms>"
