"""Tests for the demo data seeder."""

import pytest
from app.models.database import (
    TrackedRepository,
    PipelineRun,
    StepTiming,
    CodeIndex,
    IndexedFunction,
    IndexedLogCall,
    Analysis,
    AnalysisSuggestion,
)
from app.services.demo_seeder import DemoSeeder


class TestDemoSeeder:
    def test_seed_creates_repo(self, db_session):
        seeder = DemoSeeder(db_session)
        result = seeder.seed()
        assert result["repos_created"] == 1

        repo = db_session.query(TrackedRepository).filter_by(
            full_name="demo-org/sample-api"
        ).first()
        assert repo is not None

    def test_seed_creates_runs(self, db_session):
        seeder = DemoSeeder(db_session)
        result = seeder.seed()
        assert result["runs_created"] == 20

        runs = db_session.query(PipelineRun).all()
        assert len(runs) == 20

    def test_seed_creates_steps(self, db_session):
        seeder = DemoSeeder(db_session)
        seeder.seed()

        steps = db_session.query(StepTiming).all()
        # 20 runs × 6 steps = 120 steps
        assert len(steps) == 120

    def test_seed_creates_code_index(self, db_session):
        seeder = DemoSeeder(db_session)
        seeder.seed()

        idx = db_session.query(CodeIndex).filter_by(status="completed").first()
        assert idx is not None
        assert idx.total_functions == 8
        assert idx.total_log_calls == 5

    def test_seed_creates_analyses(self, db_session):
        seeder = DemoSeeder(db_session)
        result = seeder.seed()
        assert result["analyses_created"] == 3

        analyses = db_session.query(Analysis).filter_by(status="completed").all()
        assert len(analyses) == 3

    def test_analyses_have_suggestions(self, db_session):
        seeder = DemoSeeder(db_session)
        seeder.seed()

        suggestions = db_session.query(AnalysisSuggestion).all()
        assert len(suggestions) > 0
        for s in suggestions:
            assert s.estimated_saving_ms > 0
            assert s.title

    def test_seed_idempotent(self, db_session):
        seeder = DemoSeeder(db_session)
        seeder.seed()
        seeder.seed()

        repos = db_session.query(TrackedRepository).filter_by(
            full_name="demo-org/sample-api"
        ).all()
        assert len(repos) == 1

    def test_runs_have_varying_durations(self, db_session):
        seeder = DemoSeeder(db_session)
        seeder.seed()

        runs = db_session.query(PipelineRun).order_by(PipelineRun.created_at).all()
        durations = [r.total_duration_ms for r in runs]
        # Not all the same (variation from random + trend)
        assert len(set(durations)) > 1

    def test_code_index_has_functions(self, db_session):
        seeder = DemoSeeder(db_session)
        seeder.seed()

        funcs = db_session.query(IndexedFunction).all()
        assert len(funcs) == 8
        func_names = [f.function_name for f in funcs]
        assert "install_deps" in func_names
        assert "run_migrations" in func_names

    def test_code_index_has_log_calls(self, db_session):
        seeder = DemoSeeder(db_session)
        seeder.seed()

        logs = db_session.query(IndexedLogCall).all()
        assert len(logs) == 5
