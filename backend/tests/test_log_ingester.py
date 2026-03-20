import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.core.exceptions import IngestionError, RepositoryNotFoundError, RunNotFoundError
from app.db.repository import TrackedRepoRepository, PipelineRunRepository
from app.models.database import TrackedRepository, PipelineRun, StepTiming
from app.services.ingester import LogIngester
from app.services.github_client import WorkflowRunInfo


SAMPLE_LOG = """=== build/1_Set up job.txt ===
2024-03-19T10:32:01.000000Z Setting up runner...
2024-03-19T10:32:02.000000Z Runner ready
=== build/2_Run npm install.txt ===
2024-03-19T10:32:03.000000Z ##[group]Run npm install
2024-03-19T10:32:03.100000Z npm install
2024-03-19T10:32:08.000000Z added 1234 packages
2024-03-19T10:32:08.100000Z ##[endgroup]
=== build/3_Run tests.txt ===
2024-03-19T10:32:09.000000Z ##[group]Run npm test
2024-03-19T10:32:09.500000Z PASS src/app.test.ts
2024-03-19T10:32:12.000000Z All tests passed
"""

MOCK_RUN_INFO = WorkflowRunInfo(
    run_id=12345,
    run_number=42,
    workflow_name="CI",
    status="completed",
    conclusion="success",
    head_branch="main",
    head_sha="abc123",
    created_at=datetime(2024, 3, 19, 10, 30, 0),
)


@pytest.fixture
def tracked_repo(db_session):
    repo = TrackedRepository(
        full_name="octocat/Hello-World",
        owner="octocat",
        name="Hello-World",
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)
    return repo


@pytest.fixture
def mock_github():
    client = MagicMock()
    client.get_workflow_runs.return_value = [MOCK_RUN_INFO]
    client.get_run_logs.return_value = SAMPLE_LOG
    return client


class TestLogIngester:
    def test_successful_ingestion(self, db_session, tracked_repo, mock_github):
        ingester = LogIngester(db_session, github_client=mock_github)
        result = ingester.ingest_run("octocat/Hello-World", 12345)

        assert result.github_run_id == 12345
        assert result.steps_parsed == 3
        assert result.total_duration_ms > 0
        assert result.slowest_step == "Run npm install"
        assert result.slowest_step_ms == 5100

    def test_run_stored_in_db(self, db_session, tracked_repo, mock_github):
        ingester = LogIngester(db_session, github_client=mock_github)
        result = ingester.ingest_run("octocat/Hello-World", 12345)

        run_store = PipelineRunRepository(db_session)
        run = run_store.get_by_id(result.run_id)
        assert run is not None
        assert run.github_run_id == 12345
        assert run.run_number == 42
        assert run.workflow_name == "CI"
        assert len(run.step_timings) == 3

    def test_steps_sorted_by_duration_desc(self, db_session, tracked_repo, mock_github):
        ingester = LogIngester(db_session, github_client=mock_github)
        result = ingester.ingest_run("octocat/Hello-World", 12345)

        run_store = PipelineRunRepository(db_session)
        run = run_store.get_by_id(result.run_id)
        sorted_steps = sorted(run.step_timings, key=lambda s: s.duration_ms, reverse=True)
        assert sorted_steps[0].step_name == "Run npm install"
        assert sorted_steps[0].duration_ms == 5100

    def test_duplicate_ingestion_raises(self, db_session, tracked_repo, mock_github):
        ingester = LogIngester(db_session, github_client=mock_github)
        ingester.ingest_run("octocat/Hello-World", 12345)

        with pytest.raises(IngestionError, match="already been ingested"):
            ingester.ingest_run("octocat/Hello-World", 12345)

    def test_untracked_repo_raises(self, db_session, mock_github):
        ingester = LogIngester(db_session, github_client=mock_github)
        with pytest.raises(RepositoryNotFoundError):
            ingester.ingest_run("unknown/repo", 12345)

    def test_run_not_found_raises(self, db_session, tracked_repo, mock_github):
        mock_github.get_workflow_runs.return_value = []
        ingester = LogIngester(db_session, github_client=mock_github)
        with pytest.raises(RunNotFoundError, match="not found"):
            ingester.ingest_run("octocat/Hello-World", 99999)

    def test_github_log_download_failure(self, db_session, tracked_repo, mock_github):
        mock_github.get_run_logs.side_effect = Exception("Network error")
        ingester = LogIngester(db_session, github_client=mock_github)
        with pytest.raises(IngestionError, match="Failed to download"):
            ingester.ingest_run("octocat/Hello-World", 12345)

    def test_step_timings_have_correct_fields(self, db_session, tracked_repo, mock_github):
        ingester = LogIngester(db_session, github_client=mock_github)
        result = ingester.ingest_run("octocat/Hello-World", 12345)

        run_store = PipelineRunRepository(db_session)
        run = run_store.get_by_id(result.run_id)

        for step in run.step_timings:
            assert step.step_name
            assert step.step_number >= 0
            assert step.duration_ms >= 0
            assert step.started_at is not None
            assert step.ended_at is not None
            assert step.status in ("success", "failure")


class TestDatabaseQueries:
    def test_get_run_by_id(self, db_session, tracked_repo, mock_github):
        ingester = LogIngester(db_session, github_client=mock_github)
        result = ingester.ingest_run("octocat/Hello-World", 12345)

        run_store = PipelineRunRepository(db_session)
        run = run_store.get_by_id(result.run_id)
        assert run.github_run_id == 12345

    def test_list_runs_by_repo(self, db_session, tracked_repo, mock_github):
        ingester = LogIngester(db_session, github_client=mock_github)
        ingester.ingest_run("octocat/Hello-World", 12345)

        # Ingest a second run
        mock_github.get_workflow_runs.return_value = [
            WorkflowRunInfo(
                run_id=12346,
                run_number=43,
                workflow_name="CI",
                status="completed",
                conclusion="success",
                head_branch="main",
                head_sha="def456",
                created_at=datetime(2024, 3, 19, 11, 0, 0),
            )
        ]
        ingester.ingest_run("octocat/Hello-World", 12346)

        run_store = PipelineRunRepository(db_session)
        runs, total = run_store.list_by_repo(tracked_repo.id)
        assert total == 2
        assert len(runs) == 2

    def test_run_not_found(self, db_session):
        run_store = PipelineRunRepository(db_session)
        with pytest.raises(Exception, match="not found"):
            run_store.get_by_id(999)
