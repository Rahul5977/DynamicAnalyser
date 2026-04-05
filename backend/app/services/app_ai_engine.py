"""
app_ai_engine.py
----------------
AI analysis engine for application log sessions.

Mirrors the CI/CD AIEngine but targets runtime function-call bottlenecks
instead of pipeline steps.  Creates the same Analysis + AnalysisSuggestion
ORM rows, so all existing feedback routes work unchanged.
"""

from __future__ import annotations

import datetime
import json
from collections import defaultdict

import anthropic
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.logging import logger
from app.models.database import Analysis, AnalysisSuggestion, AppFunctionCall, AppLogSession


# ── LLM response schema ────────────────────────────────────────────────────────

class AppLLMSuggestion(BaseModel):
    title:                str
    description:          str
    target_function:      str = ""
    target_file:          str = ""
    estimated_saving_ms:  int = Field(ge=0)
    effort:               str = Field(pattern=r"^(low|medium|high)$")
    diff_hint:            str = ""
    anti_pattern:         str = ""   # must be one of the names listed in anti_patterns


class AppLLMResult(BaseModel):
    root_cause:                 str
    primary_bottleneck:         str
    anti_patterns:              list[str] = []
    suggestions:                list[AppLLMSuggestion] = []
    estimated_total_saving_ms:  int = Field(ge=0)


# ── System prompt & anti-patterns ─────────────────────────────────────────────

_APP_ANTI_PATTERNS = """
## Runtime Anti-Patterns to Check For

1. **Busy-wait loop**: while(condition) { check(); } with no sleep/yield.
   Typical saving: 5,000–15,000ms. Fix: condition variable or event.wait().

2. **N+1 function calls**: same sub-function called in a loop, each doing I/O.
   Typical saving: 2,000–10,000ms. Fix: batch the calls outside the loop.

3. **Synchronous blocking I/O in hot path**: read()/recv() without timeout or async.
   Typical saving: 3,000–12,000ms. Fix: async I/O or non-blocking with select().

4. **Unbounded data accumulation**: appending to list/array without size limit.
   Typical saving: 1,000–8,000ms. Fix: use a ring buffer or streaming approach.

5. **Repeated recomputation**: same expensive value recalculated every call.
   Typical saving: 1,000–5,000ms. Fix: memoize / cache the result.

6. **Lock contention**: mutex held across a slow I/O or DB operation.
   Typical saving: 1,000–6,000ms. Fix: narrow the critical section.

7. **String concatenation in loop**: building large strings with += in a loop.
   Typical saving: 500–3,000ms. Fix: use join() or a StringBuilder.

8. **Missing connection pooling**: new DB/HTTP connection opened per request.
   Typical saving: 500–5,000ms. Fix: use a connection pool.

9. **Excessive serialisation/deserialisation**: JSON parsing in the hot path.
   Typical saving: 200–2,000ms. Fix: cache parsed result or use a binary format.

10. **Deep recursion without memoisation**: recursive traversal of large graphs.
    Typical saving: 1,000–10,000ms. Fix: iterative + visited-set or DP table.
"""

_APP_SYSTEM_PROMPT = (
    "You are an expert performance engineer analysing runtime application logs. "
    "You will be given: function names with timing data extracted from log files, "
    "and optionally the source code and call chain. "
    "Your job: identify real bottlenecks based ONLY on the evidence in the data, "
    "explain why they are slow, and suggest concrete improvements. "
    "IMPORTANT RULES to avoid hallucination and repetition:\n"
    "  - Only name functions that appear in the data provided.\n"
    "  - Do NOT fabricate file paths, line numbers, or code you have not been shown.\n"
    "  - If no source code is provided, keep diff_hint as pseudocode / high-level description.\n"
    "  - Distinguish periodic/scheduled functions (consistent avg interval) from truly slow functions.\n"
    "  - estimated_saving_ms must be ≤ the function's max_ms shown in the data.\n"
    "  - Each suggestion MUST target a DIFFERENT function and address a DIFFERENT anti-pattern.\n"
    "  - Do NOT repeat the same anti-pattern name across multiple suggestions.\n"
    "  - Do NOT give the same advice twice with different wording.\n"
    "Respond in JSON matching the schema provided.\n"
    + _APP_ANTI_PATTERNS
)

_RESPONSE_SCHEMA = """{
  "root_cause": "one paragraph",
  "primary_bottleneck": "function name",
  "anti_patterns": ["list of distinct pattern names — each name used ONCE"],
  "suggestions": [
    {
      "title": "short fix title",
      "description": "what to do and why — unique, specific to this function",
      "target_function": "function name from the data",
      "target_file": "relative file path or empty string",
      "estimated_saving_ms": 1500,
      "effort": "low|medium|high",
      "diff_hint": "before/after pseudocode (no real file paths unless provided)",
      "anti_pattern": "exact name from anti_patterns list — each suggestion MUST use a DIFFERENT name"
    }
  ],
  "estimated_total_saving_ms": 5000
}"""


# ── Engine ─────────────────────────────────────────────────────────────────────

class AppAIEngine:
    """Creates Analysis + AnalysisSuggestion records for an AppLogSession."""

    def __init__(self, db: Session):
        self.db = db
        self._settings = get_settings()

    def analyse_session(
        self,
        session_id: int,
        force: bool = False,
        target_functions: list[str] | None = None,
    ) -> Analysis:
        """
        Run AI analysis for an app log session.
        Returns the persisted Analysis record (same ORM model as CI/CD analyses).
        """
        session: AppLogSession = self.db.get(AppLogSession, session_id)
        if not session:
            raise ValueError(f"AppLogSession {session_id} not found")
        if session.status != "completed":
            raise ValueError(
                f"Session {session_id} not completed (status={session.status})"
            )

        # Return existing analysis unless force=True
        if not force:
            existing = self._get_latest(session_id)
            if existing:
                return existing

        # Create pending Analysis record
        analysis = Analysis(
            app_log_session_id=session_id,
            pipeline_run_id=None,
            repository_id=None,
            status="running",
            llm_model=self._settings.LLM_MODEL,
        )
        self.db.add(analysis)
        self.db.commit()
        self.db.refresh(analysis)

        try:
            prompt = self._build_prompt(session, target_functions=target_functions)
            result, raw, ptok, ctok = self._call_llm(prompt)

            suggestions = [
                AnalysisSuggestion(
                    analysis_id=analysis.id,
                    rank=i + 1,
                    title=s.title,
                    description=s.description,
                    target_function=s.target_function or None,
                    target_file=s.target_file or None,
                    estimated_saving_ms=s.estimated_saving_ms,
                    effort=s.effort,
                    diff_hint=s.diff_hint or None,
                    # Use AI-provided anti_pattern directly; fall back to keyword match only if missing
                    anti_pattern=(
                        s.anti_pattern.strip() if s.anti_pattern.strip()
                        else self._match_anti_pattern(s.title, result.anti_patterns)
                    ),
                )
                for i, s in enumerate(result.suggestions)
            ]

            analysis.status = "completed"
            analysis.root_cause = result.root_cause
            analysis.primary_bottleneck = result.primary_bottleneck
            analysis.anti_patterns_json = json.dumps(result.anti_patterns)
            analysis.estimated_total_saving_ms = result.estimated_total_saving_ms
            analysis.raw_llm_response = raw
            analysis.llm_model = self._settings.LLM_MODEL
            analysis.llm_prompt_tokens = ptok
            analysis.llm_completion_tokens = ctok
            analysis.completed_at = datetime.datetime.utcnow()

            self.db.add_all(suggestions)
            self.db.commit()
            self.db.refresh(analysis)
            return analysis

        except Exception as e:
            analysis.status = "failed"
            analysis.error_message = str(e)
            self.db.commit()
            logger.exception("AppAIEngine: analysis failed for session %d", session_id)
            raise

    # ── Context building ───────────────────────────────────────────────────────

    def _build_prompt(
        self,
        session: AppLogSession,
        target_functions: list[str] | None = None,
    ) -> str:
        query = (
            self.db.query(AppFunctionCall)
            .filter(AppFunctionCall.session_id == session.id)
        )
        if target_functions:
            query = query.filter(AppFunctionCall.function_name.in_(target_functions))
        calls = (
            query
            .order_by(AppFunctionCall.duration_ms.desc())
            .limit(50)
            .all()
        )

        # Per-function aggregates
        agg: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_ms": 0, "max_ms": 0})
        for c in calls:
            a = agg[c.function_name]
            a["count"] += 1
            a["total_ms"] += c.duration_ms
            a["max_ms"] = max(a["max_ms"], c.duration_ms)

        top = sorted(agg.items(), key=lambda x: x[1]["total_ms"], reverse=True)[:10]
        total_ms = session.total_duration_ms or 1

        lines = [
            f"## Application: {session.app_name}",
            f"Log format: {session.log_format}",
            f"Recorded {session.total_calls} function-call timing entries.",
            *(
                [
                    f"Analysis scoped to {len(target_functions)} selected function(s): "
                    + ", ".join(target_functions),
                ]
                if target_functions else []
            ),
            "",
            "**Important:** Timings come from two sources:",
            "  1. Explicit duration messages in the log (e.g. 'completed in 5787 ms') — "
            "these are actual execution times.",
            "  2. Inter-call intervals — delta between consecutive log entries for the same "
            "function. These represent HOW OFTEN the function is invoked, NOT how long it "
            "runs. For example avg=5000ms for sendHeartBeat means it is called every 5s, "
            "not that it takes 5s to execute.",
            "Focus your analysis on functions with HIGH inter-call intervals (bottlenecks "
            "holding up the system) or explicit long durations.",
            "",
            "## Functions ranked by cumulative recorded time:",
        ]
        for rank, (fn, stats) in enumerate(top, 1):
            avg = stats["total_ms"] // max(stats["count"], 1)
            pct = stats["total_ms"] / total_ms * 100
            lines.append(
                f"{rank}. {fn}  calls={stats['count']}  "
                f"total={stats['total_ms']}ms ({pct:.1f}%)  "
                f"avg={avg}ms  max={stats['max_ms']}ms"
            )

        # Sample log excerpts + source code for top 3
        top3 = [fn for fn, _ in top[:3]]
        for fn in top3:
            sample_call = next(
                (c for c in calls if c.function_name == fn and c.log_excerpt), None
            )
            if sample_call:
                lines += ["", f"### Log excerpt for '{fn}':", sample_call.log_excerpt[:500]]
            if sample_call and sample_call.source_file:
                src = self._fetch_source(
                    session, sample_call.source_file, sample_call.source_line
                )
                if src:
                    lines += ["", f"### Source code ({sample_call.source_file}):", "```", src, "```"]
            if sample_call and sample_call.call_chain_json:
                try:
                    chain = json.loads(sample_call.call_chain_json)
                    if chain:
                        chain_str = " → ".join(
                            f"{e['function_name']} ({e['file_path']}:{e['line_number']})"
                            for e in chain
                        )
                        lines += ["", f"Call chain for '{fn}':", chain_str]
                except (json.JSONDecodeError, KeyError):
                    pass

        lines += [
            "",
            "## Respond with JSON matching this exact schema:",
            _RESPONSE_SCHEMA,
        ]
        return "\n".join(lines)

    def _fetch_source(
        self, session: AppLogSession, file_path: str, line_number: int | None
    ) -> str | None:
        """Attempt to fetch source code from GitHub if source_repo is a GitHub URL."""
        if not session.source_repo or not file_path:
            return None
        from app.services.app_trace_correlator import _parse_github_url
        repo_name = _parse_github_url(session.source_repo)
        if not repo_name:
            return None
        try:
            from app.services.github_client import GitHubClient
            gh = GitHubClient()
            content = gh.get_file_contents(repo_name, file_path)
            all_lines = content.split("\n")
            start = max(0, (line_number or 1) - 1)
            return "\n".join(all_lines[start: start + 40])
        except Exception as e:
            logger.debug("Could not fetch source for %s: %s", file_path, e)
            return None

    # ── LLM call ──────────────────────────────────────────────────────────────

    def _call_llm(
        self, prompt: str
    ) -> tuple[AppLLMResult, str, int, int]:
        settings = self._settings
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        try:
            response = client.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                system=_APP_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as e:
            raise RuntimeError(f"Anthropic auth failed: {e}") from e
        except anthropic.APIError as e:
            raise RuntimeError(f"Anthropic API error: {e}") from e

        raw = response.content[0].text
        ptok = response.usage.input_tokens
        ctok = response.usage.output_tokens

        parsed = self._parse_response(raw)
        if parsed is None:
            parsed = self._retry(client, settings, raw)
        if parsed is None:
            raise RuntimeError(f"Failed to parse LLM response: {raw[:300]}")
        return parsed, raw, ptok, ctok

    def _parse_response(self, raw: str) -> AppLLMResult | None:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            return AppLLMResult(**json.loads(text))
        except (json.JSONDecodeError, ValidationError):
            pass
        # Try extracting JSON object
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            try:
                return AppLLMResult(**json.loads(text[s:e+1]))
            except (json.JSONDecodeError, ValidationError):
                pass
        return None

    def _retry(self, client, settings, bad: str) -> AppLLMResult | None:
        try:
            r = client.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                system=_APP_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON. "
                        "Respond ONLY with valid JSON matching the schema. "
                        f"Previous response started: {bad[:300]}"
                    ),
                }],
            )
            return self._parse_response(r.content[0].text)
        except Exception:
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_latest(self, session_id: int) -> Analysis | None:
        return (
            self.db.query(Analysis)
            .filter(Analysis.app_log_session_id == session_id)
            .order_by(Analysis.created_at.desc())
            .first()
        )

    @staticmethod
    def _match_anti_pattern(title: str, patterns: list[str]) -> str | None:
        tl = title.lower()
        for p in patterns:
            words = [w for w in p.lower().split() if len(w) > 3]
            if any(w in tl for w in words):
                return p
        return patterns[0] if patterns else None
