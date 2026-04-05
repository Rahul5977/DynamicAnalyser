"""
Tests for the feedback loop enhancement:
  - AnalysisRepository.get_feedback_summary()
  - _build_user_prompt() feedback section rendering
  - FixRecommender._compute_confidence() feedback factor
"""

import json
from datetime import datetime

import pytest

from app.db.repository import AnalysisRepository
from app.models.database import (
    Analysis,
    AnalysisFeedback,
    AnalysisSuggestion,
    TrackedRepository,
)
from app.services.ai_engine import AnalysisContext, BottleneckContext, _build_user_prompt
from app.services.fix_recommender import FixRecommender


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def repo(db_session):
    r = TrackedRepository(full_name="owner/repo", owner="owner", name="repo")
    db_session.add(r)
    db_session.commit()
    db_session.refresh(r)
    return r


def _make_analysis(db_session, repo_id):
    a = Analysis(
        pipeline_run_id=None,
        repository_id=repo_id,
        status="completed",
        created_at=datetime.utcnow(),
    )
    db_session.add(a)
    db_session.commit()
    db_session.refresh(a)
    return a


def _make_suggestion(db_session, analysis_id, title, anti_pattern, saving_ms=1000):
    s = AnalysisSuggestion(
        analysis_id=analysis_id,
        rank=1,
        title=title,
        description="desc",
        anti_pattern=anti_pattern,
        estimated_saving_ms=saving_ms,
        effort="low",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def _make_feedback(db_session, analysis_id, suggestion_id, verdict, comment=""):
    f = AnalysisFeedback(
        analysis_id=analysis_id,
        suggestion_id=suggestion_id,
        verdict=verdict,
        comment=comment,
        created_at=datetime.utcnow(),
    )
    db_session.add(f)
    db_session.commit()
    db_session.refresh(f)
    return f


# ── get_feedback_summary() tests ──────────────────────────────────────────────

class TestGetFeedbackSummary:
    def test_returns_empty_list_when_no_feedback(self, db_session, repo):
        store = AnalysisRepository(db_session)
        result = store.get_feedback_summary(repo.id)
        assert result == []

    def test_returns_feedback_with_correct_keys(self, db_session, repo):
        analysis = _make_analysis(db_session, repo.id)
        suggestion = _make_suggestion(db_session, analysis.id, "Cache deps", "No dependency caching", 4000)
        _make_feedback(db_session, analysis.id, suggestion.id, "accepted", "Worked perfectly")

        store = AnalysisRepository(db_session)
        result = store.get_feedback_summary(repo.id)

        assert len(result) == 1
        entry = result[0]
        assert entry["verdict"] == "accepted"
        assert entry["suggestion_title"] == "Cache deps"
        assert entry["anti_pattern"] == "No dependency caching"
        assert entry["estimated_saving_ms"] == 4000
        assert entry["comment"] == "Worked perfectly"

    def test_multiple_feedback_ordered_newest_first(self, db_session, repo):
        analysis = _make_analysis(db_session, repo.id)
        s1 = _make_suggestion(db_session, analysis.id, "Fix A", "Pattern A")
        s2 = _make_suggestion(db_session, analysis.id, "Fix B", "Pattern B")
        _make_feedback(db_session, analysis.id, s1.id, "accepted")
        _make_feedback(db_session, analysis.id, s2.id, "rejected")

        store = AnalysisRepository(db_session)
        result = store.get_feedback_summary(repo.id)
        assert len(result) == 2
        # Most recent feedback (s2) should come first
        assert result[0]["verdict"] == "rejected"
        assert result[1]["verdict"] == "accepted"

    def test_limit_is_respected(self, db_session, repo):
        analysis = _make_analysis(db_session, repo.id)
        for i in range(10):
            s = _make_suggestion(db_session, analysis.id, f"Fix {i}", f"Pattern {i}")
            _make_feedback(db_session, analysis.id, s.id, "accepted")

        store = AnalysisRepository(db_session)
        result = store.get_feedback_summary(repo.id, limit=5)
        assert len(result) == 5

    def test_only_returns_feedback_for_given_repo(self, db_session, repo):
        other_repo = TrackedRepository(full_name="other/repo", owner="other", name="repo")
        db_session.add(other_repo)
        db_session.commit()
        db_session.refresh(other_repo)

        # Feedback for target repo
        analysis = _make_analysis(db_session, repo.id)
        s = _make_suggestion(db_session, analysis.id, "Fix X", "Pattern X")
        _make_feedback(db_session, analysis.id, s.id, "accepted")

        # Feedback for other repo — should be excluded
        other_analysis = _make_analysis(db_session, other_repo.id)
        os_ = _make_suggestion(db_session, other_analysis.id, "Fix Y", "Pattern Y")
        _make_feedback(db_session, other_analysis.id, os_.id, "rejected")

        store = AnalysisRepository(db_session)
        result = store.get_feedback_summary(repo.id)
        assert len(result) == 1
        assert result[0]["suggestion_title"] == "Fix X"

    def test_empty_comment_returns_empty_string(self, db_session, repo):
        analysis = _make_analysis(db_session, repo.id)
        s = _make_suggestion(db_session, analysis.id, "Fix Z", "Pattern Z")
        _make_feedback(db_session, analysis.id, s.id, "partial", comment=None)

        store = AnalysisRepository(db_session)
        result = store.get_feedback_summary(repo.id)
        assert result[0]["comment"] == ""


# ── _build_user_prompt() feedback section tests ───────────────────────────────

def _make_ctx(feedback_history=None):
    return AnalysisContext(
        repo_full_name="owner/repo",
        commit_sha="abc1234",
        total_duration_ms=30000,
        target_duration_ms=20000,
        status="completed",
        conclusion="success",
        bottlenecks=[],
        feedback_history=feedback_history or [],
    )


class TestBuildUserPromptFeedback:
    def test_no_feedback_section_when_empty(self):
        prompt = _build_user_prompt(_make_ctx(feedback_history=[]))
        assert "Developer Feedback" not in prompt

    def test_feedback_section_present_when_history_exists(self):
        history = [
            {"verdict": "accepted", "suggestion_title": "Add cache",
             "anti_pattern": "No dependency caching", "estimated_saving_ms": 5000, "comment": ""},
        ]
        prompt = _build_user_prompt(_make_ctx(feedback_history=history))
        assert "Developer Feedback on Previous Suggestions" in prompt

    def test_accepted_feedback_in_accepted_section(self):
        history = [
            {"verdict": "accepted", "suggestion_title": "Add cache",
             "anti_pattern": "No dependency caching", "estimated_saving_ms": 5000, "comment": "Great fix"},
        ]
        prompt = _build_user_prompt(_make_ctx(feedback_history=history))
        assert "Accepted" in prompt
        assert "Add cache" in prompt
        assert "No dependency caching" in prompt
        assert "Great fix" in prompt

    def test_rejected_feedback_in_rejected_section(self):
        history = [
            {"verdict": "rejected", "suggestion_title": "Parallel tests",
             "anti_pattern": "Sequential test execution", "estimated_saving_ms": 3000, "comment": "Too risky"},
        ]
        prompt = _build_user_prompt(_make_ctx(feedback_history=history))
        assert "Rejected" in prompt
        assert "Parallel tests" in prompt
        assert "Too risky" in prompt

    def test_partial_feedback_in_partial_section(self):
        history = [
            {"verdict": "partial", "suggestion_title": "Fix DB index",
             "anti_pattern": "Unindexed DB queries", "estimated_saving_ms": 2000, "comment": ""},
        ]
        prompt = _build_user_prompt(_make_ctx(feedback_history=history))
        assert "Partial" in prompt
        assert "Fix DB index" in prompt

    def test_mixed_verdicts_all_sections_present(self):
        history = [
            {"verdict": "accepted", "suggestion_title": "A", "anti_pattern": "P1",
             "estimated_saving_ms": 1000, "comment": ""},
            {"verdict": "rejected", "suggestion_title": "B", "anti_pattern": "P2",
             "estimated_saving_ms": 2000, "comment": ""},
            {"verdict": "partial", "suggestion_title": "C", "anti_pattern": "P3",
             "estimated_saving_ms": 3000, "comment": ""},
        ]
        prompt = _build_user_prompt(_make_ctx(feedback_history=history))
        assert "Accepted" in prompt
        assert "Rejected" in prompt
        assert "Partial" in prompt

    def test_feedback_section_appears_before_json_schema(self):
        history = [
            {"verdict": "accepted", "suggestion_title": "Cache deps",
             "anti_pattern": "No dependency caching", "estimated_saving_ms": 4000, "comment": ""},
        ]
        prompt = _build_user_prompt(_make_ctx(feedback_history=history))
        feedback_idx = prompt.index("Developer Feedback")
        schema_idx = prompt.index("Respond with JSON")
        assert feedback_idx < schema_idx


# ── FixRecommender feedback confidence factor tests ───────────────────────────

class TestComputeConfidenceFeedbackFactor:
    def test_accepted_feedback_boosts_confidence(self, db_session, repo):
        analysis = _make_analysis(db_session, repo.id)
        suggestion = _make_suggestion(
            db_session, analysis.id, "Cache npm deps",
            "No dependency caching", saving_ms=5000,
        )
        # Record an accepted feedback for this anti-pattern
        _make_feedback(db_session, analysis.id, suggestion.id, "accepted")

        recommender = FixRecommender(db_session)
        score = recommender._compute_confidence(suggestion, analysis)
        # Base(0.5) + recurrence_factor + code_index_missing(0) + saving(0.1) + accepted(+0.15)
        assert score >= 0.6

    def test_rejected_feedback_reduces_confidence(self, db_session, repo):
        analysis = _make_analysis(db_session, repo.id)
        suggestion = _make_suggestion(
            db_session, analysis.id, "Parallel tests",
            "Sequential test execution", saving_ms=3000,
        )
        _make_feedback(db_session, analysis.id, suggestion.id, "rejected")

        recommender = FixRecommender(db_session)
        score = recommender._compute_confidence(suggestion, analysis)
        # Base(0.5) + saving(0.1) - rejected(-0.2) = 0.4
        assert score <= 0.5

    def test_accepted_overrides_rejected_no_penalty(self, db_session, repo):
        """When a pattern has both accepted AND rejected feedback, penalty is suppressed."""
        analysis = _make_analysis(db_session, repo.id)
        s1 = _make_suggestion(db_session, analysis.id, "Fix A", "No dependency caching", 4000)
        s2 = _make_suggestion(db_session, analysis.id, "Fix B", "No dependency caching", 4000)
        _make_feedback(db_session, analysis.id, s1.id, "accepted")
        _make_feedback(db_session, analysis.id, s2.id, "rejected")

        recommender = FixRecommender(db_session)
        # Use s2 (the rejected suggestion) — but because accepted > 0, no penalty
        score = recommender._compute_confidence(s2, analysis)
        assert score >= 0.5

    def test_no_feedback_no_change(self, db_session, repo):
        analysis = _make_analysis(db_session, repo.id)
        suggestion = _make_suggestion(
            db_session, analysis.id, "Some fix", "Blocking I/O", saving_ms=1000,
        )
        recommender = FixRecommender(db_session)
        score = recommender._compute_confidence(suggestion, analysis)
        # Base(0.5) + saving(0.1) = 0.6 — no feedback adjustment
        assert score == pytest.approx(0.6, abs=0.05)

    def test_score_never_exceeds_1(self, db_session, repo):
        analysis = _make_analysis(db_session, repo.id)
        analysis.anti_patterns_json = json.dumps(["No dependency caching"] * 5)
        db_session.commit()

        suggestion = _make_suggestion(
            db_session, analysis.id, "Cache all", "No dependency caching", 5000,
        )
        for _ in range(5):
            _make_feedback(db_session, analysis.id, suggestion.id, "accepted")

        recommender = FixRecommender(db_session)
        score = recommender._compute_confidence(suggestion, analysis)
        assert score <= 1.0

    def test_score_never_below_zero(self, db_session, repo):
        analysis = _make_analysis(db_session, repo.id)
        suggestion = _make_suggestion(
            db_session, analysis.id, "Bad fix", "Some pattern", saving_ms=100,
        )
        for _ in range(5):
            _make_feedback(db_session, analysis.id, suggestion.id, "rejected")

        recommender = FixRecommender(db_session)
        score = recommender._compute_confidence(suggestion, analysis)
        assert score >= 0.0
