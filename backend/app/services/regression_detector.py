from sqlalchemy.orm import Session

from app.models.database import AppFunctionCall, AppLogSession, RegressionAlert

REGRESSION_WARNING = 1.5
REGRESSION_CRITICAL = 2.5
MIN_BASELINE_SESSIONS = 3


class RegressionDetector:
    def __init__(self, db: Session):
        self.db = db

    def compute_baseline(
        self, app_name: str, function_name: str, exclude_session_id: int
    ) -> float | None:
        rows = (
            self.db.query(AppFunctionCall.duration_ms)
            .join(AppLogSession, AppFunctionCall.session_id == AppLogSession.id)
            .filter(
                AppLogSession.app_name == app_name,
                AppLogSession.status == "completed",
                AppLogSession.id != exclude_session_id,
                AppFunctionCall.function_name == function_name,
            )
            .all()
        )
        durations = sorted([r.duration_ms for r in rows])
        if len(durations) < MIN_BASELINE_SESSIONS:
            return None
        return float(durations[len(durations) // 2])

    def detect_regressions(self, session_id: int) -> list[RegressionAlert]:
        session = self.db.get(AppLogSession, session_id)
        if not session:
            return []

        calls = (
            self.db.query(AppFunctionCall)
            .filter(AppFunctionCall.session_id == session_id)
            .all()
        )

        alerts: list[RegressionAlert] = []
        for call in calls:
            baseline = self.compute_baseline(session.app_name, call.function_name, session_id)
            if baseline is None or baseline <= 0:
                continue

            ratio = call.duration_ms / baseline
            if ratio >= REGRESSION_WARNING:
                severity = "critical" if ratio >= REGRESSION_CRITICAL else "warning"
                existing = (
                    self.db.query(RegressionAlert)
                    .filter_by(session_id=session_id, function_name=call.function_name)
                    .first()
                )
                if existing:
                    continue
                alert = RegressionAlert(
                    app_name=session.app_name,
                    session_id=session_id,
                    function_name=call.function_name,
                    baseline_ms=round(baseline, 1),
                    current_ms=float(call.duration_ms),
                    ratio=round(ratio, 2),
                    severity=severity,
                )
                self.db.add(alert)
                alerts.append(alert)

        self.db.commit()
        return alerts

    def get_active_alerts(self, app_name: str | None = None) -> list[dict]:
        q = self.db.query(RegressionAlert).filter(RegressionAlert.resolved.is_(False))
        if app_name:
            q = q.filter(RegressionAlert.app_name == app_name)
        rows = q.order_by(RegressionAlert.ratio.desc()).all()
        return [
            {
                "id": r.id,
                "app_name": r.app_name,
                "session_id": r.session_id,
                "function_name": r.function_name,
                "baseline_ms": r.baseline_ms,
                "current_ms": r.current_ms,
                "ratio": r.ratio,
                "severity": r.severity,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
