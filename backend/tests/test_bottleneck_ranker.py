import pytest
from datetime import datetime, timedelta

from app.models.database import (
    TrackedRepository,
    PipelineRun,
    StepTiming,
)
from app.services.bottleneck_ranker import BottleneckRanker


@pytest.fixture
def repo_with_runs(db_session):
    """Create a repo with 10 runs, each having 3 steps with varied durations."""
    repo = TrackedRepository(
        full_name="octocat/Hello-World", owner="octocat", name="Hello-World"
    )
    db_session.add(repo)
    db_session.flush()

    base_time = datetime(2024, 3, 1, 10, 0, 0)

    # Step durations designed for predictable statistics:
    # "Install" — increasing trend (slow, dominates)
    # "Test" — stable, moderate
    # "Deploy" — stable, fast
    install_durations = [3000, 3200, 3400, 3600, 3800, 4000, 4200, 4400, 4600, 5000]
    test_durations = [2000, 2000, 2100, 2000, 1900, 2000, 2100, 2000, 2000, 2000]
    deploy_durations = [500, 500, 500, 500, 500, 500, 500, 500, 500, 500]

    for i in range(10):
        run = PipelineRun(
            repository_id=repo.id,
            github_run_id=1000 + i,
            run_number=i + 1,
            workflow_name="CI",
            status="completed",
            conclusion="success",
            head_branch="main",
            head_sha=f"sha{i:04d}",
            total_duration_ms=(
                install_durations[i] + test_durations[i] + deploy_durations[i]
            ),
            created_at=base_time + timedelta(hours=i),
        )
        db_session.add(run)
        db_session.flush()

        for step_name, dur in [
            ("Install", install_durations[i]),
            ("Test", test_durations[i]),
            ("Deploy", deploy_durations[i]),
        ]:
            db_session.add(StepTiming(
                pipeline_run_id=run.id,
                step_name=step_name,
                step_number={"Install": 1, "Test": 2, "Deploy": 3}[step_name],
                duration_ms=dur,
                status="success",
            ))

    db_session.commit()
    return repo


class TestStepStatistics:
    def test_mean_calculation(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        stats = ranker.compute_stats(repo_with_runs.id, "Deploy", last_n=10)
        assert stats.mean_ms == 500.0
        assert stats.sample_count == 10

    def test_p50_calculation(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        stats = ranker.compute_stats(repo_with_runs.id, "Deploy", last_n=10)
        assert stats.p50_ms == 500

    def test_p95_calculation(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        stats = ranker.compute_stats(repo_with_runs.id, "Install", last_n=10)
        # Install durations: 3000..5000, sorted. p95 index = int(10*0.95)=9 → 5000
        assert stats.p95_ms == 5000

    def test_std_dev_zero_for_constant(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        stats = ranker.compute_stats(repo_with_runs.id, "Deploy", last_n=10)
        assert stats.std_dev_ms == 0.0

    def test_std_dev_nonzero_for_varying(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        stats = ranker.compute_stats(repo_with_runs.id, "Install", last_n=10)
        assert stats.std_dev_ms > 0.0

    def test_latest_ms(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        stats = ranker.compute_stats(repo_with_runs.id, "Install", last_n=10)
        assert stats.latest_ms == 5000

    def test_empty_step_returns_zeros(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        stats = ranker.compute_stats(repo_with_runs.id, "NonExistentStep", last_n=10)
        assert stats.sample_count == 0
        assert stats.mean_ms == 0.0


class TestTrendComputation:
    def test_increasing_trend_positive_slope(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        stats = ranker.compute_stats(repo_with_runs.id, "Install", last_n=10)
        # Install goes 3000→5000, should have positive slope
        assert stats.trend_slope > 0

    def test_constant_trend_zero_slope(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        stats = ranker.compute_stats(repo_with_runs.id, "Deploy", last_n=10)
        assert stats.trend_slope == 0.0

    def test_linear_regression_manual(self):
        # Verify the formula: durations = [100, 200, 300] → slope = 100
        durations = [100, 200, 300]
        slope = BottleneckRanker._compute_trend(durations)
        assert abs(slope - 100.0) < 0.01


class TestBottleneckRanking:
    def test_ranking_order(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        entries, total = ranker.rank_bottlenecks(
            repo_with_runs.id, last_n=10, top_n=3
        )
        assert len(entries) == 3
        assert entries[0]["rank"] == 1
        assert entries[1]["rank"] == 2
        assert entries[2]["rank"] == 3
        # Install should rank highest (highest pct_of_total + positive trend)
        assert entries[0]["step_name"] == "Install"

    def test_composite_score_decreasing(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        entries, _ = ranker.rank_bottlenecks(
            repo_with_runs.id, last_n=10, top_n=3
        )
        scores = [e["composite_score"] for e in entries]
        assert scores == sorted(scores, reverse=True)

    def test_pct_of_total_sums_near_one(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        entries, _ = ranker.rank_bottlenecks(
            repo_with_runs.id, last_n=10, top_n=3
        )
        total_pct = sum(e["pct_of_total"] for e in entries)
        assert abs(total_pct - 1.0) < 0.01

    def test_trend_direction_labels(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        entries, _ = ranker.rank_bottlenecks(
            repo_with_runs.id, last_n=10, top_n=3
        )
        install = next(e for e in entries if e["step_name"] == "Install")
        deploy = next(e for e in entries if e["step_name"] == "Deploy")
        assert install["trend_direction"] == "increasing"
        assert deploy["trend_direction"] == "stable"

    def test_empty_repo(self, db_session):
        repo = TrackedRepository(
            full_name="empty/repo", owner="empty", name="repo"
        )
        db_session.add(repo)
        db_session.commit()

        ranker = BottleneckRanker(db_session)
        entries, total = ranker.rank_bottlenecks(repo.id, last_n=10, top_n=3)
        assert entries == []
        assert total == 0

    def test_top_n_limits_results(self, db_session, repo_with_runs):
        ranker = BottleneckRanker(db_session)
        entries, _ = ranker.rank_bottlenecks(
            repo_with_runs.id, last_n=10, top_n=2
        )
        assert len(entries) == 2
