"""Tests for Phase 3 API endpoints: analysis, insights, feedback."""

import json
import pytest
from datetime import datetime

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
    Analysis,
    AnalysisSuggestion,
    AnalysisFeedback,
)


def _make_test_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def seeded_ai_client():
    """Client with repo, runs, code index, and a completed analysis."""
    engine = _make_test_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    session = Session()

    # Seed repo
    repo = TrackedRepository(
        full_name="octocat/Hello-World", owner="octocat", name="Hello-World"
    )
    session.add(repo)
    session.flush()

    # Seed runs
    for i in range(5):
        run = PipelineRun(
            repository_id=repo.id,
            github_run_id=5000 + i,
            run_number=i + 1,
            workflow_name="CI",
            status="completed",
            conclusion="success",
            head_branch="main",
            head_sha=f"sha{i:04d}",
            total_duration_ms=10000 + i * 500,
            created_at=datetime(2024, 3, 1, 10 + i, 0, 0),
        )
        session.add(run)
        session.flush()

        for step_name, dur in [("Install", 5000 + i * 200), ("Test", 3000), ("Deploy", 2000)]:
            session.add(StepTiming(
                pipeline_run_id=run.id,
                step_name=step_name,
                step_number={"Install": 1, "Test": 2, "Deploy": 3}[step_name],
                duration_ms=dur,
                status="success",
                log_excerpt="Running step",
            ))

    # Code index
    code_idx = CodeIndex(
        repository_id=repo.id,
        commit_sha="sha0004",
        status="completed",
        total_functions=1,
        total_log_calls=0,
        completed_at=datetime(2024, 3, 1, 15, 0, 0),
    )
    session.add(code_idx)
    session.flush()

    session.add(IndexedFunction(
        code_index_id=code_idx.id,
        function_name="install_deps",
        qualified_name="build.install_deps",
        file_path="build/setup.py",
        line_number=5,
        end_line_number=20,
        language="py",
    ))

    # Pre-seed a completed analysis (run_id=5, the last run)
    analysis = Analysis(
        pipeline_run_id=5,  # last run
        repository_id=repo.id,
        status="completed",
        root_cause="Install step has no dependency caching",
        primary_bottleneck="install_deps",
        anti_patterns_json=json.dumps(["No dependency caching"]),
        estimated_total_saving_ms=5000,
        llm_model="claude-sonnet-4-20250514",
        completed_at=datetime(2024, 3, 1, 16, 0, 0),
    )
    session.add(analysis)
    session.flush()

    session.add(AnalysisSuggestion(
        analysis_id=analysis.id,
        rank=1,
        title="Add pip cache",
        description="Cache pip packages to avoid re-downloading",
        target_function="install_deps",
        target_file="build/setup.py",
        estimated_saving_ms=3000,
        effort="low",
        diff_hint="Before: pip install\nAfter: pip install --cache",
        confidence_score=0.8,
        anti_pattern="No dependency caching",
    ))
    session.add(AnalysisSuggestion(
        analysis_id=analysis.id,
        rank=2,
        title="Parallelize tests",
        description="Run tests concurrently",
        target_function="",
        target_file="",
        estimated_saving_ms=2000,
        effort="medium",
        confidence_score=0.6,
        anti_pattern="Sequential test execution",
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
def empty_ai_client():
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


# ── GET /api/analyses/{id} Tests ─────────────────────────────────

class TestGetAnalysis:
    def test_get_analysis_success(self, seeded_ai_client):
        response = seeded_ai_client.get("/api/analyses/1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["status"] == "completed"
        assert data["root_cause"] == "Install step has no dependency caching"
        assert data["primary_bottleneck"] == "install_deps"
        assert len(data["suggestions"]) == 2
        assert data["suggestions"][0]["rank"] == 1
        assert data["suggestions"][0]["title"] == "Add pip cache"
        assert data["estimated_total_saving_ms"] == 5000
        assert "No dependency caching" in data["anti_patterns"]

    def test_get_analysis_not_found(self, empty_ai_client):
        response = empty_ai_client.get("/api/analyses/999")
        assert response.status_code == 404


# ── GET /api/runs/{id}/analysis/latest Tests ─────────────────────

class TestGetLatestAnalysis:
    def test_get_latest_analysis(self, seeded_ai_client):
        response = seeded_ai_client.get("/api/runs/5/analysis/latest")
        assert response.status_code == 200
        data = response.json()
        assert data["pipeline_run_id"] == 5
        assert data["status"] == "completed"
        assert len(data["suggestions"]) == 2

    def test_no_analysis_for_run(self, seeded_ai_client):
        # Run 1 has no analysis
        response = seeded_ai_client.get("/api/runs/1/analysis/latest")
        assert response.status_code == 404


# ── GET /api/repos/{owner}/{name}/insights Tests ─────────────────

class TestRepoInsights:
    def test_get_insights(self, seeded_ai_client):
        response = seeded_ai_client.get("/api/repos/octocat/Hello-World/insights")
        assert response.status_code == 200
        data = response.json()
        assert data["repository"] == "octocat/Hello-World"
        assert data["total_analyses"] >= 1
        assert data["most_common_bottleneck"] == "install_deps"
        assert data["avg_total_saving_ms"] > 0

        # Check anti-patterns
        patterns = data["anti_patterns"]
        assert len(patterns) >= 1
        assert any(p["anti_pattern"] == "No dependency caching" for p in patterns)

    def test_insights_repo_not_found(self, empty_ai_client):
        response = empty_ai_client.get("/api/repos/unknown/repo/insights")
        assert response.status_code == 404


# ── POST /api/analyses/{id}/feedback Tests ───────────────────────

class TestFeedback:
    def test_submit_feedback_accepted(self, seeded_ai_client):
        response = seeded_ai_client.post(
            "/api/analyses/1/feedback",
            json={
                "suggestion_id": 1,
                "verdict": "accepted",
                "comment": "Good suggestion, will implement!",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["analysis_id"] == 1
        assert data["suggestion_id"] == 1
        assert data["verdict"] == "accepted"
        assert data["comment"] == "Good suggestion, will implement!"

    def test_submit_feedback_rejected(self, seeded_ai_client):
        response = seeded_ai_client.post(
            "/api/analyses/1/feedback",
            json={
                "verdict": "rejected",
                "comment": "Not applicable to our setup",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["verdict"] == "rejected"

    def test_submit_feedback_invalid_verdict(self, seeded_ai_client):
        response = seeded_ai_client.post(
            "/api/analyses/1/feedback",
            json={"verdict": "maybe"},
        )
        assert response.status_code == 422

    def test_submit_feedback_analysis_not_found(self, empty_ai_client):
        response = empty_ai_client.post(
            "/api/analyses/999/feedback",
            json={"verdict": "accepted"},
        )
        assert response.status_code == 404


# ── Suggestion Schema Validation ─────────────────────────────────

class TestSuggestionResponseSchema:
    def test_suggestions_have_required_fields(self, seeded_ai_client):
        response = seeded_ai_client.get("/api/analyses/1")
        data = response.json()
        for s in data["suggestions"]:
            assert "id" in s
            assert "rank" in s
            assert "title" in s
            assert "description" in s
            assert "estimated_saving_ms" in s
            assert "effort" in s
            assert s["estimated_saving_ms"] > 0

    def test_total_saving_exceeds_minimum(self, seeded_ai_client):
        """Per spec: sum of estimated_saving_ms >= 5000."""
        response = seeded_ai_client.get("/api/analyses/1")
        data = response.json()
        total_saving = sum(s["estimated_saving_ms"] for s in data["suggestions"])
        assert total_saving >= 5000
