"""
app_logs.py
-----------
API routes for the Application Log Analysis feature.

Endpoints:
  POST  /api/app-logs/upload                     upload a log file
  GET   /api/app-logs/sessions                   list all sessions
  GET   /api/app-logs/sessions/{session_id}      one session + its calls
  POST  /api/app-logs/sessions/{session_id}/analyse  trigger AI analysis
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.logging import logger
from app.db.session import get_db
from app.models.database import AppFunctionCall, AppLogSession
from app.models.schemas import (
    AppFunctionCallResponse,
    AppLogAnalyseResponse,
    AppLogSessionDetail,
    AppLogSessionResponse,
    AppLogUploadResponse,
)
from app.services.app_ingester import AppIngester

router = APIRouter()
settings = get_settings()

_ALLOWED_FORMATS = {"auto", "json", "syslog", "tshark", "logfmt", "custom"}
_MAX_BYTES = settings.APP_LOG_MAX_SIZE_MB * 1024 * 1024


# ── Upload ────────────────────────────────────────────────────────────────────

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
    Accept a multipart log file upload.

    - **file**: .log / .txt / any plain-text log file
    - **app_name**: human label, e.g. "nginx", "tshark", "my-go-service"
    - **log_format**: auto | json | syslog | tshark | logfmt | custom
    - **source_repo**: optional GitHub URL for future correlation
    - **custom_pattern**: regex with named groups (used when log_format=custom)
    """
    if log_format not in _ALLOWED_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid log_format. Choose from: {sorted(_ALLOWED_FORMATS)}",
        )

    # --- Size guard ---
    contents = await file.read()
    if len(contents) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {settings.APP_LOG_MAX_SIZE_MB} MB.",
        )

    # --- Save to disk ---
    upload_dir = os.path.abspath(settings.APP_LOG_UPLOAD_DIR)
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"{uuid.uuid4().hex}_{os.path.basename(file.filename or 'upload.log')}"
    file_path = os.path.join(upload_dir, safe_name)
    with open(file_path, "wb") as fh:
        fh.write(contents)

    # --- Create session record ---
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

    # --- Ingest synchronously (file is small enough) ---
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
        # Session already marked failed inside ingester; just report it

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


# ── List sessions ─────────────────────────────────────────────────────────────

@router.get("/app-logs/sessions", response_model=list[AppLogSessionResponse])
def list_app_sessions(db: Session = Depends(get_db)):
    """Return all app-log sessions, newest first."""
    rows = (
        db.query(AppLogSession)
        .order_by(AppLogSession.created_at.desc())
        .all()
    )
    return rows


# ── Session detail ────────────────────────────────────────────────────────────

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
            )
            for c in calls
        ],
    )


# ── AI analysis ───────────────────────────────────────────────────────────────

@router.post("/app-logs/sessions/{session_id}/analyse", response_model=AppLogAnalyseResponse)
def analyse_app_session(session_id: int, db: Session = Depends(get_db)):
    """
    Run AI analysis on the parsed function calls for this session.
    Calls the Anthropic API and stores a JSON analysis blob on the session.
    """
    session = db.get(AppLogSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    if session.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Session is not completed (status={session.status}). Ingest it first.",
        )

    # Gather top slowest calls for context
    calls = (
        db.query(AppFunctionCall)
        .filter(AppFunctionCall.session_id == session_id)
        .order_by(AppFunctionCall.duration_ms.desc())
        .limit(20)
        .all()
    )

    if not calls:
        raise HTTPException(
            status_code=400, detail="No function calls parsed — nothing to analyse."
        )

    # Build per-function aggregates for the prompt
    from collections import defaultdict

    agg: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_ms": 0, "max_ms": 0})
    for c in calls:
        a = agg[c.function_name]
        a["count"] += 1
        a["total_ms"] += c.duration_ms
        a["max_ms"] = max(a["max_ms"], c.duration_ms)

    top_funcs = sorted(agg.items(), key=lambda x: x[1]["total_ms"], reverse=True)[:10]

    prompt_lines = [
        f"You are a performance engineer analysing logs from the application '{session.app_name}'.",
        f"Log format: {session.log_format}.",
        f"Total captured duration: {session.total_duration_ms} ms across {session.total_calls} function calls.",
        "",
        "Top slowest functions (by total time):",
    ]
    for rank, (fn, stats) in enumerate(top_funcs, 1):
        avg = stats["total_ms"] // max(stats["count"], 1)
        prompt_lines.append(
            f"  {rank}. {fn}: calls={stats['count']}, "
            f"total={stats['total_ms']}ms, avg={avg}ms, max={stats['max_ms']}ms"
        )

    # Sample log excerpts for top 3 functions
    top3_names = [fn for fn, _ in top_funcs[:3]]
    for fn in top3_names:
        sample = next(
            (c.log_excerpt for c in calls if c.function_name == fn and c.log_excerpt), None
        )
        if sample:
            prompt_lines += ["", f"Log excerpt for '{fn}':", sample[:500]]

    prompt_lines += [
        "",
        "Provide a concise JSON response with the following schema:",
        '{',
        '  "root_cause": "<one sentence>",',
        '  "primary_bottleneck": "<function name>",',
        '  "anti_patterns": ["<pattern1>", ...],',
        '  "suggestions": [',
        '    {',
        '      "rank": 1,',
        '      "title": "<short title>",',
        '      "description": "<actionable fix>",',
        '      "target_function": "<fn>",',
        '      "estimated_saving_ms": <int>,',
        '      "effort": "low|medium|high"',
        '    }',
        '  ],',
        '  "estimated_total_saving_ms": <int>',
        '}',
        "Return ONLY the JSON — no prose.",
    ]

    prompt = "\n".join(prompt_lines)

    # Call LLM
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fence if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        # Validate JSON
        json.loads(raw)
        session.ai_analysis = raw
        db.commit()
        return AppLogAnalyseResponse(
            session_id=session_id,
            status="completed",
            ai_analysis=raw,
            message="AI analysis complete.",
        )
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="anthropic SDK not installed. Run: pip install anthropic",
        )
    except Exception as e:
        logger.error("AI analysis failed for session %d: %s", session_id, e)
        raise HTTPException(status_code=500, detail=f"LLM call failed: {e}")
