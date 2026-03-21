"""Phase 2 API routes: code indexing, bottleneck ranking, step stats."""

import datetime
import json

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import DynamicAnalyserError, to_http_exception
from app.db.repository import (
    CodeIndexRepository,
    PipelineRunRepository,
    TrackedRepoRepository,
)
from app.db.session import get_db
from app.models.database import CodeIndex, IndexedFunction, IndexedLogCall
from app.models.schemas import (
    BottleneckEntry,
    BottleneckReport,
    CodeIndexResponse,
    IndexRepoRequest,
    StepStatsResponse,
)
from app.services.ast_parser import CodeIndexer, ASTParser
from app.services.bottleneck_ranker import BottleneckRanker
from app.services.github_client import GitHubClient

router = APIRouter(prefix="/repos")


@router.post(
    "/{owner}/{name}/index",
    response_model=CodeIndexResponse,
    status_code=201,
)
def index_repo(
    owner: str,
    name: str,
    request: IndexRepoRequest | None = None,
    db: Session = Depends(get_db),
):
    """Trigger AST indexing + call graph build for a repository."""
    try:
        full_name = f"{owner}/{name}"
        repo_store = TrackedRepoRepository(db)
        tracked_repo = repo_store.get_by_full_name(full_name)

        github = GitHubClient()

        # Determine commit SHA
        commit_sha = request.commit_sha if request and request.commit_sha else None
        if not commit_sha:
            # Get HEAD SHA from latest workflow run or repo default branch
            runs = github.get_workflow_runs(full_name, limit=1)
            if runs:
                commit_sha = runs[0].head_sha
            else:
                # Fetch default branch HEAD
                repo_obj = github._get_repo(full_name)
                commit_sha = repo_obj.get_branch(
                    tracked_repo.default_branch
                ).commit.sha

        # Check if already indexed
        idx_store = CodeIndexRepository(db)
        existing = idx_store.get_by_repo_and_sha(tracked_repo.id, commit_sha)
        if existing and existing.status == "completed":
            breakdown = json.loads(existing.language_breakdown) if existing.language_breakdown else {}
            return CodeIndexResponse(
                id=existing.id,
                commit_sha=existing.commit_sha,
                total_functions=existing.total_functions,
                total_log_calls=existing.total_log_calls,
                language_breakdown=breakdown,
                status=existing.status,
                created_at=existing.created_at,
            )

        # Create pending index record
        code_index = CodeIndex(
            repository_id=tracked_repo.id,
            commit_sha=commit_sha,
            status="running",
        )
        code_index = idx_store.create(code_index)

        # Build the index
        try:
            indexer = CodeIndexer(github)
            index_data = indexer.build_index(full_name, commit_sha)

            # Persist functions and log calls
            db_functions = [
                IndexedFunction(
                    function_name=f.name,
                    qualified_name=f.qualified_name,
                    file_path=f.file_path,
                    line_number=f.line_number,
                    end_line_number=f.end_line_number,
                    language=f.language,
                    calls_json=json.dumps(f.calls) if f.calls else None,
                )
                for f in index_data.functions
            ]
            db_log_calls = [
                IndexedLogCall(
                    log_string=lc.log_string,
                    file_path=lc.file_path,
                    line_number=lc.line_number,
                    function_name=lc.function_name,
                    log_level=lc.log_level,
                    language=lc.language,
                )
                for lc in index_data.log_calls
            ]
            idx_store.save_functions_and_log_calls(
                code_index.id, db_functions, db_log_calls
            )

            idx_store.update_status(
                code_index.id,
                status="completed",
                completed_at=datetime.datetime.utcnow(),
                total_functions=len(index_data.functions),
                total_log_calls=len(index_data.log_calls),
                language_breakdown=index_data.language_breakdown,
            )

            return CodeIndexResponse(
                id=code_index.id,
                commit_sha=commit_sha,
                total_functions=len(index_data.functions),
                total_log_calls=len(index_data.log_calls),
                language_breakdown=index_data.language_breakdown,
                status="completed",
                created_at=code_index.created_at,
            )

        except Exception as e:
            idx_store.update_status(
                code_index.id, status="failed", error_message=str(e)
            )
            raise

    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.get("/{owner}/{name}/bottlenecks", response_model=BottleneckReport)
def get_bottlenecks(
    owner: str,
    name: str,
    window: int = Query(50, ge=5, le=200),
    top_n: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
):
    """Return ranked bottleneck steps for a repository."""
    try:
        full_name = f"{owner}/{name}"
        repo_store = TrackedRepoRepository(db)
        tracked_repo = repo_store.get_by_full_name(full_name)

        ranker = BottleneckRanker(db)
        entries, total_analyzed = ranker.rank_bottlenecks(
            tracked_repo.id, last_n=window, top_n=top_n
        )

        bottlenecks = [
            BottleneckEntry(
                rank=e["rank"],
                step_name=e["step_name"],
                composite_score=e["composite_score"],
                pct_of_total=e["pct_of_total"],
                anomaly_score=e["anomaly_score"],
                trend_direction=e["trend_direction"],
                mean_ms=e["mean_ms"],
                p50_ms=e["p50_ms"],
                p95_ms=e["p95_ms"],
                source_location=None,
            )
            for e in entries
        ]

        return BottleneckReport(
            repository=full_name,
            analysis_window=window,
            total_runs_analyzed=total_analyzed,
            bottlenecks=bottlenecks,
        )

    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


@router.get(
    "/{owner}/{name}/step/{step_name}/stats",
    response_model=StepStatsResponse,
)
def get_step_stats(
    owner: str,
    name: str,
    step_name: str,
    window: int = Query(50, ge=5, le=200),
    db: Session = Depends(get_db),
):
    """Return statistics for a specific step."""
    try:
        full_name = f"{owner}/{name}"
        repo_store = TrackedRepoRepository(db)
        tracked_repo = repo_store.get_by_full_name(full_name)

        ranker = BottleneckRanker(db)
        stats = ranker.compute_stats(tracked_repo.id, step_name, window)

        return StepStatsResponse(
            step_name=stats.step_name,
            sample_count=stats.sample_count,
            mean_ms=round(stats.mean_ms, 1),
            p50_ms=stats.p50_ms,
            p95_ms=stats.p95_ms,
            std_dev_ms=round(stats.std_dev_ms, 1),
            trend_slope=round(stats.trend_slope, 2),
            latest_ms=stats.latest_ms,
        )

    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e
