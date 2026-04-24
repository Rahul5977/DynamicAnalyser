from __future__ import annotations

import json
import math
from collections import Counter

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.database import Analysis, AppLogSession, PipelineRun, TrackedRepository
from fastapi import Depends

router = APIRouter()


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac)


def _most_common_anti_pattern(db: Session) -> str | None:
    rows = (
        db.query(Analysis.anti_patterns_json)
        .filter(
            Analysis.app_log_session_id.isnot(None),
            Analysis.anti_patterns_json.isnot(None),
            Analysis.status == "completed",
        )
        .all()
    )
    counter: Counter[str] = Counter()
    for (raw,) in rows:
        try:
            items = json.loads(raw)
            if isinstance(items, list):
                counter.update([x for x in items if isinstance(x, str) and x.strip()])
        except (json.JSONDecodeError, TypeError):
            continue
    return counter.most_common(1)[0][0] if counter else None


@router.get("/benchmarks/app-sessions")
def app_sessions_benchmark(app_name: str = Query(...), db: Session = Depends(get_db)):
    requested_name = app_name.strip()
    requested_norm = requested_name.casefold()
    grouped = (
        db.query(
            AppLogSession.app_name.label("app_name"),
            func.avg(AppLogSession.total_duration_ms).label("avg_ms"),
            func.count(AppLogSession.id).label("session_count"),
            func.avg(AppLogSession.total_calls).label("avg_calls"),
        )
        .filter(
            AppLogSession.status == "completed",
            AppLogSession.total_duration_ms.isnot(None),
            AppLogSession.total_duration_ms > 0,
        )
        .group_by(AppLogSession.app_name)
        .order_by(func.avg(AppLogSession.total_duration_ms).asc())
        .all()
    )

    if not grouped:
        raise HTTPException(status_code=404, detail="No completed app sessions found")

    app_rows = [
        {
            "app_name": r.app_name,
            "avg_ms": float(r.avg_ms or 0),
            "session_count": int(r.session_count or 0),
            "avg_calls": float(r.avg_calls or 0),
        }
        for r in grouped
    ]
    target = next(
        (r for r in app_rows if (r["app_name"] or "").strip().casefold() == requested_norm),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail=f"No benchmark data found for app '{app_name}'")

    values = sorted([r["avg_ms"] for r in app_rows])
    total_apps = len(values)
    rank = 1 + sum(1 for r in app_rows if r["avg_ms"] < target["avg_ms"])

    if total_apps < 2:
        speed_percentile = None
    else:
        less_or_equal = sum(1 for r in app_rows if r["avg_ms"] <= target["avg_ms"])
        speed_percentile = int(round((less_or_equal / total_apps) * 100))

    return {
        "app_name": target["app_name"],
        "avg_duration_ms": target["avg_ms"],
        "session_count": target["session_count"],
        "total_apps_in_fleet": total_apps,
        "speed_percentile": speed_percentile,
        "fleet_p50_ms": _percentile(values, 0.5),
        "fleet_p95_ms": _percentile(values, 0.95),
        "fleet_most_common_anti_pattern": _most_common_anti_pattern(db),
        "your_rank": rank,
    }


@router.get("/benchmarks/pipeline-repos")
def pipeline_repos_benchmark(
    owner: str = Query(...),
    name: str = Query(...),
    db: Session = Depends(get_db),
):
    full_name = f"{owner}/{name}"
    grouped = (
        db.query(
            PipelineRun.repository_id.label("repository_id"),
            func.avg(PipelineRun.total_duration_ms).label("avg_ms"),
            func.count(PipelineRun.id).label("session_count"),
        )
        .filter(
            PipelineRun.status == "completed",
            PipelineRun.total_duration_ms.isnot(None),
            PipelineRun.total_duration_ms > 0,
        )
        .group_by(PipelineRun.repository_id)
        .order_by(func.avg(PipelineRun.total_duration_ms).asc())
        .all()
    )
    if not grouped:
        raise HTTPException(status_code=404, detail="No completed pipeline runs found")

    repos = {r.id: r.full_name for r in db.query(TrackedRepository).all()}
    repo_rows = [
        {
            "repository_id": r.repository_id,
            "full_name": repos.get(r.repository_id),
            "avg_ms": float(r.avg_ms or 0),
            "session_count": int(r.session_count or 0),
        }
        for r in grouped
    ]
    target = next((r for r in repo_rows if r["full_name"] == full_name), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"No benchmark data found for repo '{full_name}'")

    values = sorted([r["avg_ms"] for r in repo_rows])
    total_repos = len(values)
    rank = 1 + sum(1 for r in repo_rows if r["avg_ms"] < target["avg_ms"])
    if total_repos < 2:
        speed_percentile = None
    else:
        less_or_equal = sum(1 for r in repo_rows if r["avg_ms"] <= target["avg_ms"])
        speed_percentile = int(round((less_or_equal / total_repos) * 100))

    return {
        "app_name": full_name,
        "avg_duration_ms": target["avg_ms"],
        "session_count": target["session_count"],
        "total_apps_in_fleet": total_repos,
        "speed_percentile": speed_percentile,
        "fleet_p50_ms": _percentile(values, 0.5),
        "fleet_p95_ms": _percentile(values, 0.95),
        "fleet_most_common_anti_pattern": _most_common_anti_pattern(db),
        "your_rank": rank,
    }


@router.get("/benchmarks/fleet-summary")
def fleet_summary(db: Session = Depends(get_db)):
    total_app_sessions = (
        db.query(func.count(AppLogSession.id))
        .filter(AppLogSession.status == "completed")
        .scalar()
        or 0
    )
    total_pipeline_runs = (
        db.query(func.count(PipelineRun.id))
        .filter(PipelineRun.status == "completed")
        .scalar()
        or 0
    )
    total_repos = db.query(func.count(TrackedRepository.id)).scalar() or 0

    app_grouped = (
        db.query(
            AppLogSession.app_name.label("app_name"),
            func.avg(AppLogSession.total_duration_ms).label("avg_ms"),
        )
        .filter(
            AppLogSession.status == "completed",
            AppLogSession.total_duration_ms.isnot(None),
            AppLogSession.total_duration_ms > 0,
        )
        .group_by(AppLogSession.app_name)
        .all()
    )
    app_rows = [{"app_name": r.app_name, "avg_ms": float(r.avg_ms or 0)} for r in app_grouped]
    values = sorted([r["avg_ms"] for r in app_rows])

    top3 = sorted(app_rows, key=lambda x: x["avg_ms"])[:3]
    top_3_apps = []
    for row in top3:
        if len(values) < 2:
            pct = None
        else:
            le = sum(1 for v in values if v <= row["avg_ms"])
            pct = int(round((le / len(values)) * 100))
        top_3_apps.append({"app_name": row["app_name"], "avg_ms": row["avg_ms"], "percentile": pct})

    fleet_avg = float(sum(values) / len(values)) if values else 0.0
    return {
        "total_app_sessions": int(total_app_sessions),
        "total_pipeline_runs": int(total_pipeline_runs),
        "total_repos": int(total_repos),
        "fleet_avg_duration_ms": fleet_avg,
        "most_common_anti_pattern": _most_common_anti_pattern(db),
        "top_3_apps_by_speed": top_3_apps,
    }
