"""API: chunked static analysis (domain splits + AST + Claude)."""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.db.repository import StaticAnalysisRepository, TrackedRepoRepository
from app.db.session import get_db
from app.models.schemas import (
    StaticAnalysisReportResponse,
    StaticAnalysisReportSummary,
    StaticAnalysisStartRequest,
    StaticAnalysisFindingItem,
    StaticDomainChunk,
)
from app.core.exceptions import DatabaseError
from app.services.static_analysis_engine import (
    resolve_commit_sha,
    resolve_github_target,
    run_static_analysis_job,
)

router = APIRouter(prefix="/static-analysis", tags=["static-analysis"])


def _parse_domains(raw: str | None) -> list:
    if not raw:
        return []
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for name, st in d.items():
        if not isinstance(st, dict):
            continue
        out.append(
            StaticDomainChunk(
                name=name,
                file_count=int(st.get("file_count", 0)),
                files_sample=list(st.get("files_sample") or [])[:20],
                llm_issues_count=int(st.get("llm_issues", 0)),
            )
        )
    return sorted(out, key=lambda x: -x.file_count)


def _parse_findings(raw: str | None) -> list[StaticAnalysisFindingItem]:
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    out: list[StaticAnalysisFindingItem] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            out.append(StaticAnalysisFindingItem.model_validate(it))
        except Exception:
            continue
    return out


def _report_to_response(row) -> StaticAnalysisReportResponse:
    return StaticAnalysisReportResponse(
        id=row.id,
        github_full_name=row.github_full_name,
        commit_sha=row.commit_sha,
        status=row.status,
        summary_markdown=row.summary_markdown,
        domains=_parse_domains(row.domains_json),
        findings=_parse_findings(row.findings_json),
        llm_model=row.llm_model,
        llm_prompt_tokens=row.llm_prompt_tokens,
        llm_completion_tokens=row.llm_completion_tokens,
        error_message=row.error_message,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


@router.post("/start", response_model=StaticAnalysisReportResponse, status_code=202)
def start_static_analysis(
    body: StaticAnalysisStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Queue full-repo static analysis. Resolves the repo from `github_url` or `full_name`,
    ensures the repo is tracked, then processes domains in the background.
    """
    try:
        full_name = resolve_github_target(body.github_url, body.full_name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    repo_store = TrackedRepoRepository(db)
    if not repo_store.exists(full_name):
        repo_store.create(full_name)
    tracked = repo_store.get_by_full_name(full_name)

    try:
        gh = GitHubClient()
        sha = resolve_commit_sha(gh, full_name, body.commit_sha)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"GitHub: {e}")

    sa_store = StaticAnalysisRepository(db)
    report = sa_store.create_pending(full_name, sha, tracked.id)

    background_tasks.add_task(run_static_analysis_job, report.id)
    return _report_to_response(report)


@router.get("/reports", response_model=list[StaticAnalysisReportSummary])
def list_static_reports(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    rows = StaticAnalysisRepository(db).list_recent(limit)
    return [
        StaticAnalysisReportSummary(
            id=r.id,
            github_full_name=r.github_full_name,
            commit_sha=r.commit_sha,
            status=r.status,
            created_at=r.created_at,
            completed_at=r.completed_at,
        )
        for r in rows
    ]


@router.get("/reports/{report_id}", response_model=StaticAnalysisReportResponse)
def get_static_report(
    report_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
):
    try:
        row = StaticAnalysisRepository(db).get_by_id(report_id)
    except DatabaseError:
        raise HTTPException(status_code=404, detail="Report not found")
    return _report_to_response(row)
