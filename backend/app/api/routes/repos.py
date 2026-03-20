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
