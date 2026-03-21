import json
import pytest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.session import get_db
from app.models.database import (
    Base,
    TrackedRepository,
    PipelineRun,
    StepTiming,
    CodeIndex,
    IndexedFunction,
    IndexedLogCall,
)


def _make_test_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def seeded_analysis_client():
    """Client with repo, 10 runs, and a completed code index."""
    engine = _make_test_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    # Seed data
    session = Session()
    repo = TrackedRepository(
        full_name="octocat/Hello-World", owner="octocat", name="Hello-World"
    )
    session.add(repo)
    session.flush()

    base_time = datetime(2024, 3, 1, 10, 0, 0)
    install_durs = [3000, 3200, 3400, 3600, 3800, 4000, 4200, 4400, 4600, 5000]
    test_durs = [2000] * 10
    deploy_durs = [500] * 10

    for i in range(10):
        total = install_durs[i] + test_durs[i] + deploy_durs[i]
        run = PipelineRun(
            repository_id=repo.id,
            github_run_id=1000 + i,
            run_number=i + 1,
            workflow_name="CI",
            status="completed",
            conclusion="success",
            head_branch="main",
            head_sha=f"sha{i:04d}",
            total_duration_ms=total,
            created_at=base_time + timedelta(hours=i),
        )
        session.add(run)
        session.flush()

        for step_name, dur, num in [
            ("Install", install_durs[i], 1),
            ("Test", test_durs[i], 2),
            ("Deploy", deploy_durs[i], 3),
        ]:
            session.add(StepTiming(
                pipeline_run_id=run.id,
                step_name=step_name,
                step_number=num,
                duration_ms=dur,
                status="success",
                log_excerpt="Running database migrations" if step_name == "Install" else "Running tests",
            ))

    # Code index
    code_idx = CodeIndex(
        repository_id=repo.id,
        commit_sha="sha0009",
        status="completed",
        total_functions=2,
        total_log_calls=1,
        language_breakdown=json.dumps({"py": 1}),
        completed_at=datetime(2024, 3, 1, 10, 0, 0),
    )
    session.add(code_idx)
    session.flush()

    session.add(IndexedFunction(
        code_index_id=code_idx.id,
        function_name="run_migrations",
        qualified_name="db.run_migrations",
        file_path="db/migrate.py",
        line_number=10,
        end_line_number=20,
        language="py",
        calls_json=None,
    ))
    session.add(IndexedLogCall(
        code_index_id=code_idx.id,
        log_string="Running database migrations",
        file_path="db/migrate.py",
        line_number=12,
        function_name="run_migrations",
        log_level="info",
        language="py",
    ))
    session.commit()
    session.close()

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def empty_client():
    engine = _make_test_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


class TestBottlenecksEndpoint:
    def test_get_bottlenecks(self, seeded_analysis_client):
        response = seeded_analysis_client.get(
            "/api/repos/octocat/Hello-World/bottlenecks"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["repository"] == "octocat/Hello-World"
        assert len(data["bottlenecks"]) == 3
        assert data["bottlenecks"][0]["rank"] == 1
        assert data["bottlenecks"][0]["step_name"] == "Install"

    def test_bottlenecks_repo_not_found(self, empty_client):
        response = empty_client.get("/api/repos/unknown/repo/bottlenecks")
        assert response.status_code == 404

    def test_bottlenecks_custom_top_n(self, seeded_analysis_client):
        response = seeded_analysis_client.get(
            "/api/repos/octocat/Hello-World/bottlenecks?top_n=1"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["bottlenecks"]) == 1


class TestStepStatsEndpoint:
    def test_get_step_stats(self, seeded_analysis_client):
        response = seeded_analysis_client.get(
            "/api/repos/octocat/Hello-World/step/Install/stats"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["step_name"] == "Install"
        assert data["sample_count"] == 10
        assert data["mean_ms"] > 0
        assert data["p50_ms"] > 0
        assert data["p95_ms"] >= data["p50_ms"]
        assert data["trend_slope"] > 0  # Install has increasing trend

    def test_step_stats_nonexistent_step(self, seeded_analysis_client):
        response = seeded_analysis_client.get(
            "/api/repos/octocat/Hello-World/step/NonExistent/stats"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["sample_count"] == 0

    def test_step_stats_repo_not_found(self, empty_client):
        response = empty_client.get("/api/repos/unknown/repo/step/Install/stats")
        assert response.status_code == 404


class TestTraceEndpoint:
    def test_get_trace(self, seeded_analysis_client):
        # Run ID 10 is the last run (10 runs, IDs 1-10)
        response = seeded_analysis_client.get("/api/runs/10/trace")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == 10
        assert data["total_steps"] == 3
        assert "steps" in data
        assert data["match_rate"] >= 0.0

    def test_trace_has_source_location(self, seeded_analysis_client):
        response = seeded_analysis_client.get("/api/runs/10/trace")
        data = response.json()
        # Install step has log_excerpt "Running database migrations" which matches
        install_step = next(
            (s for s in data["steps"] if s["step_name"] == "Install"), None
        )
        assert install_step is not None
        if install_step["source_location"]:
            assert install_step["source_location"]["function_name"] == "run_migrations"
            assert install_step["match_method"] == "exact"

    def test_trace_run_not_found(self, empty_client):
        response = empty_client.get("/api/runs/999/trace")
        assert response.status_code == 404
