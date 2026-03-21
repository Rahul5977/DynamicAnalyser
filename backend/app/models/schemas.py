from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# ── Request Schemas ──────────────────────────────────────────────

class AddRepoRequest(BaseModel):
    full_name: str = Field(
        ...,
        min_length=3,
        max_length=255,
        pattern=r"^[a-zA-Z0-9\-_.]+/[a-zA-Z0-9\-_.]+$",
        examples=["octocat/Hello-World"],
        description="GitHub repository in owner/name format",
    )


# ── Response Schemas ─────────────────────────────────────────────

class StepTimingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    step_name: str
    step_number: int
    duration_ms: int
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str
    annotation: str | None = None
    log_excerpt: str | None = None


class PipelineRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    github_run_id: int
    run_number: int
    workflow_name: str | None = None
    status: str
    conclusion: str | None = None
    head_branch: str | None = None
    total_duration_ms: int | None = None
    created_at: datetime
    ingested_at: datetime


class PipelineRunDetail(PipelineRunSummary):
    step_timings: list[StepTimingResponse] = []


class TrackedRepoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    owner: str
    name: str
    default_branch: str
    is_active: bool
    created_at: datetime


class PaginatedRuns(BaseModel):
    total: int
    page: int
    page_size: int
    runs: list[PipelineRunSummary]


class IngestionResult(BaseModel):
    run_id: int
    github_run_id: int
    steps_parsed: int
    total_duration_ms: int
    slowest_step: str
    slowest_step_ms: int


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


# ── Phase 2 Request Schemas ──────────────────────────────────────

class IndexRepoRequest(BaseModel):
    commit_sha: str | None = Field(
        None,
        description="Commit SHA to index. Defaults to HEAD of default branch.",
    )


# ── Phase 2 Response Schemas ─────────────────────────────────────

class SourceLocation(BaseModel):
    file_path: str
    line_number: int
    function_name: str
    qualified_name: str | None = None


class CallChainEntry(BaseModel):
    function_name: str
    file_path: str
    line_number: int


class AnnotatedStep(BaseModel):
    step_name: str
    step_number: int
    duration_ms: int
    status: str
    source_location: SourceLocation | None = None
    call_chain: list[CallChainEntry] = []
    match_confidence: float | None = None
    match_method: str | None = None


class AnnotatedTrace(BaseModel):
    run_id: int
    github_run_id: int
    workflow_name: str | None = None
    total_steps: int
    matched_steps: int
    match_rate: float
    steps: list[AnnotatedStep]


class CodeIndexResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    commit_sha: str
    total_functions: int
    total_log_calls: int
    language_breakdown: dict[str, int] = {}
    status: str
    created_at: datetime


class StepStatsResponse(BaseModel):
    step_name: str
    sample_count: int
    mean_ms: float
    p50_ms: int
    p95_ms: int
    std_dev_ms: float
    trend_slope: float
    latest_ms: int


class BottleneckEntry(BaseModel):
    rank: int
    step_name: str
    composite_score: float
    pct_of_total: float
    anomaly_score: float | None = None
    trend_direction: str
    mean_ms: float
    p50_ms: int
    p95_ms: int
    source_location: SourceLocation | None = None


class BottleneckReport(BaseModel):
    repository: str
    analysis_window: int
    total_runs_analyzed: int
    bottlenecks: list[BottleneckEntry]
