"""Tests for Phase 4 API: dashboard, analytics, webhook, demo seed."""

import hashlib
import hmac
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
    Analysis,
    AnalysisSuggestion,
)


def _make_test_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def seeded_dashboard_client():
    """Client with repo, runs, and analyses for dashboard tests."""
    engine = _make_test_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    session = Session()

    repo = TrackedRepository(
        full_name="octocat/Hello-World", owner="octocat", name="Hello-World"
    )
    session.add(repo)
    session.flush()

    for i in range(5):
        run = PipelineRun(
            repository_id=repo.id,
            github_run_id=7000 + i,
            run_number=i + 1,
            workflow_name="CI",
            status="completed",
            conclusion="success",
            head_branch="main",
            head_sha=f"sha{i:04d}",
            total_duration_ms=18000 + i * 500,
            created_at=datetime(2024, 3, 1, 10 + i, 0, 0),
        )
        session.add(run)
        session.flush()

        for step_name, dur in [
            ("Install", 6000 + i * 200),
            ("Test", 5000),
            ("Deploy", 2000),
        ]:
            session.add(StepTiming(
                pipeline_run_id=run.id,
                step_name=step_name,
                step_number={"Install": 1, "Test": 2, "Deploy": 3}[step_name],
                duration_ms=dur,
                status="success",
            ))

    # Create analyses
    for i in range(3):
        a = Analysis(
            pipeline_run_id=i + 3,  # runs 3, 4, 5
            repository_id=repo.id,
            status="completed",
            root_cause=f"Root cause #{i+1}",
            primary_bottleneck="Install",
            anti_patterns_json=json.dumps(["No dependency caching"]),
            estimated_total_saving_ms=5000 + i * 500,
            llm_model="test-model",
            completed_at=datetime(2024, 3, 1, 12 + i, 0, 0),
        )
        session.add(a)
        session.flush()

        session.add(AnalysisSuggestion(
            analysis_id=a.id,
            rank=1,
            title="Add cache",
            description="Cache deps",
            target_function="install_deps",
            target_file="build/setup.py",
            estimated_saving_ms=3000,
            effort="low",
            anti_pattern="No dependency caching",
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
def empty_dashboard_client():
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


# ── Dashboard Summary Tests ──────────────────────────────────────

class TestDashboardSummary:
    def test_summary_with_data(self, seeded_dashboard_client):
        response = seeded_dashboard_client.get("/api/dashboard/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_repos"] == 1
        assert data["total_runs"] == 5
        assert data["total_analyses"] == 3
        assert data["avg_duration_ms"] > 0
        assert data["avg_saving_ms"] > 0
        assert len(data["recent_runs"]) == 5

    def test_summary_empty_db(self, empty_dashboard_client):
        response = empty_dashboard_client.get("/api/dashboard/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_repos"] == 0
        assert data["total_runs"] == 0
        assert data["recent_runs"] == []


# ── Repository Analytics Tests ───────────────────────────────────

class TestRepoAnalytics:
    def test_analytics_returns_data(self, seeded_dashboard_client):
        response = seeded_dashboard_client.get(
            "/api/repos/octocat/Hello-World/analytics?window=10"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["repository"] == "octocat/Hello-World"
        assert len(data["duration_trend"]) == 5
        assert len(data["step_evolution"]) > 0
        assert isinstance(data["anti_pattern_frequency"], dict)

        # Duration trend should be ordered oldest first
        trend = data["duration_trend"]
        assert trend[0]["run_number"] < trend[-1]["run_number"]

    def test_analytics_repo_not_found(self, empty_dashboard_client):
        response = empty_dashboard_client.get(
            "/api/repos/unknown/repo/analytics"
        )
        assert response.status_code == 404

    def test_step_evolution_has_pct(self, seeded_dashboard_client):
        response = seeded_dashboard_client.get(
            "/api/repos/octocat/Hello-World/analytics"
        )
        data = response.json()
        if data["step_evolution"]:
            pt = data["step_evolution"][0]
            assert "pct_of_total" in pt
            assert 0 <= pt["pct_of_total"] <= 1


# ── Webhook Tests ────────────────────────────────────────────────

class TestWebhook:
    def test_ping_event(self, empty_dashboard_client):
        response = empty_dashboard_client.post(
            "/api/webhook/github",
            json={"zen": "test"},
            headers={"X-GitHub-Event": "ping"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "pong"

    def test_ignored_event(self, empty_dashboard_client):
        response = empty_dashboard_client.post(
            "/api/webhook/github",
            json={"action": "created"},
            headers={"X-GitHub-Event": "push"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_workflow_run_untracked_repo(self, empty_dashboard_client):
        payload = {
            "action": "completed",
            "workflow_run": {"id": 12345, "head_branch": "main", "run_number": 1},
            "repository": {"full_name": "unknown/repo"},
        }
        response = empty_dashboard_client.post(
            "/api/webhook/github",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"
        assert "not tracked" in data["reason"]

    def test_workflow_run_missing_data(self, empty_dashboard_client):
        payload = {
            "action": "completed",
            "workflow_run": {},
            "repository": {},
        }
        response = empty_dashboard_client.post(
            "/api/webhook/github",
            json=payload,
            headers={"X-GitHub-Event": "workflow_run"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"


# ── Demo Seed Tests ──────────────────────────────────────────────

class TestDemoSeed:
    def test_seed_creates_data(self, empty_dashboard_client):
        response = empty_dashboard_client.post("/api/demo/seed")
        assert response.status_code == 200
        data = response.json()
        assert data["repos_created"] == 1
        assert data["runs_created"] == 20
        assert data["analyses_created"] == 3
        assert "successfully" in data["message"]

    def test_seed_idempotent(self, empty_dashboard_client):
        empty_dashboard_client.post("/api/demo/seed")
        response = empty_dashboard_client.post("/api/demo/seed")
        assert response.status_code == 200
        # Should not crash on second seed

    def test_dashboard_after_seed(self, empty_dashboard_client):
        empty_dashboard_client.post("/api/demo/seed")
        response = empty_dashboard_client.get("/api/dashboard/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_repos"] >= 1
        assert data["total_runs"] >= 20

    def test_analytics_after_seed(self, empty_dashboard_client):
        empty_dashboard_client.post("/api/demo/seed")
        response = empty_dashboard_client.get(
            "/api/repos/demo-org/sample-api/analytics"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["duration_trend"]) == 20
        assert len(data["step_evolution"]) > 0


# ── Webhook Signature Verification ───────────────────────────────

class TestWebhookSignature:
    def test_verify_valid_signature(self):
        from app.services.webhook_handler import WebhookHandler
        body = b'{"test": "data"}'
        secret = "test-secret"
        sig = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        assert WebhookHandler.verify_signature(body, sig, secret) is True

    def test_verify_invalid_signature(self):
        from app.services.webhook_handler import WebhookHandler
        body = b'{"test": "data"}'
        assert WebhookHandler.verify_signature(body, "sha256=invalid", "secret") is False

    def test_verify_missing_signature(self):
        from app.services.webhook_handler import WebhookHandler
        assert WebhookHandler.verify_signature(b"test", "", "secret") is False
