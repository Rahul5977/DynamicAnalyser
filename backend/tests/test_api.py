import pytest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.session import get_db
from app.models.database import Base, TrackedRepository, PipelineRun, StepTiming


def _make_test_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def test_setup():
    engine = _make_test_engine()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client, Session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def client(test_setup):
    client, _ = test_setup
    return client


@pytest.fixture
def seeded_client(test_setup):
    client, Session = test_setup
    session = Session()
    repo = TrackedRepository(
        full_name="octocat/Hello-World", owner="octocat", name="Hello-World"
    )
    session.add(repo)
    session.flush()

    run = PipelineRun(
        repository_id=repo.id,
        github_run_id=12345,
        run_number=42,
        workflow_name="CI",
        status="completed",
        conclusion="success",
        head_branch="main",
        head_sha="abc123",
        total_duration_ms=9600,
        created_at=datetime(2024, 3, 19, 10, 30, 0),
    )
    session.add(run)
    session.flush()

    for i, (name, dur) in enumerate(
        [("Set up job", 1500), ("Run npm install", 5100), ("Run tests", 3000)], 1
    ):
        session.add(
            StepTiming(
                pipeline_run_id=run.id,
                step_name=name,
                step_number=i,
                duration_ms=dur,
                status="success",
            )
        )
    session.commit()
    session.close()
    return client


class TestHealthEndpoint:
    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert data["database"] == "healthy"


class TestRepoEndpoints:
    def test_list_repos_empty(self, client):
        response = client.get("/api/repos")
        assert response.status_code == 200
        assert response.json() == []

    def test_add_repo(self, client):
        response = client.post(
            "/api/repos", json={"full_name": "octocat/Hello-World"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["full_name"] == "octocat/Hello-World"
        assert data["owner"] == "octocat"
        assert data["name"] == "Hello-World"

    def test_add_repo_invalid_name(self, client):
        response = client.post("/api/repos", json={"full_name": "invalid"})
        assert response.status_code == 422

    def test_add_repo_idempotent(self, client):
        client.post("/api/repos", json={"full_name": "octocat/Hello-World"})
        response = client.post(
            "/api/repos", json={"full_name": "octocat/Hello-World"}
        )
        assert response.status_code == 201

    def test_list_repos_after_add(self, client):
        client.post("/api/repos", json={"full_name": "octocat/Hello-World"})
        response = client.get("/api/repos")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["full_name"] == "octocat/Hello-World"


class TestRunEndpoints:
    def test_get_run(self, seeded_client):
        response = seeded_client.get("/api/runs/1")
        assert response.status_code == 200
        data = response.json()
        assert data["github_run_id"] == 12345
        assert data["run_number"] == 42
        assert len(data["step_timings"]) == 3
        assert data["step_timings"][0]["step_name"] == "Run npm install"
        assert data["step_timings"][0]["duration_ms"] == 5100

    def test_get_run_not_found(self, client):
        response = client.get("/api/runs/999")
        assert response.status_code == 404

    def test_list_runs_for_repo(self, seeded_client):
        response = seeded_client.get("/api/repos/octocat/Hello-World/runs")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["runs"]) == 1

    def test_list_runs_repo_not_found(self, client):
        response = client.get("/api/repos/unknown/repo/runs")
        assert response.status_code == 404
