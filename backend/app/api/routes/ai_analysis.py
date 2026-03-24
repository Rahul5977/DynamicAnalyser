"""Phase 3 API routes: AI analysis, insights, and feedback."""

import json

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.core.exceptions import AnalysisNotFoundError, DynamicAnalyserError, to_http_exception
from app.db.repository import AnalysisRepository, TrackedRepoRepository
from app.db.session import get_db
from app.models.database import AnalysisFeedback
from app.models.schemas import (
    AnalyseRunRequest,
    AnalysisResponse,
    AntiPatternInsight,
    FeedbackResponse,
    RepoInsightsResponse,
    SubmitFeedbackRequest,
    SuggestionResponse,
)
from app.services.ai_engine import AIEngine
from app.services.fix_recommender import FixRecommender

router = APIRouter()


def _analysis_to_response(analysis) -> AnalysisResponse:
    """Convert an Analysis ORM object to an AnalysisResponse schema."""
    anti_patterns = []
    if analysis.anti_patterns_json:
        try:
            anti_patterns = json.loads(analysis.anti_patterns_json)
        except (json.JSONDecodeError, TypeError):
            pass

    suggestions = [
        SuggestionResponse(
            id=s.id,
            rank=s.rank,
            title=s.title,
            description=s.description,
            target_function=s.target_function,
            target_file=s.target_file,
            estimated_saving_ms=s.estimated_saving_ms,
            effort=s.effort,
            diff_hint=s.diff_hint,
            enriched_diff=s.enriched_diff,
            confidence_score=s.confidence_score,
            anti_pattern=s.anti_pattern,
        )
        for s in sorted(analysis.suggestions, key=lambda s: s.rank)
    ]

    return AnalysisResponse(
        id=analysis.id,
        pipeline_run_id=analysis.pipeline_run_id,
        repository_id=analysis.repository_id,
        status=analysis.status,
        root_cause=analysis.root_cause,
        primary_bottleneck=analysis.primary_bottleneck,
        anti_patterns=anti_patterns,
        estimated_total_saving_ms=analysis.estimated_total_saving_ms,
        suggestions=suggestions,
        llm_model=analysis.llm_model,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
    )


@router.post(
    "/runs/{run_id}/analyse",
    response_model=AnalysisResponse,
    status_code=201,
)
def analyse_run(
    run_id: int = Path(..., ge=1),
    request: AnalyseRunRequest | None = None,
    db: Session = Depends(get_db),
):
    """Trigger full AI analysis for a pipeline run."""
    try:
        force = request.force if request else False
        engine = AIEngine(db)
        analysis = engine.analyse_run(run_id, force=force)

        # Enrich suggestions with diffs and confidence
        recommender = FixRecommender(db)
        analysis = recommender.enrich_analysis(analysis)

        return _analysis_to_response(analysis)
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisResponse,
)
def get_analysis(
    analysis_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
):
    """Return full analysis with suggestions."""
    try:
        store = AnalysisRepository(db)
        analysis = store.get_by_id(analysis_id)
        return _analysis_to_response(analysis)
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.get(
    "/runs/{run_id}/analysis/latest",
    response_model=AnalysisResponse,
)
def get_latest_analysis(
    run_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
):
    """Return the most recent completed analysis for a run."""
    try:
        store = AnalysisRepository(db)
        analysis = store.get_latest_for_run(run_id)
        if not analysis:
            raise AnalysisNotFoundError(
                f"No completed analysis found for run {run_id}"
            )
        return _analysis_to_response(analysis)
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.get(
    "/repos/{owner}/{name}/insights",
    response_model=RepoInsightsResponse,
)
def get_repo_insights(
    owner: str,
    name: str,
    db: Session = Depends(get_db),
):
    """Aggregate anti-pattern insights across all analyses for a repo."""
    try:
        full_name = f"{owner}/{name}"
        repo_store = TrackedRepoRepository(db)
        repo = repo_store.get_by_full_name(full_name)

        recommender = FixRecommender(db)
        insights = recommender.get_repo_insights(repo.id)

        return RepoInsightsResponse(
            repository=full_name,
            total_analyses=insights["total_analyses"],
            anti_patterns=[
                AntiPatternInsight(**ap) for ap in insights["anti_patterns"]
            ],
            most_common_bottleneck=insights["most_common_bottleneck"],
            avg_total_saving_ms=insights["avg_total_saving_ms"],
        )
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.post(
    "/analyses/{analysis_id}/feedback",
    response_model=FeedbackResponse,
    status_code=201,
)
def submit_feedback(
    analysis_id: int = Path(..., ge=1),
    request: SubmitFeedbackRequest = ...,
    db: Session = Depends(get_db),
):
    """Record developer feedback on an analysis suggestion."""
    try:
        store = AnalysisRepository(db)
        # Validate analysis exists
        store.get_by_id(analysis_id)

        feedback = AnalysisFeedback(
            analysis_id=analysis_id,
            suggestion_id=request.suggestion_id,
            verdict=request.verdict,
            comment=request.comment,
        )
        feedback = store.add_feedback(feedback)
        return feedback
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e
