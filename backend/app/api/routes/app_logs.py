"""
app_logs.py
-----------
All API routes for the Application Log Analysis feature (Phases 1–5).

Endpoints
─────────
POST  /api/app-logs/detect-format                      Phase 3: preview format + first records
POST  /api/app-logs/upload                             Phase 1: multipart upload + parse
GET   /api/app-logs/sessions                           list sessions
GET   /api/app-logs/sessions/{id}                      session detail + function calls
POST  /api/app-logs/sessions/{id}/index-source         Phase 4: trigger code index for source_repo
GET   /api/app-logs/sessions/{id}/trace                Phase 4: source-correlated calls
POST  /api/app-logs/sessions/{id}/analyse              Phase 5: run AI analysis
GET   /api/app-logs/sessions/{id}/analysis             Phase 5: latest analysis for session
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.logging import logger
from app.db.session import get_db
from app.models.database import (
    AppFunctionCall,
    AppLogSession,
    Analysis,
    AnalysisSuggestion,
    AnalysisFeedback,
)
from app.models.schemas import (
    AnalysisResponse,
    AppFunctionCallResponse,
    AppLogSessionDetail,
    AppLogSessionResponse,
    AppLogUploadResponse,
    AppTraceResponse,
    DetectFormatResponse,
    SampleRecord,
    SuggestionResponse,
)
from pydantic import BaseModel

from app.services.app_ingester import AppIngester
from app.services.app_log_parser import parse_to_universal

router = APIRouter()


class AppAnalyseRequest(BaseModel):
    target_functions: list[str] | None = None


class AppFeedbackRequest(BaseModel):
    suggestion_id: int
    verdict: str
    comment: str | None = None
settings = get_settings()

_ALLOWED_FORMATS = {"auto", "unknown", "json", "syslog", "tshark", "logfmt",
                    "spring", "rails", "enter_exit", "heuristic", "custom", "radcom"}
_MAX_BYTES = settings.APP_LOG_MAX_SIZE_MB * 1024 * 1024


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Detect format (called client-side before full upload)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/app-logs/detect-format", response_model=DetectFormatResponse)
async def detect_format_endpoint(
    payload: Annotated[dict, Body()],
    db: Session = Depends(get_db),
):
    """
    Accept the first 50 lines of a log file as JSON `{"lines": [...]}`.
    Returns detected format, confidence score, and up to 5 preview records.
    Called instantly after the user drops a file — before full upload.
    """
    lines: list[str] = payload.get("lines", [])
    app_name: str = payload.get("app_name", "")
    custom_pattern: str = payload.get("custom_pattern", "")

    if not lines:
        raise HTTPException(status_code=422, detail="'lines' array is required")

    from app.services.app_log_parser import detect_format as _detect
    fmt, confidence = _detect(lines)

    # Parse first 5 records for preview
    _, records = parse_to_universal(lines, fmt=fmt, custom_pattern=custom_pattern)
    sample = [
        SampleRecord(
            func_name=r.func_name,
            duration_ms=r.duration_ms,
            log_excerpt=(r.log_excerpt or "")[:200],
        )
        for r in records[:5]
    ]

    # If confidence is low, try AI schema inference and re-run
    if confidence < 0.3 and app_name and settings.ANTHROPIC_API_KEY:
        try:
            from app.services.log_schema_inferrer import AISchemaInferrer
            inferrer = AISchemaInferrer(db)
            schema = inferrer.infer(lines, app_name=app_name)
            if schema and schema.func_regex:
                # Use the inferred patterns to try a custom parse
                import re as _re
                patterns = " ".join(filter(None, [
                    schema.ts_regex, schema.func_regex, schema.elapsed_regex
                ]))
                _, ai_recs = parse_to_universal(lines, fmt="custom", custom_pattern=patterns)
                if ai_recs:
                    fmt = "ai_inferred"
                    confidence = 0.7
                    sample = [
                        SampleRecord(
                            func_name=r.func_name,
                            duration_ms=r.duration_ms,
                            log_excerpt=(r.log_excerpt or "")[:200],
                        )
                        for r in ai_recs[:5]
                    ]
        except Exception as e:
            logger.warning("AI schema inference failed: %s", e)

    return DetectFormatResponse(
        format=fmt,
        confidence=round(confidence, 3),
        sample_records=sample,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Upload + parse
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/app-logs/upload", response_model=AppLogUploadResponse, status_code=201)
async def upload_app_log(
    file: UploadFile = File(...),
    app_name: str = Form(..., max_length=255),
    log_format: str = Form("auto"),
    source_repo: str = Form(""),
    custom_pattern: str = Form(""),
    db: Session = Depends(get_db),
):
    """
    Accept a multipart log file upload, parse it, store results.

    - **file**: plain-text log (.log / .txt / any text format)
    - **app_name**: human label, e.g. "nginx", "tshark", "my-service"
    - **log_format**: auto | json | syslog | tshark | logfmt | spring | rails | enter_exit | custom
    - **source_repo**: optional GitHub URL for source correlation
    - **custom_pattern**: named-group regex (when log_format=custom)
    """
    if log_format not in _ALLOWED_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid log_format. Choose from: {sorted(_ALLOWED_FORMATS)}",
        )

    contents = await file.read()
    if len(contents) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum is {settings.APP_LOG_MAX_SIZE_MB} MB.",
        )

    upload_dir = os.path.abspath(settings.APP_LOG_UPLOAD_DIR)
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{os.path.basename(file.filename or 'upload.log')}"
    file_path = os.path.join(upload_dir, safe_name)
    with open(file_path, "wb") as fh:
        fh.write(contents)

    session = AppLogSession(
        app_name=app_name.strip(),
        log_file_path=file_path,
        log_format=log_format,
        source_repo=source_repo.strip() or None,
        custom_pattern=custom_pattern.strip() or None,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        ingester = AppIngester(db)
        ingester.ingest_file(
            session_id=session.id,
            file_path=file_path,
            log_format=log_format,
            custom_pattern=custom_pattern.strip(),
        )
        db.refresh(session)
    except Exception as e:
        logger.error("Ingestion failed for session %d: %s", session.id, e)

    return AppLogUploadResponse(
        session_id=session.id,
        app_name=session.app_name,
        log_format=session.log_format,
        status=session.status,
        message=(
            f"Parsed {session.total_calls or 0} function call(s) "
            f"totalling {session.total_duration_ms or 0} ms."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# List sessions
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/app-logs/sessions", response_model=list[AppLogSessionResponse])
def list_app_sessions(db: Session = Depends(get_db)):
    """Return all sessions, newest first."""
    return (
        db.query(AppLogSession)
        .order_by(AppLogSession.created_at.desc())
        .all()
    )
# ─────────────────────────────────────────────────────────────────────────────
# Session detail
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/app-logs/sessions/{session_id}", response_model=AppLogSessionDetail)
def get_app_session(session_id: int, db: Session = Depends(get_db)):
    """Return one session with all its parsed function calls."""
    session = db.get(AppLogSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    calls = (
        db.query(AppFunctionCall)
        .filter(AppFunctionCall.session_id == session_id)
        .order_by(AppFunctionCall.duration_ms.desc())
        .all()
    )

    return AppLogSessionDetail(
        id=session.id,
        app_name=session.app_name,
        log_format=session.log_format,
        source_repo=session.source_repo,
        total_duration_ms=session.total_duration_ms,
        total_calls=session.total_calls,
        status=session.status,
        error_message=session.error_message,
        ai_analysis=session.ai_analysis,
        created_at=session.created_at,
        function_calls=[
            AppFunctionCallResponse(
                id=c.id,
                function_name=c.function_name,
                call_number=c.call_number,
                duration_ms=c.duration_ms,
                started_at=c.started_at,
                ended_at=c.ended_at,
                log_excerpt=c.log_excerpt,
                source_function=c.source_function,
                source_file=c.source_file,
                source_line=c.source_line,
                call_chain_json=c.call_chain_json,
            )
            for c in calls
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 — Index source repo
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/app-logs/sessions/{session_id}/index-source")
def index_source_for_session(
    session_id: int,
    payload: Annotated[dict, Body()] = {},
    db: Session = Depends(get_db),
):
    """
    Trigger AST indexing for this session's source repository.

    Body (optional): `{"github_url": "https://github.com/owner/repo"}`

    If `github_url` is provided it overrides the one stored on the session.
    Reuses the existing CodeIndexer — just points it at a TrackedRepository.
    """
    session = db.get(AppLogSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    github_url = (payload.get("github_url") or session.source_repo or "").strip()
    if not github_url:
        raise HTTPException(
            status_code=400,
            detail="Provide a github_url in the request body or set source_repo on the session.",
        )

    # Update session.source_repo if a new URL was given
    if payload.get("github_url") and payload["github_url"] != session.source_repo:
        session.source_repo = github_url
        db.commit()

    # Parse owner/repo
    from app.services.app_trace_correlator import _parse_github_url
    repo_name = _parse_github_url(github_url)
    if not repo_name:
        raise HTTPException(status_code=422, detail=f"Cannot parse GitHub URL: {github_url}")

    # Ensure repo is tracked
    from app.db.repository import TrackedRepoRepository
    repo_store = TrackedRepoRepository(db)
    if not repo_store.exists(repo_name):
        try:
            repo_store.create(repo_name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to track repo: {e}")

    repo = repo_store.get_by_full_name(repo_name)

    # Trigger indexing
    try:
        from app.services.ast_parser import CodeIndexer
        indexer = CodeIndexer(db)
        result = indexer.index_repo(repo.id, repo_name)
        return {
            "status": "completed",
            "repo": repo_name,
            "commit_sha": result.commit_sha,
            "total_functions": result.total_functions,
        }
    except Exception as e:
        logger.error("Source indexing failed for session %d: %s", session_id, e)
        raise HTTPException(status_code=500, detail=f"Indexing failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 — Source trace
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/app-logs/sessions/{session_id}/trace", response_model=AppTraceResponse)
def get_app_trace(session_id: int, db: Session = Depends(get_db)):
    """
    Return source-correlated function calls for a session.
    Runs correlation on demand (idempotent — re-correlates each call).
    """
    session = db.get(AppLogSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    if session.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Session not completed (status={session.status})",
        )

    from app.services.app_trace_correlator import AppTraceCorrelator
    try:
        correlator = AppTraceCorrelator(db)
        return correlator.correlate_session(session_id)
    except Exception as e:
        logger.error("Trace correlation failed for session %d: %s", session_id, e)
        raise HTTPException(status_code=500, detail=f"Correlation failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5 — AI Analysis
# ─────────────────────────────────────────────────────────────────────────────

def _analysis_to_response(analysis: Analysis) -> AnalysisResponse:
    import json as _json
    anti = []
    if analysis.anti_patterns_json:
        try: anti = _json.loads(analysis.anti_patterns_json)
        except _json.JSONDecodeError: pass

    return AnalysisResponse(
        id=analysis.id,
        pipeline_run_id=analysis.pipeline_run_id or 0,
        repository_id=analysis.repository_id or 0,
        status=analysis.status,
        root_cause=analysis.root_cause,
        primary_bottleneck=analysis.primary_bottleneck,
        anti_patterns=anti,
        estimated_total_saving_ms=analysis.estimated_total_saving_ms,
        suggestions=[
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
            for s in (analysis.suggestions or [])
        ],
        llm_model=analysis.llm_model,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
    )


@router.post(
    "/app-logs/sessions/{session_id}/analyse",
    response_model=AnalysisResponse,
)
def analyse_app_session(
    session_id: int,
    force: bool = False,
    payload: AppAnalyseRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    """
    Run AI performance analysis on this session.
    Creates Analysis + AnalysisSuggestion rows (same schema as CI/CD analyses).
    Use `?force=true` to re-run even if an analysis already exists.
    Body (optional): `{"target_functions": ["funcA", "funcB"]}` — scopes the analysis
    to only the listed functions; implies force=True.
    """
    session = db.get(AppLogSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    if session.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Session not completed (status={session.status}). Ingest it first.",
        )
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured. Set it in .env to enable AI analysis.",
        )

    target_functions = payload.target_functions if payload else None
    # When specific functions are targeted, always create a fresh analysis
    effective_force = force or (target_functions is not None)

    from app.services.app_ai_engine import AppAIEngine
    try:
        engine = AppAIEngine(db)
        analysis = engine.analyse_session(
            session_id, force=effective_force, target_functions=target_functions
        )
        return _analysis_to_response(analysis)
    except Exception as e:
        logger.error("AI analysis failed for session %d: %s", session_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/app-logs/sessions/{session_id}/analysis",
    response_model=AnalysisResponse,
)
def get_app_session_analysis(session_id: int, db: Session = Depends(get_db)):
    """Return the most recent AI analysis for this session."""
    session = db.get(AppLogSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    analysis = (
        db.query(Analysis)
        .filter(Analysis.app_log_session_id == session_id)
        .order_by(Analysis.created_at.desc())
        .first()
    )
    if not analysis:
        raise HTTPException(
            status_code=404,
            detail=f"No analysis found for session {session_id}. Run POST /analyse first.",
        )
    return _analysis_to_response(analysis)


@router.post("/app-logs/sessions/{session_id}/feedback")
def submit_app_feedback(
    session_id: int,
    payload: AppFeedbackRequest,
    db: Session = Depends(get_db),
):
    if payload.verdict not in {"accepted", "rejected", "partial"}:
        raise HTTPException(status_code=422, detail="verdict must be accepted|rejected|partial")

    suggestion = db.get(AnalysisSuggestion, payload.suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=404, detail=f"Suggestion {payload.suggestion_id} not found")

    analysis = db.get(Analysis, suggestion.analysis_id)
    if not analysis or not analysis.app_log_session_id:
        raise HTTPException(status_code=400, detail="Suggestion is not linked to an app-log analysis")
    if analysis.app_log_session_id != session_id:
        raise HTTPException(status_code=400, detail="Suggestion does not belong to this session")

    session = db.get(AppLogSession, analysis.app_log_session_id)
    if not session:
        raise HTTPException(status_code=404, detail="App log session not found")

    feedback = AnalysisFeedback(
        analysis_id=analysis.id,
        suggestion_id=suggestion.id,
        verdict=payload.verdict,
        comment=payload.comment,
    )
    db.add(feedback)
    db.commit()

    from app.services.pattern_confidence import PatternConfidenceService

    new_rate = PatternConfidenceService(db).record_feedback(
        app_name=session.app_name,
        anti_pattern=suggestion.anti_pattern or "",
        verdict=payload.verdict,
        saving_ms=suggestion.estimated_saving_ms,
    )
    return {
        "status": "recorded",
        "app_name": session.app_name,
        "anti_pattern": suggestion.anti_pattern,
        "new_acceptance_rate": new_rate,
    }


@router.get("/app-logs/apps/{app_name}/pattern-confidence")
def get_pattern_confidence_for_app(app_name: str, db: Session = Depends(get_db)):
    from app.services.pattern_confidence import PatternConfidenceService

    rows = PatternConfidenceService(db).get_all_for_app(app_name)
    return {"app_name": app_name, "patterns": rows}
