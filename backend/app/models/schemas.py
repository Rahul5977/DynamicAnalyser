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


# ── Phase 3 Request Schemas ──────────────────────────────────────

class AnalyseRunRequest(BaseModel):
    force: bool = Field(
        False, description="Force re-analysis even if one already exists."
    )


class SubmitFeedbackRequest(BaseModel):
    suggestion_id: int | None = Field(
        None, description="ID of the specific suggestion being reviewed."
    )
    verdict: str = Field(
        ...,
        pattern=r"^(accepted|rejected|partial)$",
        description="Feedback verdict: accepted, rejected, or partial.",
    )
    comment: str | None = Field(
        None, max_length=2000, description="Optional developer comment."
    )


# ── Phase 3 Response Schemas ─────────────────────────────────────

class SuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rank: int
    title: str
    description: str
    target_function: str | None = None
    target_file: str | None = None
    estimated_saving_ms: int
    effort: str
    diff_hint: str | None = None
    enriched_diff: str | None = None
    confidence_score: float | None = None
    anti_pattern: str | None = None


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pipeline_run_id: int
    repository_id: int
    status: str
    root_cause: str | None = None
    primary_bottleneck: str | None = None
    anti_patterns: list[str] = []
    estimated_total_saving_ms: int | None = None
    suggestions: list[SuggestionResponse] = []
    llm_model: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AnalysisSummary(BaseModel):
    id: int
    pipeline_run_id: int
    status: str
    primary_bottleneck: str | None = None
    estimated_total_saving_ms: int | None = None
    suggestion_count: int
    created_at: datetime


class AntiPatternInsight(BaseModel):
    anti_pattern: str
    occurrence_count: int
    avg_estimated_saving_ms: float
    affected_functions: list[str]


class RepoInsightsResponse(BaseModel):
    repository: str
    total_analyses: int
    anti_patterns: list[AntiPatternInsight]
    most_common_bottleneck: str | None = None
    avg_total_saving_ms: float


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    suggestion_id: int | None = None
    verdict: str
    comment: str | None = None
    created_at: datetime


# ── Phase 4 Response Schemas ─────────────────────────────────────

class DashboardSummary(BaseModel):
    total_repos: int
    total_runs: int
    total_analyses: int
    avg_duration_ms: float
    avg_saving_ms: float
    recent_runs: list[PipelineRunSummary] = []


class DurationTrendPoint(BaseModel):
    run_number: int
    created_at: datetime
    total_duration_ms: int
    p50_ms: int | None = None
    p95_ms: int | None = None


class StepEvolutionPoint(BaseModel):
    run_number: int
    created_at: datetime
    step_name: str
    duration_ms: int
    pct_of_total: float


class FixImpactEntry(BaseModel):
    suggestion_title: str
    anti_pattern: str | None = None
    before_avg_ms: float
    after_avg_ms: float
    improvement_ms: float
    improvement_pct: float


class RepoAnalyticsResponse(BaseModel):
    repository: str
    duration_trend: list[DurationTrendPoint]
    step_evolution: list[StepEvolutionPoint]
    fix_impacts: list[FixImpactEntry]
    anti_pattern_frequency: dict[str, int]


class DemoSeedResponse(BaseModel):
    repos_created: int
    runs_created: int
    analyses_created: int
    message: str


# ── App Log Schemas ───────────────────────────────────────────────────────────

class AppFunctionCallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    function_name: str
    call_number: int
    duration_ms: int
    started_at: datetime | None = None
    ended_at: datetime | None = None
    log_excerpt: str | None = None
    source_function: str | None = None


class AppLogSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    app_name: str
    log_format: str
    source_repo: str | None = None
    total_duration_ms: int | None = None
    total_calls: int | None = None
    status: str
    created_at: datetime


class AppLogSessionDetail(AppLogSessionResponse):
    error_message: str | None = None
    ai_analysis: str | None = None
    function_calls: list[AppFunctionCallResponse] = []


class AppLogUploadResponse(BaseModel):
    session_id: int
    app_name: str
    log_format: str
    status: str
    message: str


class AppLogAnalyseResponse(BaseModel):
    session_id: int
    status: str
    ai_analysis: str | None = None
    message: str
