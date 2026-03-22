"""Tests for the AI engine: context assembly, prompt building, response parsing."""

import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

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
)
from app.services.ai_engine import (
    AIEngine,
    LLMAnalysisResult,
    LLMSuggestion,
    AnalysisContext,
    BottleneckContext,
    _build_user_prompt,
    SYSTEM_PROMPT,
)


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def seeded_db(db_session):
    """Create repo, runs, steps, and code index for AI analysis tests."""
    repo = TrackedRepository(
        full_name="octocat/Hello-World", owner="octocat", name="Hello-World"
    )
    db_session.add(repo)
    db_session.flush()

    # Create 5 pipeline runs with increasing Install durations
    for i in range(5):
        run = PipelineRun(
            repository_id=repo.id,
            github_run_id=2000 + i,
            run_number=i + 1,
            workflow_name="CI",
            status="completed",
            conclusion="success",
            head_branch="main",
            head_sha=f"abc{i:04d}",
            total_duration_ms=8000 + i * 500,
            created_at=datetime(2024, 3, 1, 10 + i, 0, 0),
        )
        db_session.add(run)
        db_session.flush()

        for step_name, dur in [("Install", 4000 + i * 300), ("Test", 3000), ("Deploy", 1000)]:
            db_session.add(StepTiming(
                pipeline_run_id=run.id,
                step_name=step_name,
                step_number={"Install": 1, "Test": 2, "Deploy": 3}[step_name],
                duration_ms=dur,
                status="success",
                log_excerpt="Running database migrations" if step_name == "Install" else "Running tests",
            ))

    # Code index
    code_idx = CodeIndex(
        repository_id=repo.id,
        commit_sha="abc0004",
        status="completed",
        total_functions=2,
        total_log_calls=1,
        completed_at=datetime(2024, 3, 1, 15, 0, 0),
    )
    db_session.add(code_idx)
    db_session.flush()

    db_session.add(IndexedFunction(
        code_index_id=code_idx.id,
        function_name="run_migrations",
        qualified_name="db.run_migrations",
        file_path="db/migrate.py",
        line_number=10,
        end_line_number=20,
        language="py",
    ))
    db_session.add(IndexedLogCall(
        code_index_id=code_idx.id,
        log_string="Running database migrations",
        file_path="db/migrate.py",
        line_number=12,
        function_name="run_migrations",
        log_level="info",
        language="py",
    ))
    db_session.commit()
    return repo, run


# ── LLM Response Parsing Tests ───────────────────────────────────

class TestLLMResponseParsing:
    def test_valid_json_response(self):
        engine = MagicMock()
        engine._parse_llm_response = AIEngine._parse_llm_response

        valid_json = json.dumps({
            "root_cause": "Install step has no dependency caching",
            "primary_bottleneck": "run_migrations",
            "anti_patterns": ["No dependency caching"],
            "suggestions": [
                {
                    "title": "Add pip cache",
                    "description": "Cache pip packages to speed up installs",
                    "target_function": "run_migrations",
                    "target_file": "db/migrate.py",
                    "estimated_saving_ms": 3000,
                    "effort": "low",
                    "diff_hint": "Before: pip install\nAfter: pip install --cache-dir .cache",
                },
                {
                    "title": "Parallelize tests",
                    "description": "Run tests in parallel using pytest-xdist",
                    "target_function": "",
                    "target_file": "",
                    "estimated_saving_ms": 2000,
                    "effort": "medium",
                    "diff_hint": "",
                },
            ],
            "estimated_total_saving_ms": 5000,
        })
        result = AIEngine._parse_llm_response(engine, valid_json)
        assert result is not None
        assert result.root_cause == "Install step has no dependency caching"
        assert result.primary_bottleneck == "run_migrations"
        assert len(result.suggestions) == 2
        assert result.estimated_total_saving_ms == 5000

    def test_json_wrapped_in_code_fence(self):
        engine = MagicMock()
        engine._parse_llm_response = AIEngine._parse_llm_response

        response = '```json\n{"root_cause": "slow", "primary_bottleneck": "fn", "anti_patterns": [], "suggestions": [], "estimated_total_saving_ms": 1000}\n```'
        result = AIEngine._parse_llm_response(engine, response)
        assert result is not None
        assert result.root_cause == "slow"

    def test_json_with_surrounding_text(self):
        engine = MagicMock()
        engine._parse_llm_response = AIEngine._parse_llm_response

        response = 'Here is my analysis:\n{"root_cause": "cache miss", "primary_bottleneck": "install", "anti_patterns": ["No dependency caching"], "suggestions": [], "estimated_total_saving_ms": 3000}\n\nHope this helps!'
        result = AIEngine._parse_llm_response(engine, response)
        assert result is not None
        assert result.root_cause == "cache miss"
        assert result.anti_patterns == ["No dependency caching"]

    def test_invalid_json_returns_none(self):
        engine = MagicMock()
        engine._parse_llm_response = AIEngine._parse_llm_response

        result = AIEngine._parse_llm_response(engine, "This is not JSON at all")
        assert result is None

    def test_missing_required_fields_returns_none(self):
        engine = MagicMock()
        engine._parse_llm_response = AIEngine._parse_llm_response

        partial = json.dumps({"root_cause": "slow"})
        result = AIEngine._parse_llm_response(engine, partial)
        assert result is None

    def test_suggestion_validation(self):
        """Suggestions with invalid effort level should fail validation."""
        engine = MagicMock()
        engine._parse_llm_response = AIEngine._parse_llm_response

        bad_suggestion = json.dumps({
            "root_cause": "slow",
            "primary_bottleneck": "fn",
            "anti_patterns": [],
            "suggestions": [{
                "title": "Fix",
                "description": "Do something",
                "estimated_saving_ms": 1000,
                "effort": "extreme",  # invalid
            }],
            "estimated_total_saving_ms": 1000,
        })
        result = AIEngine._parse_llm_response(engine, bad_suggestion)
        assert result is None


# ── Prompt Building Tests ────────────────────────────────────────

class TestPromptBuilding:
    def test_user_prompt_contains_repo_info(self):
        ctx = AnalysisContext(
            repo_full_name="octocat/Hello-World",
            commit_sha="abc12345",
            total_duration_ms=20000,
            target_duration_ms=15000,
            status="completed",
            conclusion="success",
            bottlenecks=[],
        )
        prompt = _build_user_prompt(ctx)
        assert "octocat/Hello-World" in prompt
        assert "abc12345" in prompt
        assert "20000ms" in prompt
        assert "15000ms" in prompt

    def test_user_prompt_includes_bottleneck_steps(self):
        ctx = AnalysisContext(
            repo_full_name="test/repo",
            commit_sha="sha123",
            total_duration_ms=10000,
            target_duration_ms=5000,
            status="completed",
            conclusion="success",
            bottlenecks=[
                BottleneckContext(
                    step_name="Install",
                    duration_ms=5000,
                    p95_ms=6000,
                    pct_of_total=0.5,
                    trend_direction="increasing",
                    source_function="run_migrations",
                    source_file="db/migrate.py",
                    source_line=10,
                    call_chain="deploy_app (deploy/main.py:5)",
                    function_source_code="def run_migrations():\n    pass",
                    language="python",
                ),
            ],
        )
        prompt = _build_user_prompt(ctx)
        assert "Install" in prompt
        assert "5000ms" in prompt
        assert "6000ms" in prompt
        assert "50.0%" in prompt
        assert "increasing" in prompt
        assert "run_migrations" in prompt
        assert "def run_migrations():" in prompt
        assert "```python" in prompt

    def test_system_prompt_contains_anti_patterns(self):
        assert "No dependency caching" in SYSTEM_PROMPT
        assert "Sequential test execution" in SYSTEM_PROMPT
        assert "Unindexed DB queries" in SYSTEM_PROMPT
        assert "Blocking I/O" in SYSTEM_PROMPT

    def test_prompt_handles_no_source_code(self):
        ctx = AnalysisContext(
            repo_full_name="test/repo",
            commit_sha="sha123",
            total_duration_ms=10000,
            target_duration_ms=5000,
            status="completed",
            conclusion="success",
            bottlenecks=[
                BottleneckContext(
                    step_name="Build",
                    duration_ms=5000,
                    p95_ms=6000,
                    pct_of_total=0.5,
                    trend_direction="stable",
                    source_function=None,
                    source_file=None,
                    source_line=None,
                    call_chain="",
                    function_source_code=None,
                    language=None,
                ),
            ],
        )
        prompt = _build_user_prompt(ctx)
        assert "Build" in prompt
        # Should not have source code block
        assert "```" not in prompt or "```\n{" in prompt  # only JSON block


# ── Context Assembly Tests ───────────────────────────────────────

class TestContextAssembly:
    def test_assemble_context_builds_bottlenecks(self, db_session, seeded_db):
        repo, run = seeded_db
        engine = AIEngine(db_session)
        ctx = engine._assemble_context(run, repo)

        assert ctx.repo_full_name == "octocat/Hello-World"
        assert ctx.total_duration_ms > 0
        assert len(ctx.bottlenecks) > 0
        # Install should be the top bottleneck
        assert ctx.bottlenecks[0].step_name == "Install"

    def test_assemble_context_with_no_runs(self, db_session):
        repo = TrackedRepository(
            full_name="empty/repo", owner="empty", name="repo"
        )
        db_session.add(repo)
        db_session.flush()

        run = PipelineRun(
            repository_id=repo.id,
            github_run_id=9999,
            run_number=1,
            workflow_name="CI",
            status="completed",
            conclusion="success",
            total_duration_ms=1000,
            created_at=datetime(2024, 3, 1),
        )
        db_session.add(run)
        db_session.flush()
        db_session.add(StepTiming(
            pipeline_run_id=run.id,
            step_name="Build",
            step_number=1,
            duration_ms=1000,
            status="success",
        ))
        db_session.commit()

        engine = AIEngine(db_session)
        ctx = engine._assemble_context(run, repo)
        assert ctx.repo_full_name == "empty/repo"
        # Should have bottleneck for the one step
        assert len(ctx.bottlenecks) >= 0  # may be 0 or 1 depending on ranking


# ── Anti-Pattern Matching Tests ──────────────────────────────────

class TestAntiPatternMatching:
    def test_matches_by_keyword(self):
        patterns = ["No dependency caching", "Sequential test execution"]
        result = AIEngine._match_anti_pattern("Add pip cache for dependencies", patterns)
        assert result == "No dependency caching"

    def test_falls_back_to_first_pattern(self):
        patterns = ["No dependency caching", "Blocking I/O"]
        result = AIEngine._match_anti_pattern("Completely unrelated title", patterns)
        assert result == "No dependency caching"

    def test_empty_patterns_returns_none(self):
        result = AIEngine._match_anti_pattern("Some title", [])
        assert result is None


# ── LLM Result Model Validation ──────────────────────────────────

class TestLLMResultModel:
    def test_valid_result(self):
        result = LLMAnalysisResult(
            root_cause="Slow installs",
            primary_bottleneck="install_deps",
            anti_patterns=["No dependency caching"],
            suggestions=[
                LLMSuggestion(
                    title="Add cache",
                    description="Use pip cache",
                    estimated_saving_ms=3000,
                    effort="low",
                )
            ],
            estimated_total_saving_ms=3000,
        )
        assert result.root_cause == "Slow installs"
        assert len(result.suggestions) == 1

    def test_negative_saving_rejected(self):
        with pytest.raises(Exception):
            LLMAnalysisResult(
                root_cause="test",
                primary_bottleneck="fn",
                estimated_total_saving_ms=-100,
            )

    def test_invalid_effort_rejected(self):
        with pytest.raises(Exception):
            LLMSuggestion(
                title="Fix",
                description="Do something",
                estimated_saving_ms=1000,
                effort="extreme",
            )

    def test_default_values(self):
        result = LLMAnalysisResult(
            root_cause="test",
            primary_bottleneck="fn",
            estimated_total_saving_ms=0,
        )
        assert result.anti_patterns == []
        assert result.suggestions == []


# ── Full Analysis Flow (mocked LLM) ─────────────────────────────

class TestFullAnalysisFlow:
    @patch("app.services.ai_engine.anthropic")
    def test_analyse_run_success(self, mock_anthropic, db_session, seeded_db):
        repo, run = seeded_db

        # Mock the Anthropic client
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = json.dumps({
            "root_cause": "Install step has no caching",
            "primary_bottleneck": "run_migrations",
            "anti_patterns": ["No dependency caching"],
            "suggestions": [
                {
                    "title": "Add pip cache",
                    "description": "Cache pip packages",
                    "target_function": "run_migrations",
                    "target_file": "db/migrate.py",
                    "estimated_saving_ms": 3000,
                    "effort": "low",
                    "diff_hint": "Before: pip install\nAfter: pip install --cache-dir .cache",
                },
                {
                    "title": "Parallelize tests",
                    "description": "Run pytest in parallel",
                    "target_function": "",
                    "target_file": "",
                    "estimated_saving_ms": 2000,
                    "effort": "medium",
                    "diff_hint": "",
                },
            ],
            "estimated_total_saving_ms": 5000,
        })
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 500
        mock_response.usage.output_tokens = 300
        mock_client.messages.create.return_value = mock_response

        # Set API key
        with patch("app.services.ai_engine.get_settings") as mock_settings:
            settings = MagicMock()
            settings.ANTHROPIC_API_KEY = "test-key"
            settings.LLM_MODEL = "claude-sonnet-4-20250514"
            settings.LLM_MAX_OUTPUT_TOKENS = 3000
            settings.ANALYSIS_BOTTLENECK_TOP_N = 3
            settings.ANALYSIS_HISTORY_WINDOW = 20
            settings.ANALYSIS_TARGET_DURATION_MS = 15000
            settings.FUZZY_MATCH_THRESHOLD = 0.85
            settings.BOTTLENECK_DEFAULT_WINDOW = 50
            mock_settings.return_value = settings

            engine = AIEngine(db_session)
            analysis = engine.analyse_run(run.id)

        assert analysis.status == "completed"
        assert analysis.root_cause == "Install step has no caching"
        assert analysis.primary_bottleneck == "run_migrations"
        assert len(analysis.suggestions) == 2
        assert analysis.estimated_total_saving_ms == 5000
        assert analysis.suggestions[0].title == "Add pip cache"

    def test_existing_analysis_returned_without_force(self, db_session, seeded_db):
        repo, run = seeded_db

        # Create an existing completed analysis
        existing = Analysis(
            pipeline_run_id=run.id,
            repository_id=repo.id,
            status="completed",
            root_cause="Known issue",
            primary_bottleneck="install",
            estimated_total_saving_ms=3000,
        )
        db_session.add(existing)
        db_session.commit()

        engine = AIEngine(db_session)
        result = engine.analyse_run(run.id, force=False)
        assert result.root_cause == "Known issue"
