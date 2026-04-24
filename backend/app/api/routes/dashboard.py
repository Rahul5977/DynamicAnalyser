"""Dashboard summary and GitHub webhook routes."""

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import DynamicAnalyserError, to_http_exception
from app.db.session import get_db
from app.models.database import Analysis, PipelineRun, TrackedRepository
from app.models.schemas import DashboardSummary, PipelineRunSummary

router = APIRouter()


@router.get("/dashboard/summary", response_model=DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db)):
    """Return KPI aggregates for the top-level dashboard."""
    try:
        total_repos = db.query(func.count(TrackedRepository.id)).scalar() or 0
        total_runs = db.query(func.count(PipelineRun.id)).scalar() or 0
        total_analyses = (
            db.query(func.count(Analysis.id))
            .filter(Analysis.status == "completed")
            .scalar()
            or 0
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
