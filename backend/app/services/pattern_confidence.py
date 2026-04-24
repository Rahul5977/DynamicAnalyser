import datetime

from sqlalchemy.orm import Session

from app.models.database import PatternConfidence


class PatternConfidenceService:
    def __init__(self, db: Session):
        self.db = db

    def record_feedback(
        self, app_name: str, anti_pattern: str, verdict: str, saving_ms: int = 0
    ) -> float:
        pattern_name = (anti_pattern or "").strip() or "unknown"
        row = (
            self.db.query(PatternConfidence)
            .filter_by(app_name=app_name, anti_pattern=pattern_name)
            .first()
        )
        if not row:
            row = PatternConfidence(app_name=app_name, anti_pattern=pattern_name)
            self.db.add(row)

        if verdict == "accepted":
            row.accepted_count += 1
        elif verdict == "rejected":
            row.rejected_count += 1
        elif verdict == "partial":
            row.partial_count += 1

        row.total_estimated_saving_ms += saving_ms or 0
        total = row.accepted_count + row.rejected_count + row.partial_count
        row.acceptance_rate = (row.accepted_count + 0.5 * row.partial_count) / max(total, 1)
        row.updated_at = datetime.datetime.utcnow()
        self.db.commit()
        return row.acceptance_rate

    def get_confidence_context(self, app_name: str) -> str:
        rows = (
            self.db.query(PatternConfidence)
            .filter(
                PatternConfidence.app_name == app_name,
                (PatternConfidence.accepted_count + PatternConfidence.rejected_count) > 0,
            )
            .order_by(PatternConfidence.acceptance_rate.desc())
            .all()
        )
        if not rows:
            return ""

        lines = [
            "## Learned Pattern Confidence for this Application",
            "Use this data to calibrate which anti-patterns are",
            "most relevant and which fixes have worked before:",
        ]
        for r in rows:
            total = r.accepted_count + r.rejected_count + r.partial_count
            pct = round(r.acceptance_rate * 100)
            lines.append(
                f"- {r.anti_pattern}: {pct}% acceptance rate "
                f"({r.accepted_count} accepted, {r.rejected_count} "
                f"rejected from {total} total feedbacks)"
            )
            if r.acceptance_rate >= 0.7:
                lines.append("  → HIGH CONFIDENCE: Prioritise this pattern")
            elif r.acceptance_rate <= 0.3:
                lines.append("  → LOW CONFIDENCE: Deprioritise or skip")
        return "\n".join(lines)

    def get_all_for_app(self, app_name: str) -> list[dict]:
        rows = (
            self.db.query(PatternConfidence)
            .filter(PatternConfidence.app_name == app_name)
            .order_by(PatternConfidence.acceptance_rate.desc(), PatternConfidence.updated_at.desc())
            .all()
        )
        return [
            {
                "app_name": r.app_name,
                "anti_pattern": r.anti_pattern,
                "accepted_count": r.accepted_count,
                "rejected_count": r.rejected_count,
                "partial_count": r.partial_count,
                "total_estimated_saving_ms": r.total_estimated_saving_ms,
                "acceptance_rate": r.acceptance_rate,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
