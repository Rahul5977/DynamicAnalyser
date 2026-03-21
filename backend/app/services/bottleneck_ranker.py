"""Statistical bottleneck ranker for pipeline steps."""

import statistics
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.exceptions import DatabaseError, RepositoryNotFoundError
from app.core.logging import logger
from app.db.repository import PipelineRunRepository, TrackedRepoRepository


@dataclass
class StepStatistics:
    step_name: str
    sample_count: int
    durations: list[int]
    mean_ms: float
    p50_ms: int
    p95_ms: int
    std_dev_ms: float
    trend_slope: float
    latest_ms: int
    pct_of_total: float = 0.0


class BottleneckRanker:
    """Computes statistical bottleneck ranking across pipeline runs."""

    W_PCT_OF_TOTAL = 0.5
    W_ANOMALY = 0.3
    W_TREND = 0.2

    def __init__(self, db: Session):
        self.db = db

    def compute_stats(
        self, repo_id: int, step_name: str, last_n: int = 50
    ) -> StepStatistics:
        """Compute full statistics for a single step across last N runs."""
        run_store = PipelineRunRepository(self.db)
        rows = run_store.get_step_durations_for_repo(repo_id, step_name, last_n)

        if not rows:
            return StepStatistics(
                step_name=step_name,
                sample_count=0,
                durations=[],
                mean_ms=0.0,
                p50_ms=0,
                p95_ms=0,
                std_dev_ms=0.0,
                trend_slope=0.0,
                latest_ms=0,
            )

        durations = [r[1] for r in rows]  # already ordered oldest→newest
        n = len(durations)
        sorted_d = sorted(durations)

        mean = statistics.mean(durations)
        p50 = sorted_d[n // 2] if n > 0 else 0
        p95_idx = min(int(n * 0.95), n - 1)
        p95 = sorted_d[p95_idx]
        std_dev = statistics.pstdev(durations) if n > 1 else 0.0
        trend = self._compute_trend(durations)
        latest = durations[-1] if durations else 0

        return StepStatistics(
            step_name=step_name,
            sample_count=n,
            durations=durations,
            mean_ms=mean,
            p50_ms=p50,
            p95_ms=p95,
            std_dev_ms=std_dev,
            trend_slope=trend,
            latest_ms=latest,
        )

    def rank_bottlenecks(
        self, repo_id: int, last_n: int = 50, top_n: int = 3
    ) -> tuple[list[dict], int]:
        """Rank steps by composite bottleneck score.

        Returns (bottleneck_entries, total_runs_analyzed).
        """
        run_store = PipelineRunRepository(self.db)
        step_names = run_store.get_all_step_names_for_repo(repo_id, last_n)

        if not step_names:
            return [], 0

        # Compute stats for all steps
        all_stats: list[StepStatistics] = []
        for name in step_names:
            stats = self.compute_stats(repo_id, name, last_n)
            if stats.sample_count > 0:
                all_stats.append(stats)

        if not all_stats:
            return [], 0

        # Compute pct_of_total
        total_mean = sum(s.mean_ms for s in all_stats)
        if total_mean > 0:
            for s in all_stats:
                s.pct_of_total = s.mean_ms / total_mean

        # Compute composite scores and build entries
        entries = []
        max_samples = max(s.sample_count for s in all_stats)
        for stats in all_stats:
            anomaly = self._compute_anomaly_score(stats)
            score = self._compute_composite_score(stats, anomaly)

            trend_dir = "stable"
            if stats.trend_slope > 10:
                trend_dir = "increasing"
            elif stats.trend_slope < -10:
                trend_dir = "decreasing"

            entries.append({
                "step_name": stats.step_name,
                "composite_score": round(score, 4),
                "pct_of_total": round(stats.pct_of_total, 4),
                "anomaly_score": round(anomaly, 4) if anomaly is not None else None,
                "trend_direction": trend_dir,
                "mean_ms": round(stats.mean_ms, 1),
                "p50_ms": stats.p50_ms,
                "p95_ms": stats.p95_ms,
            })

        # Sort by composite score descending and assign ranks
        entries.sort(key=lambda e: e["composite_score"], reverse=True)
        for i, entry in enumerate(entries[:top_n], 1):
            entry["rank"] = i

        return entries[:top_n], max_samples

    @staticmethod
    def _compute_trend(durations: list[int]) -> float:
        """Linear regression slope of duration over run index."""
        n = len(durations)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(durations)
        numerator = sum(
            (i - x_mean) * (d - y_mean) for i, d in enumerate(durations)
        )
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        return numerator / denominator if denominator else 0.0

    @staticmethod
    def _compute_anomaly_score(stats: StepStatistics) -> float | None:
        """Compute how many standard deviations the latest run is above average."""
        if stats.std_dev_ms == 0 or stats.sample_count < 2:
            return 0.0
        raw = (stats.latest_ms - stats.mean_ms) / stats.std_dev_ms
        return max(0.0, min(raw, 5.0))  # Clamp to [0, 5]

    def _compute_composite_score(
        self, stats: StepStatistics, anomaly: float | None
    ) -> float:
        """Composite score: 0.5*pct_of_total + 0.3*anomaly + 0.2*(trend>0)."""
        pct = stats.pct_of_total
        anom = (anomaly or 0.0) / 5.0  # Normalize to [0, 1]
        trend_flag = 1.0 if stats.trend_slope > 0 else 0.0

        return (
            self.W_PCT_OF_TOTAL * pct
            + self.W_ANOMALY * anom
            + self.W_TREND * trend_flag
        )
