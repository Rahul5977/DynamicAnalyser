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
