from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.exceptions import DynamicAnalyserError, to_http_exception
from app.db.repository import TrackedRepoRepository, PipelineRunRepository
from app.db.session import get_db
from app.models.schemas import (
    AddRepoRequest,
    TrackedRepoResponse,
    PaginatedRuns,
    PipelineRunSummary,
)
from app.services.github_client import GitHubClient

router = APIRouter(prefix="/repos")


@router.get("", response_model=list[TrackedRepoResponse])
def list_repos(db: Session = Depends(get_db)):
    try:
        repo_store = TrackedRepoRepository(db)
        repos = repo_store.list_all()
        return repos
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.post("", response_model=TrackedRepoResponse, status_code=201)
def add_repo(request: AddRepoRequest, db: Session = Depends(get_db)):
    try:
        repo_store = TrackedRepoRepository(db)
        if repo_store.exists(request.full_name):
            existing = repo_store.get_by_full_name(request.full_name)
            return existing
        return repo_store.create(request.full_name)
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.get("/{owner}/{name}/github-runs")
def list_github_runs(
    owner: str,
    name: str,
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Return recent completed GitHub Actions run IDs available for ingestion."""
    try:
        full_name = f"{owner}/{name}"
        github = GitHubClient()
        # Fetch more than needed so we can filter to completed runs
        all_runs = github.get_workflow_runs(full_name, limit=limit * 4)
        completed = [
            r for r in all_runs
            if r.conclusion in ("success", "failure", "cancelled")
        ][:limit]
        return [
            {
                "run_id": r.run_id,
                "run_number": r.run_number,
                "workflow_name": r.workflow_name,
                "conclusion": r.conclusion,
                "head_branch": r.head_branch,
                "created_at": r.created_at.isoformat(),
            }
            for r in completed
        ]
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.get("/{owner}/{name}/runs", response_model=PaginatedRuns)
def list_runs(
    owner: str,
    name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        full_name = f"{owner}/{name}"
        repo_store = TrackedRepoRepository(db)
        tracked_repo = repo_store.get_by_full_name(full_name)

        run_store = PipelineRunRepository(db)
        runs, total = run_store.list_by_repo(tracked_repo.id, page, page_size)

        return PaginatedRuns(
            total=total,
            page=page,
            page_size=page_size,
            runs=[PipelineRunSummary.model_validate(r) for r in runs],
        )
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e
