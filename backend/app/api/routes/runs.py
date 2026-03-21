from fastapi import APIRouter, Depends, Path, Query, HTTPException
from sqlalchemy.orm import Session

from app.core.exceptions import DynamicAnalyserError, to_http_exception
from app.db.repository import PipelineRunRepository
from app.db.session import get_db
from app.models.schemas import PipelineRunDetail, IngestionResult, AnnotatedTrace
from app.services.ingester import LogIngester
from app.services.trace_correlator import TraceCorrelator

router = APIRouter(prefix="/runs")


@router.get("/{run_id}", response_model=PipelineRunDetail)
def get_run(run_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    try:
        run_store = PipelineRunRepository(db)
        run = run_store.get_by_id(run_id)
        # Sort step_timings by duration_ms descending
        run.step_timings = sorted(
            run.step_timings, key=lambda s: s.duration_ms, reverse=True
        )
        return run
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.post("/{run_id}/ingest", response_model=IngestionResult)
def ingest_run(
    run_id: int = Path(..., description="GitHub Actions run ID"),
    repo: str = Query(..., description="Full repository name (owner/repo)"),
    db: Session = Depends(get_db),
):
    """Trigger log fetch + parse for a GitHub Actions run."""
    try:
        ingester = LogIngester(db)
        return ingester.ingest_run(repo, run_id)
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.get("/{run_id}/trace", response_model=AnnotatedTrace)
def get_trace(run_id: int = Path(..., ge=1), db: Session = Depends(get_db)):
    """Return annotated trace with source code locations for a run."""
    try:
        correlator = TraceCorrelator(db)
        return correlator.correlate_run(run_id)
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e
