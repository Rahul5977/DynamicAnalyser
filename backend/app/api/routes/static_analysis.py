from __future__ import annotations

import asyncio
import json
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.models.database import StaticAnalysisJob
from app.services.static_analyser.ast_triage import run_ast_triage
from app.services.static_analyser.graph_store import InProcessGraphStore
from app.services.static_analyser.ingestor import cleanup_repository, ingest_repository
from app.services.static_analyser.vector_store import InProcessVectorStore
from app.services.static_analyser.council.council_orchestrator import CouncilOrchestrator

router = APIRouter()


class StaticAnalyseRequest(BaseModel):
    repo_url: str


def _run_static_pipeline(job_id: str, repo_url: str) -> None:
    db = SessionLocal()
    local_path = ""
    try:
        job = db.query(StaticAnalysisJob).filter(StaticAnalysisJob.job_id == job_id).first()
        if not job:
            return
        job.status = "running"
        db.commit()

        manifest = ingest_repository(repo_url)
        local_path = manifest["local_path"]
        triage = run_ast_triage(local_path=manifest["local_path"], target_files=manifest["target_files"])
        vector_store = InProcessVectorStore()
        vector_store.index(triage.chunks, job_id=job_id)
        graph_store = InProcessGraphStore()
        graph = graph_store.build_graph(triage.adjacency_list)
        coupling = graph_store.compute_coupling_scores()
        chunk_counts: dict[str, int] = {}
        for c in triage.chunks:
            chunk_counts[c.file_path] = chunk_counts.get(c.file_path, 0) + 1
        architecture = {
            "cycles": graph_store.find_cycles(),
            "coupling_scores": coupling,
            "god_classes": graph_store.find_god_classes(chunk_counts=chunk_counts),
            "nodes": len(graph),
            "edges": sum(len(v) for v in graph.values()),
        }

        orchestrator = CouncilOrchestrator()
        report = asyncio.run(
            orchestrator.run(
                repo_id=repo_url,
                job_id=job_id,
                manifest=manifest,
                triage_result=triage,
                architecture_report=architecture,
            )
        )

        job.status = "completed"
        job.primary_language = manifest.get("primary_language")
        job.health_score = report.health_score
        job.finding_count = len(report.finding_cards)
        job.report_json = json.dumps(report.to_dict())
        job.completed_at = datetime.utcnow()
        job.error_message = None
        db.commit()
    except Exception as e:  # pragma: no cover
        row = db.query(StaticAnalysisJob).filter(StaticAnalysisJob.job_id == job_id).first()
        if row:
            row.status = "failed"
            row.error_message = str(e)
            row.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
        if local_path:
            cleanup_repository(local_path)


@router.post("/static/analyse")
def analyse_static(payload: StaticAnalyseRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    jid = str(uuid4())
    job = StaticAnalysisJob(job_id=jid, repo_url=payload.repo_url, status="pending")
    db.add(job)
    db.commit()
    background_tasks.add_task(_run_static_pipeline, jid, payload.repo_url)
    return {"job_id": jid, "status": "running"}


@router.get("/static/jobs/{job_id}")
def get_static_job(job_id: str, db: Session = Depends(get_db)):
    row = db.query(StaticAnalysisJob).filter(StaticAnalysisJob.job_id == job_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": row.job_id,
        "repo_url": row.repo_url,
        "status": row.status,
        "created_at": row.created_at,
        "completed_at": row.completed_at,
        "error_message": row.error_message,
        "health_score": row.health_score,
        "finding_count": row.finding_count,
        "primary_language": row.primary_language,
    }


@router.get("/static/report/{job_id}")
def get_static_report(job_id: str, db: Session = Depends(get_db)):
    row = db.query(StaticAnalysisJob).filter(StaticAnalysisJob.job_id == job_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if not row.report_json:
        raise HTTPException(status_code=404, detail="Report not available yet")
    return json.loads(row.report_json)


@router.get("/static/jobs")
def list_static_jobs(db: Session = Depends(get_db)):
    rows = (
        db.query(StaticAnalysisJob)
        .order_by(StaticAnalysisJob.created_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "job_id": r.job_id,
            "repo_url": r.repo_url,
            "status": r.status,
            "created_at": r.created_at,
            "completed_at": r.completed_at,
            "health_score": r.health_score,
            "finding_count": r.finding_count,
            "primary_language": r.primary_language,
        }
        for r in rows
    ]
