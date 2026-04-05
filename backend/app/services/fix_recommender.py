"""Fix recommender: enriches AI suggestions with diffs and confidence scores."""

import difflib
import json

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.db.repository import AnalysisRepository, CodeIndexRepository
from app.models.database import Analysis, AnalysisFeedback, AnalysisSuggestion, IndexedFunction


class FixRecommender:
    """Enriches analysis suggestions with real diffs and confidence scores."""

    def __init__(self, db: Session):
        self.db = db

    def enrich_analysis(self, analysis: Analysis) -> Analysis:
        """Enrich all suggestions in an analysis with diffs and confidence."""
        if not analysis.suggestions:
            return analysis

        for suggestion in analysis.suggestions:
            self._enrich_suggestion(suggestion, analysis)

        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to persist enriched suggestions: %s", e)

        return analysis

    def _enrich_suggestion(
        self, suggestion: AnalysisSuggestion, analysis: Analysis
    ) -> None:
        """Enrich a single suggestion with diff and confidence."""
        # 1. Generate enriched diff from diff_hint
        if suggestion.diff_hint and suggestion.target_file:
            enriched = self._generate_unified_diff(
                suggestion.target_file,
                suggestion.target_function,
                suggestion.diff_hint,
            )
            if enriched:
                suggestion.enriched_diff = enriched

        # 2. Compute confidence score
        suggestion.confidence_score = self._compute_confidence(
            suggestion, analysis
        )

    def _generate_unified_diff(
        self, file_path: str, function_name: str | None, diff_hint: str
    ) -> str | None:
        """Convert a before/after diff_hint into a unified diff string."""
        if not diff_hint:
            return None

        # Parse "before/after" style hints
        before_lines, after_lines = self._parse_diff_hint(diff_hint)
        if not before_lines and not after_lines:
            return None

        from_file = f"a/{file_path}"
        to_file = f"b/{file_path}"

        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=from_file,
            tofile=to_file,
            lineterm="",
        )
        result = "\n".join(diff)
        return result if result else None

    @staticmethod
    def _parse_diff_hint(diff_hint: str) -> tuple[list[str], list[str]]:
        """Parse a diff_hint into before and after line lists.

        Handles formats like:
        - Git diff format: lines prefixed with '-' (before) and '+' (after)
        - "Before: X\\nAfter: Y"
        - Multi-line blocks separated by arrows or markers
        """
        hint = diff_hint.strip()
        before: list[str] = []
        after: list[str] = []

        # Try git diff format: lines starting with '-' or '+' (but not '---'/'+++' headers)
        lines = hint.split("\n")
        diff_lines = [l for l in lines if l.startswith(("+", "-")) and not l.startswith(("---", "+++"))]
        if diff_lines and len(diff_lines) == len([l for l in lines if l.strip()]):
            for line in lines:
                stripped = line.rstrip()
                if stripped.startswith("-") and not stripped.startswith("---"):
                    before.append(stripped[1:].lstrip())
                elif stripped.startswith("+") and not stripped.startswith("+++"):
                    after.append(stripped[1:].lstrip())
            if before or after:
                return before, after

        # Try "Before:" / "After:" format
        hint_lower = hint.lower()
        before_idx = hint_lower.find("before:")
        after_idx = hint_lower.find("after:")

        if before_idx >= 0 and after_idx > before_idx:
            before_text = hint[before_idx + 7:after_idx].strip()
            after_text = hint[after_idx + 6:].strip()
            before = [l for l in before_text.split("\n") if l.strip()]
            after = [l for l in after_text.split("\n") if l.strip()]
            return before, after

        # Try "→" or "->" separator
        for sep in ["→", "->", "=>"]:
            if sep in hint:
                parts = hint.split(sep, 1)
                before = [l.strip() for l in parts[0].strip().split("\n") if l.strip()]
                after = [l.strip() for l in parts[1].strip().split("\n") if l.strip()]
                return before, after

        # Fallback: treat entire hint as "after" (new code to add)
        after = [l for l in hint.split("\n") if l.strip()]
        return before, after

    def _compute_confidence(
        self, suggestion: AnalysisSuggestion, analysis: Analysis
    ) -> float:
        """Compute confidence score for a suggestion.

        Factors:
        - Anti-pattern recurrence: if seen 3+ times in past analyses → high confidence
        - Target function exists in code index → higher confidence
        - Estimated saving is reasonable → higher confidence
        """
        score = 0.5  # Base confidence

        # Factor 1: Anti-pattern recurrence
        if suggestion.anti_pattern and analysis.repository_id:
            analysis_store = AnalysisRepository(self.db)
            count = analysis_store.count_past_anti_pattern(
                analysis.repository_id, suggestion.anti_pattern
            )
            if count >= 3:
                score += 0.3
            elif count >= 1:
                score += 0.15

        # Factor 2: Target function exists in code index
        if suggestion.target_function and analysis.repository_id:
            idx_store = CodeIndexRepository(self.db)
            code_idx = idx_store.get_latest_for_repo(analysis.repository_id)
            if code_idx:
                func = (
                    self.db.query(IndexedFunction)
                    .filter(
                        IndexedFunction.code_index_id == code_idx.id,
                        IndexedFunction.function_name == suggestion.target_function,
                    )
                    .first()
                )
                if func:
                    score += 0.1

        # Factor 3: Reasonable saving estimate (500ms–300s covers typical CI savings)
        if 500 <= suggestion.estimated_saving_ms <= 300000:
            score += 0.1

        # Factor 4: Developer feedback history for this anti-pattern on this repo
        if suggestion.anti_pattern and analysis.repository_id:
            feedback_rows = (
                self.db.query(
                    AnalysisFeedback.verdict,
                )
                .join(AnalysisSuggestion, AnalysisFeedback.suggestion_id == AnalysisSuggestion.id)
                .join(Analysis, AnalysisFeedback.analysis_id == Analysis.id)
                .filter(
                    Analysis.repository_id == analysis.repository_id,
                    AnalysisSuggestion.anti_pattern == suggestion.anti_pattern,
                )
                .all()
            )
            verdicts = [r.verdict for r in feedback_rows]
            accepted_count = verdicts.count("accepted")
            rejected_count = verdicts.count("rejected")
            # Boost if this anti-pattern has been accepted before for this repo
            if accepted_count > 0:
                score += 0.15
            # Penalise if it has been rejected (only if no countervailing accepts)
            if rejected_count > 0 and accepted_count == 0:
                score -= 0.2

        return min(max(round(score, 2), 0.0), 1.0)

    def get_repo_insights(self, repo_id: int) -> dict:
        """Aggregate anti-pattern insights across all analyses for a repo."""
        analysis_store = AnalysisRepository(self.db)
        analyses = analysis_store.get_all_for_repo(repo_id)

        if not analyses:
            return {
                "total_analyses": 0,
                "anti_patterns": [],
                "most_common_bottleneck": None,
                "avg_total_saving_ms": 0.0,
            }

        # Aggregate anti-patterns
        pattern_data: dict[str, dict] = {}
        bottleneck_counts: dict[str, int] = {}
        total_saving = 0
        valid_count = 0

        for a in analyses:
            # Count bottlenecks
            if a.primary_bottleneck:
                bottleneck_counts[a.primary_bottleneck] = (
                    bottleneck_counts.get(a.primary_bottleneck, 0) + 1
                )

            # Sum savings
            if a.estimated_total_saving_ms:
                total_saving += a.estimated_total_saving_ms
                valid_count += 1

            # Aggregate anti-patterns from suggestions
            for s in a.suggestions:
                if s.anti_pattern:
                    if s.anti_pattern not in pattern_data:
                        pattern_data[s.anti_pattern] = {
                            "count": 0,
                            "total_saving": 0,
                            "functions": set(),
                        }
                    pd = pattern_data[s.anti_pattern]
                    pd["count"] += 1
                    pd["total_saving"] += s.estimated_saving_ms
                    if s.target_function:
                        pd["functions"].add(s.target_function)

        # Build response
        anti_patterns = []
        for pattern_name, pd in sorted(
            pattern_data.items(), key=lambda x: x[1]["count"], reverse=True
        ):
            anti_patterns.append({
                "anti_pattern": pattern_name,
                "occurrence_count": pd["count"],
                "avg_estimated_saving_ms": (
                    round(pd["total_saving"] / pd["count"], 1) if pd["count"] else 0.0
                ),
                "affected_functions": sorted(pd["functions"]),
            })

        most_common = (
            max(bottleneck_counts, key=bottleneck_counts.get)
            if bottleneck_counts else None
        )

        return {
            "total_analyses": len(analyses),
            "anti_patterns": anti_patterns,
            "most_common_bottleneck": most_common,
            "avg_total_saving_ms": (
                round(total_saving / valid_count, 1) if valid_count else 0.0
            ),
        }
