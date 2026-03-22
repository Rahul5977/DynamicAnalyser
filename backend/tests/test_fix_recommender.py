"""Tests for the fix recommender: diff generation, confidence scoring, insights."""

import json
import pytest
from datetime import datetime

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
from app.services.fix_recommender import FixRecommender


@pytest.fixture
def repo_with_analyses(db_session):
    """Create a repo with multiple analyses and suggestions."""
    repo = TrackedRepository(
        full_name="octocat/Hello-World", owner="octocat", name="Hello-World"
    )
    db_session.add(repo)
    db_session.flush()

    # Create a run
    run = PipelineRun(
        repository_id=repo.id,
        github_run_id=3000,
        run_number=1,
        workflow_name="CI",
        status="completed",
        conclusion="success",
        head_branch="main",
        head_sha="def456",
        total_duration_ms=20000,
        created_at=datetime(2024, 3, 1, 10, 0, 0),
    )
    db_session.add(run)
    db_session.flush()

    db_session.add(StepTiming(
        pipeline_run_id=run.id,
        step_name="Install",
        step_number=1,
        duration_ms=10000,
        status="success",
    ))

    # Code index with a function
    code_idx = CodeIndex(
        repository_id=repo.id,
        commit_sha="def456",
        status="completed",
        total_functions=1,
        total_log_calls=0,
        completed_at=datetime(2024, 3, 1, 10, 0, 0),
    )
    db_session.add(code_idx)
    db_session.flush()

    db_session.add(IndexedFunction(
        code_index_id=code_idx.id,
        function_name="install_deps",
        qualified_name="build.install_deps",
        file_path="build/setup.py",
        line_number=5,
        end_line_number=20,
        language="py",
    ))

    # Analysis 1
    a1 = Analysis(
        pipeline_run_id=run.id,
        repository_id=repo.id,
        status="completed",
        root_cause="No caching",
        primary_bottleneck="install_deps",
        anti_patterns_json=json.dumps(["No dependency caching"]),
        estimated_total_saving_ms=5000,
        completed_at=datetime(2024, 3, 1, 10, 30, 0),
    )
    db_session.add(a1)
    db_session.flush()

    s1 = AnalysisSuggestion(
        analysis_id=a1.id,
        rank=1,
        title="Add pip cache",
        description="Cache pip packages",
        target_function="install_deps",
        target_file="build/setup.py",
        estimated_saving_ms=3000,
        effort="low",
        diff_hint="Before: pip install -r requirements.txt\nAfter: pip install --cache-dir .cache -r requirements.txt",
        anti_pattern="No dependency caching",
    )
    db_session.add(s1)

    s2 = AnalysisSuggestion(
        analysis_id=a1.id,
        rank=2,
        title="Parallelize tests",
        description="Run tests in parallel",
        target_function="",
        target_file="",
        estimated_saving_ms=2000,
        effort="medium",
        diff_hint="Before: pytest tests/\nAfter: pytest -n auto tests/",
        anti_pattern="Sequential test execution",
    )
    db_session.add(s2)

    # Analysis 2 (same pattern, for recurrence testing)
    a2 = Analysis(
        pipeline_run_id=run.id,
        repository_id=repo.id,
        status="completed",
        root_cause="Still no caching",
        primary_bottleneck="install_deps",
        anti_patterns_json=json.dumps(["No dependency caching"]),
        estimated_total_saving_ms=4000,
        completed_at=datetime(2024, 3, 2, 10, 30, 0),
    )
    db_session.add(a2)
    db_session.flush()

    db_session.add(AnalysisSuggestion(
        analysis_id=a2.id,
        rank=1,
        title="Add pip cache key",
        description="Use GitHub Actions cache",
        target_function="install_deps",
        target_file="build/setup.py",
        estimated_saving_ms=3500,
        effort="low",
        anti_pattern="No dependency caching",
    ))

    # Analysis 3 (same pattern again, for count >= 3)
    a3 = Analysis(
        pipeline_run_id=run.id,
        repository_id=repo.id,
        status="completed",
        root_cause="Caching still missing",
        primary_bottleneck="install_deps",
        anti_patterns_json=json.dumps(["No dependency caching"]),
        estimated_total_saving_ms=4500,
        completed_at=datetime(2024, 3, 3, 10, 30, 0),
    )
    db_session.add(a3)
    db_session.flush()

    db_session.add(AnalysisSuggestion(
        analysis_id=a3.id,
        rank=1,
        title="Implement caching",
        description="Add caching layer",
        target_function="install_deps",
        target_file="build/setup.py",
        estimated_saving_ms=3200,
        effort="low",
        anti_pattern="No dependency caching",
    ))

    db_session.commit()
    return repo, a1


# ── Diff Generation Tests ────────────────────────────────────────

class TestDiffGeneration:
    def test_before_after_format(self, db_session):
        recommender = FixRecommender(db_session)
        diff = recommender._generate_unified_diff(
            "build/setup.py",
            "install_deps",
            "Before: pip install -r requirements.txt\nAfter: pip install --cache-dir .cache -r requirements.txt",
        )
        assert diff is not None
        assert "---" in diff
        assert "+++" in diff
        assert "-pip install -r requirements.txt" in diff
        assert "+pip install --cache-dir .cache -r requirements.txt" in diff

    def test_arrow_separator_format(self, db_session):
        recommender = FixRecommender(db_session)
        diff = recommender._generate_unified_diff(
            "test.py", "run_tests",
            "pytest tests/ -> pytest -n auto tests/",
        )
        assert diff is not None
        assert "-pytest tests/" in diff
        assert "+pytest -n auto tests/" in diff

    def test_empty_diff_hint(self, db_session):
        recommender = FixRecommender(db_session)
        diff = recommender._generate_unified_diff("f.py", "fn", "")
        assert diff is None

    def test_none_diff_hint(self, db_session):
        recommender = FixRecommender(db_session)
        diff = recommender._generate_unified_diff("f.py", "fn", None)
        assert diff is None

    def test_multiline_before_after(self, db_session):
        recommender = FixRecommender(db_session)
        hint = "Before:\ndef install():\n    os.system('pip install')\nAfter:\ndef install():\n    subprocess.run(['pip', 'install', '--cache-dir', '.cache'])"
        diff = recommender._generate_unified_diff("setup.py", "install", hint)
        assert diff is not None
        assert "---" in diff


class TestDiffHintParsing:
    def test_before_after_parsing(self):
        before, after = FixRecommender._parse_diff_hint(
            "Before: old code\nAfter: new code"
        )
        assert before == ["old code"]
        assert after == ["new code"]

    def test_arrow_parsing(self):
        before, after = FixRecommender._parse_diff_hint("old -> new")
        assert before == ["old"]
        assert after == ["new"]

    def test_double_arrow_parsing(self):
        before, after = FixRecommender._parse_diff_hint("old => new")
        assert before == ["old"]
        assert after == ["new"]

    def test_fallback_no_separator(self):
        before, after = FixRecommender._parse_diff_hint("just new code here")
        assert before == []
        assert after == ["just new code here"]


# ── Confidence Scoring Tests ─────────────────────────────────────

class TestConfidenceScoring:
    def test_high_confidence_recurring_pattern(self, db_session, repo_with_analyses):
        repo, analysis = repo_with_analyses
        recommender = FixRecommender(db_session)

        suggestion = analysis.suggestions[0]  # "No dependency caching" with install_deps
        confidence = recommender._compute_confidence(suggestion, analysis)

        # Pattern seen 3+ times → +0.3, function exists → +0.1, reasonable saving → +0.1
        assert confidence >= 0.8

    def test_base_confidence(self, db_session):
        repo = TrackedRepository(
            full_name="fresh/repo", owner="fresh", name="repo"
        )
        db_session.add(repo)
        db_session.flush()

        analysis = Analysis(
            pipeline_run_id=1,
            repository_id=repo.id,
            status="completed",
        )
        db_session.add(analysis)
        db_session.flush()

        suggestion = AnalysisSuggestion(
            analysis_id=analysis.id,
            rank=1,
            title="Something",
            description="Something to do",
            estimated_saving_ms=100,  # too low for bonus
            effort="low",
            anti_pattern=None,
            target_function=None,
        )
        db_session.add(suggestion)
        db_session.commit()

        recommender = FixRecommender(db_session)
        confidence = recommender._compute_confidence(suggestion, analysis)
        assert confidence == 0.5  # Base score only

    def test_reasonable_saving_bonus(self, db_session):
        repo = TrackedRepository(
            full_name="test/repo2", owner="test", name="repo2"
        )
        db_session.add(repo)
        db_session.flush()

        analysis = Analysis(
            pipeline_run_id=1,
            repository_id=repo.id,
            status="completed",
        )
        db_session.add(analysis)
        db_session.flush()

        suggestion = AnalysisSuggestion(
            analysis_id=analysis.id,
            rank=1,
            title="Fix",
            description="Do it",
            estimated_saving_ms=3000,  # in reasonable range
            effort="low",
        )
        db_session.add(suggestion)
        db_session.commit()

        recommender = FixRecommender(db_session)
        confidence = recommender._compute_confidence(suggestion, analysis)
        assert confidence >= 0.6  # base + saving bonus


# ── Enrichment Integration Tests ─────────────────────────────────

class TestEnrichment:
    def test_enrich_analysis_updates_suggestions(self, db_session, repo_with_analyses):
        repo, analysis = repo_with_analyses
        recommender = FixRecommender(db_session)

        enriched = recommender.enrich_analysis(analysis)
        assert enriched.suggestions[0].confidence_score is not None
        # First suggestion has a diff_hint → should have enriched_diff
        assert enriched.suggestions[0].enriched_diff is not None

    def test_enrich_empty_analysis(self, db_session):
        repo = TrackedRepository(
            full_name="empty/repo", owner="empty", name="repo"
        )
        db_session.add(repo)
        db_session.flush()

        analysis = Analysis(
            pipeline_run_id=1,
            repository_id=repo.id,
            status="completed",
        )
        db_session.add(analysis)
        db_session.commit()

        recommender = FixRecommender(db_session)
        result = recommender.enrich_analysis(analysis)
        assert result.suggestions == []


# ── Repository Insights Tests ────────────────────────────────────

class TestRepoInsights:
    def test_insights_aggregation(self, db_session, repo_with_analyses):
        repo, _ = repo_with_analyses
        recommender = FixRecommender(db_session)
        insights = recommender.get_repo_insights(repo.id)

        assert insights["total_analyses"] == 3
        assert insights["most_common_bottleneck"] == "install_deps"
        assert insights["avg_total_saving_ms"] > 0

        # "No dependency caching" should be the most common anti-pattern
        patterns = insights["anti_patterns"]
        assert len(patterns) >= 1
        caching_pattern = next(
            (p for p in patterns if p["anti_pattern"] == "No dependency caching"), None
        )
        assert caching_pattern is not None
        assert caching_pattern["occurrence_count"] >= 3
        assert "install_deps" in caching_pattern["affected_functions"]

    def test_insights_empty_repo(self, db_session):
        repo = TrackedRepository(
            full_name="empty/repo2", owner="empty", name="repo2"
        )
        db_session.add(repo)
        db_session.commit()

        recommender = FixRecommender(db_session)
        insights = recommender.get_repo_insights(repo.id)
        assert insights["total_analyses"] == 0
        assert insights["anti_patterns"] == []
        assert insights["most_common_bottleneck"] is None
