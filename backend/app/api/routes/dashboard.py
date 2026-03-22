"""Phase 4 API routes: dashboard, analytics, webhook, demo seed."""

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Path, Query, Request, Header, HTTPException
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import DynamicAnalyserError, to_http_exception
from app.db.repository import (
    AnalysisRepository,
    PipelineRunRepository,
    TrackedRepoRepository,
)
from app.db.session import get_db
from app.models.database import (
    Analysis,
    AnalysisSuggestion,
    PipelineRun,
    StepTiming,
    TrackedRepository,
)
from app.models.schemas import (
    DashboardSummary,
    DemoSeedResponse,
    DurationTrendPoint,
    FixImpactEntry,
    PipelineRunSummary,
    RepoAnalyticsResponse,
    StepEvolutionPoint,
)

router = APIRouter()


# ── Dashboard Summary ────────────────────────────────────────────

@router.get("/dashboard/summary", response_model=DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db)):
    """Return KPI aggregates for the top-level dashboard."""
    try:
        total_repos = db.query(func.count(TrackedRepository.id)).scalar() or 0
        total_runs = db.query(func.count(PipelineRun.id)).scalar() or 0
        total_analyses = (
            db.query(func.count(Analysis.id))
            .filter(Analysis.status == "completed")
            .scalar() or 0
        )

        avg_duration = (
            db.query(func.avg(PipelineRun.total_duration_ms))
            .filter(PipelineRun.total_duration_ms.isnot(None))
            .scalar()
        )
        avg_saving = (
            db.query(func.avg(Analysis.estimated_total_saving_ms))
            .filter(
                Analysis.status == "completed",
                Analysis.estimated_total_saving_ms.isnot(None),
            )
            .scalar()
        )

        # Recent runs (last 10)
        recent = (
            db.query(PipelineRun)
            .order_by(desc(PipelineRun.created_at))
            .limit(10)
            .all()
        )

        return DashboardSummary(
            total_repos=total_repos,
            total_runs=total_runs,
            total_analyses=total_analyses,
            avg_duration_ms=round(avg_duration or 0, 1),
            avg_saving_ms=round(avg_saving or 0, 1),
            recent_runs=[PipelineRunSummary.model_validate(r) for r in recent],
        )
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


# ── Repository Analytics ─────────────────────────────────────────

@router.get(
    "/repos/{owner}/{name}/analytics",
    response_model=RepoAnalyticsResponse,
)
def get_repo_analytics(
    owner: str,
    name: str,
    window: int = Query(30, ge=5, le=200),
    db: Session = Depends(get_db),
):
    """Return duration trends, step evolution, and fix impact data."""
    try:
        full_name = f"{owner}/{name}"
        repo_store = TrackedRepoRepository(db)
        repo = repo_store.get_by_full_name(full_name)

        # Duration trend
        runs = (
            db.query(PipelineRun)
            .filter(
                PipelineRun.repository_id == repo.id,
                PipelineRun.total_duration_ms.isnot(None),
            )
            .order_by(desc(PipelineRun.created_at))
            .limit(window)
            .all()
        )
        runs.reverse()  # oldest first

        duration_trend = []
        for r in runs:
            duration_trend.append(DurationTrendPoint(
                run_number=r.run_number,
                created_at=r.created_at,
                total_duration_ms=r.total_duration_ms,
            ))

        # Step evolution (last N runs)
        step_evolution = []
        for r in runs:
            steps = (
                db.query(StepTiming)
                .filter(StepTiming.pipeline_run_id == r.id)
                .order_by(StepTiming.step_number)
                .all()
            )
            total = r.total_duration_ms or 1
            for s in steps:
                step_evolution.append(StepEvolutionPoint(
                    run_number=r.run_number,
                    created_at=r.created_at,
                    step_name=s.step_name,
                    duration_ms=s.duration_ms,
                    pct_of_total=round(s.duration_ms / total, 4),
                ))

        # Fix impacts — compare before/after for accepted feedback
        fix_impacts = _compute_fix_impacts(db, repo.id)

        # Anti-pattern frequency
        anti_pattern_freq = _compute_anti_pattern_frequency(db, repo.id)

        return RepoAnalyticsResponse(
            repository=full_name,
            duration_trend=duration_trend,
            step_evolution=step_evolution,
            fix_impacts=fix_impacts,
            anti_pattern_frequency=anti_pattern_freq,
        )
    except DynamicAnalyserError as e:
        raise to_http_exception(e) from e


def _compute_fix_impacts(db: Session, repo_id: int) -> list[FixImpactEntry]:
    """Compute before/after impact for suggestions from completed analyses."""
    analyses = (
        db.query(Analysis)
        .filter(
            Analysis.repository_id == repo_id,
            Analysis.status == "completed",
        )
        .order_by(Analysis.created_at)
        .all()
    )

    if len(analyses) < 2:
        return []

    impacts = []
    seen_patterns: set[str] = set()
    for i in range(1, len(analyses)):
        prev = analyses[i - 1]
        curr = analyses[i]
        if prev.estimated_total_saving_ms and curr.estimated_total_saving_ms:
            for s in (prev.suggestions if hasattr(prev, 'suggestions') else []):
                if s.anti_pattern and s.anti_pattern not in seen_patterns:
                    before = prev.estimated_total_saving_ms
                    after = curr.estimated_total_saving_ms
                    improvement = before - after
                    if improvement > 0:
                        impacts.append(FixImpactEntry(
                            suggestion_title=s.title,
                            anti_pattern=s.anti_pattern,
                            before_avg_ms=float(before),
                            after_avg_ms=float(after),
                            improvement_ms=float(improvement),
                            improvement_pct=round(improvement / before * 100, 1) if before else 0,
                        ))
                        seen_patterns.add(s.anti_pattern)

    return impacts


def _compute_anti_pattern_frequency(db: Session, repo_id: int) -> dict[str, int]:
    """Count anti-pattern occurrences across all analyses."""
    analyses = (
        db.query(Analysis.anti_patterns_json)
        .filter(
            Analysis.repository_id == repo_id,
            Analysis.status == "completed",
            Analysis.anti_patterns_json.isnot(None),
        )
        .all()
    )
    freq: dict[str, int] = {}
    for (ap_json,) in analyses:
        try:
            patterns = json.loads(ap_json)
            for p in patterns:
                freq[p] = freq.get(p, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue
    return freq


# ── GitHub Webhook ───────────────────────────────────────────────

@router.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
    db: Session = Depends(get_db),
):
    """Receive GitHub Actions webhook events."""
    settings = get_settings()
    body = await request.body()

    # Verify signature if secret is configured
    if settings.GITHUB_WEBHOOK_SECRET:
        if not x_hub_signature_256:
            raise HTTPException(status_code=401, detail="Missing signature header")
        expected = "sha256=" + hmac.new(
            settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)

    if x_github_event == "ping":
        return {"status": "pong"}

    if x_github_event == "workflow_run":
        from app.services.webhook_handler import WebhookHandler
        handler = WebhookHandler(db)
        return handler.handle_workflow_run_completed(payload)

    return {"status": "ignored", "event": x_github_event}


# ── Demo Seed ────────────────────────────────────────────────────

@router.post("/demo/seed", response_model=DemoSeedResponse)
def seed_demo_data(db: Session = Depends(get_db)):
    """Seed demo data for testing and demos."""
    from app.services.demo_seeder import DemoSeeder
    seeder = DemoSeeder(db)
    result = seeder.seed()
    return DemoSeedResponse(
        repos_created=result["repos_created"],
        runs_created=result["runs_created"],
        analyses_created=result["analyses_created"],
        message="Demo data seeded successfully",
    )
