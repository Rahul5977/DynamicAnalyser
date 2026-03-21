import json
import pytest
from datetime import datetime

from app.models.database import (
    Base,
    TrackedRepository,
    PipelineRun,
    StepTiming,
    CodeIndex,
    IndexedFunction,
    IndexedLogCall,
)
from app.services.trace_correlator import TraceCorrelator, _clean_log_line


@pytest.fixture
def repo_with_index(db_session):
    """Create a repo, a run, steps, and a completed code index."""
    repo = TrackedRepository(
        full_name="octocat/Hello-World", owner="octocat", name="Hello-World"
    )
    db_session.add(repo)
    db_session.flush()

    run = PipelineRun(
        repository_id=repo.id,
        github_run_id=12345,
        run_number=42,
        workflow_name="CI",
        status="completed",
        conclusion="success",
        head_branch="main",
        head_sha="abc123def456",
        total_duration_ms=10000,
        created_at=datetime(2024, 3, 19, 10, 30, 0),
    )
    db_session.add(run)
    db_session.flush()

    steps = [
        StepTiming(
            pipeline_run_id=run.id,
            step_name="Run migrations",
            step_number=1,
            duration_ms=5000,
            status="success",
            log_excerpt="Running database migrations\nMigration complete",
        ),
        StepTiming(
            pipeline_run_id=run.id,
            step_name="Run tests",
            step_number=2,
            duration_ms=3000,
            status="success",
            log_excerpt="Executing test suite\nAll tests passed",
        ),
        StepTiming(
            pipeline_run_id=run.id,
            step_name="Deploy",
            step_number=3,
            duration_ms=2000,
            status="success",
            log_excerpt="Starting deployment process",
        ),
    ]
    for s in steps:
        db_session.add(s)
    db_session.flush()

    # Create code index
    code_idx = CodeIndex(
        repository_id=repo.id,
        commit_sha="abc123def456",
        status="completed",
        total_functions=3,
        total_log_calls=3,
        completed_at=datetime(2024, 3, 19, 10, 0, 0),
    )
    db_session.add(code_idx)
    db_session.flush()

    # Add indexed functions
    funcs = [
        IndexedFunction(
            code_index_id=code_idx.id,
            function_name="run_migrations",
            qualified_name="db.run_migrations",
            file_path="db/migrate.py",
            line_number=10,
            end_line_number=20,
            language="py",
            calls_json=json.dumps(["execute_sql"]),
        ),
        IndexedFunction(
            code_index_id=code_idx.id,
            function_name="execute_sql",
            qualified_name="db.execute_sql",
            file_path="db/migrate.py",
            line_number=22,
            end_line_number=30,
            language="py",
            calls_json=None,
        ),
        IndexedFunction(
            code_index_id=code_idx.id,
            function_name="deploy_app",
            qualified_name="deploy.deploy_app",
            file_path="deploy/main.py",
            line_number=5,
            end_line_number=15,
            language="py",
            calls_json=json.dumps(["run_migrations"]),
        ),
    ]
    for f in funcs:
        db_session.add(f)

    # Add indexed log calls
    log_calls = [
        IndexedLogCall(
            code_index_id=code_idx.id,
            log_string="Running database migrations",
            file_path="db/migrate.py",
            line_number=12,
            function_name="run_migrations",
            log_level="warning",
            language="py",
        ),
        IndexedLogCall(
            code_index_id=code_idx.id,
            log_string="Starting deployment process",
            file_path="deploy/main.py",
            line_number=8,
            function_name="deploy_app",
            log_level="info",
            language="py",
        ),
    ]
    for lc in log_calls:
        db_session.add(lc)
    db_session.commit()

    return repo, run


class TestCleanLogLine:
    def test_strip_timestamp(self):
        line = "2024-03-19T10:32:01.456789Z Installing dependencies..."
        assert _clean_log_line(line) == "Installing dependencies..."

    def test_strip_annotation(self):
        line = "##[group]Run npm install"
        assert _clean_log_line(line) == "Run npm install"

    def test_strip_both(self):
        line = "2024-03-19T10:32:01.456789Z ##[group]Run npm install"
        assert _clean_log_line(line) == "Run npm install"

    def test_plain_line_unchanged(self):
        assert _clean_log_line("hello world") == "hello world"


class TestTraceCorrelator:
    def test_exact_match(self, db_session, repo_with_index):
        repo, run = repo_with_index
        correlator = TraceCorrelator(db_session)
        trace = correlator.correlate_run(run.id)

        # "Running database migrations" should exact-match
        migration_step = next(
            s for s in trace.steps if s.step_name == "Run migrations"
        )
        assert migration_step.source_location is not None
        assert migration_step.source_location.function_name == "run_migrations"
        assert migration_step.source_location.file_path == "db/migrate.py"
        assert migration_step.match_method == "exact"
        assert migration_step.match_confidence == 1.0

    def test_deploy_step_matches(self, db_session, repo_with_index):
        repo, run = repo_with_index
        correlator = TraceCorrelator(db_session)
        trace = correlator.correlate_run(run.id)

        deploy_step = next(s for s in trace.steps if s.step_name == "Deploy")
        assert deploy_step.source_location is not None
        assert deploy_step.source_location.function_name == "deploy_app"
        assert deploy_step.match_method == "exact"

    def test_match_rate(self, db_session, repo_with_index):
        repo, run = repo_with_index
        correlator = TraceCorrelator(db_session)
        trace = correlator.correlate_run(run.id)

        assert trace.total_steps == 3
        assert trace.matched_steps >= 2  # at least migrations + deploy
        assert trace.match_rate > 0.0

    def test_call_chain_populated(self, db_session, repo_with_index):
        repo, run = repo_with_index
        correlator = TraceCorrelator(db_session)
        trace = correlator.correlate_run(run.id)

        migration_step = next(
            s for s in trace.steps if s.step_name == "Run migrations"
        )
        # run_migrations is called by deploy_app
        chain_names = [c.function_name for c in migration_step.call_chain]
        assert "deploy_app" in chain_names

    def test_source_function_persisted(self, db_session, repo_with_index):
        repo, run = repo_with_index
        correlator = TraceCorrelator(db_session)
        correlator.correlate_run(run.id)

        # Check that source_function was saved to the DB
        step = (
            db_session.query(StepTiming)
            .filter(
                StepTiming.pipeline_run_id == run.id,
                StepTiming.step_name == "Run migrations",
            )
            .first()
        )
        assert step.source_function == "run_migrations"

    def test_no_code_index_graceful(self, db_session):
        """When no code index exists, trace should still return with match_rate=0."""
        repo = TrackedRepository(
            full_name="no-index/repo", owner="no-index", name="repo"
        )
        db_session.add(repo)
        db_session.flush()

        run = PipelineRun(
            repository_id=repo.id,
            github_run_id=99999,
            run_number=1,
            status="completed",
            total_duration_ms=1000,
            created_at=datetime(2024, 3, 19),
        )
        db_session.add(run)
        db_session.flush()

        step = StepTiming(
            pipeline_run_id=run.id,
            step_name="Build",
            step_number=1,
            duration_ms=1000,
            status="success",
            log_excerpt="Building project",
        )
        db_session.add(step)
        db_session.commit()

        correlator = TraceCorrelator(db_session)
        trace = correlator.correlate_run(run.id)
        assert trace.match_rate == 0.0
        assert trace.total_steps == 1

    def test_grep_fallback(self, db_session, repo_with_index):
        """The 'Run tests' step has no log match but 'deploy' keyword may match."""
        repo, run = repo_with_index
        correlator = TraceCorrelator(db_session)
        trace = correlator.correlate_run(run.id)

        # Even steps without exact/fuzzy match may get grep fallback
        for step in trace.steps:
            if step.match_method == "grep":
                assert step.match_confidence == 0.5 or step.match_confidence == 0.3
