import json

from sqlalchemy.orm import Session

from app.models.database import Analysis, AnalysisFeedback, AppLogSession

ANTI_PATTERN_SEVERITY = {
    "Busy-wait loop": 10,
    "N+1 function calls": 8,
    "Synchronous blocking I/O in hot path": 9,
    "Unbounded data accumulation": 7,
    "Repeated recomputation": 5,
    "Lock contention": 7,
    "String concatenation in loop": 3,
    "Missing connection pooling": 6,
    "Excessive serialisation/deserialisation": 5,
    "Inefficient data structure": 4,
}
DEFAULT_SEVERITY = 3


class DebtScorer:
    def __init__(self, db: Session):
        self.db = db

    def compute_score(self, analysis: Analysis) -> int:
        score = 0
        patterns = []
        if analysis.anti_patterns_json:
            try:
                patterns = json.loads(analysis.anti_patterns_json)
            except Exception:
                patterns = []

        for p in patterns:
            score += ANTI_PATTERN_SEVERITY.get(p, DEFAULT_SEVERITY)

        saving_points = min(20, ((analysis.estimated_total_saving_ms or 0) // 1000) * 2)
        score += saving_points

        rejected = (
            self.db.query(AnalysisFeedback)
            .filter(
                AnalysisFeedback.analysis_id == analysis.id,
                AnalysisFeedback.verdict == "rejected",
            )
            .count()
        )
        score += rejected * 3
        score += len(patterns) * 2
        return int(score)

    def get_trend(self, session_id: int, limit: int = 10) -> list[dict]:
        session = self.db.get(AppLogSession, session_id)
        if not session:
            return []

        rows = (
            self.db.query(
                Analysis.debt_score,
                Analysis.created_at,
                AppLogSession.id.label("session_id"),
            )
            .join(AppLogSession, Analysis.app_log_session_id == AppLogSession.id)
            .filter(
                AppLogSession.app_name == session.app_name,
                Analysis.status == "completed",
                Analysis.debt_score.isnot(None),
            )
            .order_by(Analysis.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "score": r.debt_score,
                "created_at": r.created_at.isoformat(),
                "session_id": r.session_id,
            }
            for r in reversed(rows)
        ]

    def get_label(self, score: int) -> str:
        if score <= 10:
            return "Healthy"
        if score <= 20:
            return "Moderate"
        if score <= 35:
            return "High Debt"
        return "Critical"

    def get_color(self, score: int) -> str:
        if score <= 10:
            return "green"
        if score <= 20:
            return "amber"
        if score <= 35:
            return "orange"
        return "red"
