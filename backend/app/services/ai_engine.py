"""AI root cause engine: context assembly, LLM prompting, and response parsing."""

import json
import datetime
from dataclasses import dataclass, field

import anthropic
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import AnalysisError, LLMError, RunNotFoundError
from app.core.logging import logger
from app.db.repository import (
    AnalysisRepository,
    CodeIndexRepository,
    PipelineRunRepository,
    TrackedRepoRepository,
)
from app.models.database import Analysis, AnalysisSuggestion
from app.services.bottleneck_ranker import BottleneckRanker
from app.services.trace_correlator import TraceCorrelator


# ── LLM Response Schema (Pydantic for validation) ───────────────

class LLMSuggestion(BaseModel):
    title: str
    description: str
    target_function: str = ""
    target_file: str = ""
    estimated_saving_ms: int = Field(ge=0)
    effort: str = Field(pattern=r"^(low|medium|high)$")
    diff_hint: str = ""


class LLMAnalysisResult(BaseModel):
    root_cause: str
    primary_bottleneck: str
    anti_patterns: list[str] = []
    suggestions: list[LLMSuggestion] = []
    estimated_total_saving_ms: int = Field(ge=0)


# ── Context Assembly Dataclass ───────────────────────────────────

@dataclass
class BottleneckContext:
    step_name: str
    duration_ms: int
    p95_ms: int
    pct_of_total: float
    trend_direction: str
    source_function: str | None
    source_file: str | None
    source_line: int | None
    call_chain: str
    function_source_code: str | None
    language: str | None


@dataclass
class AnalysisContext:
    repo_full_name: str
    commit_sha: str
    total_duration_ms: int
    target_duration_ms: int
    status: str
    conclusion: str | None
    bottlenecks: list[BottleneckContext] = field(default_factory=list)


# ── Anti-Pattern Few-Shot Examples ───────────────────────────────

ANTI_PATTERN_EXAMPLES = """
## Known Anti-Patterns to Check For

1. **No dependency caching**: npm install / pip install runs in every CI run without cache key.
   Detection: step name contains "install" and duration > 3000ms. Fix: add cache: key to workflow YAML.
   Typical saving: 3000–8000ms.

2. **Sequential test execution**: Tests run single-threaded (e.g., pytest without -n, jest with --runInBand).
   Detection: test step duration scales linearly with test count. Fix: pytest -n auto or jest --workers.
   Typical saving: 2000–5000ms.

3. **Unindexed DB queries**: SELECT with WHERE on non-indexed column during migrations or tests.
   Detection: migration/DB step is disproportionately slow. Fix: add database index migration.
   Typical saving: 1000–4000ms.

4. **Blocking I/O in sync code**: time.sleep(), sync file reads, or sync HTTP calls in hot path.
   Detection: function contains sleep() or blocking I/O calls. Fix: convert to async/await or thread pool.
   Typical saving: 500–3000ms.

5. **Redundant installs**: Same package installed twice across different steps.
   Detection: multiple steps install overlapping dependencies. Fix: deduplicate requirements.
   Typical saving: 1000–3000ms.

6. **No build cache**: Full recompile every CI run, no layer caching in Docker builds.
   Detection: build step duration is constant regardless of change size. Fix: add build cache layer.
   Typical saving: 2000–6000ms.

7. **Large test fixtures**: Loading entire DB dump or heavy fixture data for each test.
   Detection: test setup phase dominates test duration. Fix: use factory_boy or transactions.
   Typical saving: 1000–5000ms.
"""


# ── Prompt Templates ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert performance engineer specialising in CI/CD pipelines.
You analyse execution logs, source code, and timing data to identify
bottlenecks and recommend specific code-level fixes. Always respond in
valid JSON matching the schema provided. Be specific — name exact
functions, line numbers, and anti-patterns.
""" + ANTI_PATTERN_EXAMPLES


def _build_user_prompt(ctx: AnalysisContext) -> str:
    lines = [
        "## Pipeline Run Summary",
        f"Repo: {ctx.repo_full_name}",
        f"Commit: {ctx.commit_sha[:8]}",
        f"Total duration: {ctx.total_duration_ms}ms  |  Target: {ctx.target_duration_ms}ms",
        f"Status: {ctx.status} ({ctx.conclusion or 'N/A'})",
        "",
        f"## Top {len(ctx.bottlenecks)} Slowest Steps (by p95 across last 20 runs)",
    ]

    for i, b in enumerate(ctx.bottlenecks, 1):
        lines.append(f"\n### Step {i}: {b.step_name}")
        lines.append(f"- Current duration: {b.duration_ms}ms")
        lines.append(f"- p95 across 20 runs: {b.p95_ms}ms")
        lines.append(f"- % of total pipeline: {b.pct_of_total * 100:.1f}%")
        lines.append(f"- Trend: {b.trend_direction}")
        if b.source_function:
            loc = f"{b.source_function} in {b.source_file or 'unknown'}:{b.source_line or '?'}"
            lines.append(f"- Source function: {loc}")
        if b.call_chain:
            lines.append(f"- Call chain: {b.call_chain}")
        if b.function_source_code:
            lang = b.language or "python"
            lines.append(f"\nSource code of {b.source_function}:")
            lines.append(f"```{lang}")
            lines.append(b.function_source_code)
            lines.append("```")

    lines.append("")
    lines.append("## Respond with JSON matching this exact schema:")
    lines.append("""{
  "root_cause": "string — one paragraph explanation",
  "primary_bottleneck": "function name",
  "anti_patterns": ["list of anti-pattern names found"],
  "suggestions": [
    {
      "title": "short fix title",
      "description": "what to do and why",
      "target_function": "function name",
      "target_file": "relative file path",
      "estimated_saving_ms": 1500,
      "effort": "low|medium|high",
      "diff_hint": "before/after pseudocode"
    }
  ],
  "estimated_total_saving_ms": 5000
}""")

    return "\n".join(lines)


# ── AI Engine ────────────────────────────────────────────────────

class AIEngine:
    """Orchestrates context assembly, LLM invocation, and result persistence."""

    def __init__(self, db: Session):
        self.db = db
        self._settings = get_settings()
        self._gh_client = None

    def analyse_run(self, run_id: int, force: bool = False) -> Analysis:
        """Run full AI analysis for a pipeline run.

        Returns the persisted Analysis record.
        """
        analysis_store = AnalysisRepository(self.db)

        # Check for existing analysis
        if not force:
            existing = analysis_store.get_latest_for_run(run_id)
            if existing:
                return existing

        # Load pipeline run
        run_store = PipelineRunRepository(self.db)
        run = run_store.get_by_id(run_id)
        repo_store = TrackedRepoRepository(self.db)
        repo = repo_store.get_by_id(run.repository_id)

        # Create pending analysis record
        analysis = Analysis(
            pipeline_run_id=run.id,
            repository_id=repo.id,
            status="running",
            llm_model=self._settings.LLM_MODEL,
        )
        analysis = analysis_store.create(analysis)

        try:
            # 1. Assemble context
            ctx = self._assemble_context(run, repo)

            # 2. Call LLM
            llm_result, raw_response, prompt_tokens, completion_tokens = (
                self._call_llm(ctx)
            )

            # 3. Build suggestion records
            suggestions = [
                AnalysisSuggestion(
                    rank=i + 1,
                    title=s.title,
                    description=s.description,
                    target_function=s.target_function or None,
                    target_file=s.target_file or None,
                    estimated_saving_ms=s.estimated_saving_ms,
                    effort=s.effort,
                    diff_hint=s.diff_hint or None,
                    anti_pattern=self._match_anti_pattern(s.title, llm_result.anti_patterns),
                )
                for i, s in enumerate(llm_result.suggestions)
            ]

            # 4. Persist completed analysis
            analysis_store.update_completed(
                analysis_id=analysis.id,
                root_cause=llm_result.root_cause,
                primary_bottleneck=llm_result.primary_bottleneck,
                anti_patterns_json=json.dumps(llm_result.anti_patterns),
                estimated_total_saving_ms=llm_result.estimated_total_saving_ms,
                raw_llm_response=raw_response,
                llm_model=self._settings.LLM_MODEL,
                llm_prompt_tokens=prompt_tokens,
                llm_completion_tokens=completion_tokens,
                completed_at=datetime.datetime.utcnow(),
                suggestions=suggestions,
            )

            # Reload to get full record with suggestions
            return analysis_store.get_by_id(analysis.id)

        except (AnalysisError, LLMError) as e:
            analysis_store.update_failed(analysis.id, str(e))
            raise
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            analysis_store.update_failed(analysis.id, error_msg)
            logger.exception("Analysis failed for run %d", run_id)
            raise AnalysisError(
                f"Analysis failed for run {run_id}", detail=error_msg
            ) from e

    def _assemble_context(self, run, repo) -> AnalysisContext:
        """Build the structured context for the LLM prompt."""
        settings = self._settings

        # Get bottleneck rankings
        ranker = BottleneckRanker(self.db)
        top_n = settings.ANALYSIS_BOTTLENECK_TOP_N
        window = settings.ANALYSIS_HISTORY_WINDOW
        entries, _ = ranker.rank_bottlenecks(repo.id, last_n=window, top_n=top_n)

        # Get trace correlation data
        correlator = TraceCorrelator(self.db)
        try:
            trace = correlator.correlate_run(run.id)
        except Exception as e:
            logger.warning("Trace correlation failed: %s", e)
            trace = None

        # Create GitHub client once for source fetching (avoids re-validating token per step)
        try:
            from app.services.github_client import GitHubClient
            self._gh_client = GitHubClient()
        except Exception:
            self._gh_client = None

        # Build step-level context
        bottleneck_contexts: list[BottleneckContext] = []
        for entry in entries:
            step_name = entry["step_name"]

            # Find the matching annotated step from the trace
            source_function = None
            source_file = None
            source_line = None
            call_chain_str = ""
            function_source = None
            language = None

            if trace:
                matched_step = next(
                    (s for s in trace.steps if s.step_name == step_name), None
                )
                if matched_step and matched_step.source_location:
                    loc = matched_step.source_location
                    source_function = loc.function_name
                    source_file = loc.file_path
                    source_line = loc.line_number
                    if matched_step.call_chain:
                        chain_parts = [
                            f"{c.function_name} ({c.file_path}:{c.line_number})"
                            for c in matched_step.call_chain
                        ]
                        call_chain_str = " → ".join(chain_parts)

                    # Try to fetch actual source code
                    function_source, language = self._fetch_function_source(
                        repo.full_name, run.head_sha, loc.file_path,
                        loc.line_number,
                        # Find end line from indexed functions
                        self._get_end_line(repo.id, loc.function_name),
                    )

            # Find the step's current duration from the run
            step_timing = next(
                (s for s in run.step_timings if s.step_name == step_name), None
            )
            current_duration = step_timing.duration_ms if step_timing else 0

            bottleneck_contexts.append(BottleneckContext(
                step_name=step_name,
                duration_ms=current_duration,
                p95_ms=entry["p95_ms"],
                pct_of_total=entry["pct_of_total"],
                trend_direction=entry["trend_direction"],
                source_function=source_function,
                source_file=source_file,
                source_line=source_line,
                call_chain=call_chain_str,
                function_source_code=function_source,
                language=language,
            ))

        return AnalysisContext(
            repo_full_name=repo.full_name,
            commit_sha=run.head_sha or "unknown",
            total_duration_ms=run.total_duration_ms or 0,
            target_duration_ms=settings.ANALYSIS_TARGET_DURATION_MS,
            status=run.status,
            conclusion=run.conclusion,
            bottlenecks=bottleneck_contexts,
        )

    def _fetch_function_source(
        self, repo_full_name: str, commit_sha: str | None,
        file_path: str, start_line: int, end_line: int | None,
    ) -> tuple[str | None, str | None]:
        """Fetch function source code from GitHub. Returns (source, language)."""
        if not commit_sha or not file_path:
            return None, None

        try:
            gh = self._gh_client
            if gh is None:
                return None, None
            content = gh.get_file_contents(repo_full_name, file_path, ref=commit_sha)

            lines = content.split("\n")
            end = end_line or min(start_line + 30, len(lines))
            start = max(0, start_line - 1)
            source = "\n".join(lines[start:end])

            # Determine language from extension
            ext = file_path.rsplit(".", 1)[-1] if "." in file_path else ""
            lang_map = {"py": "python", "js": "javascript", "ts": "typescript",
                        "tsx": "typescript", "java": "java", "go": "go"}
            language = lang_map.get(ext, ext)

            return source, language
        except Exception as e:
            logger.warning("Could not fetch source for %s: %s", file_path, e)
            return None, None

    def _get_end_line(self, repo_id: int, function_name: str) -> int | None:
        """Look up end_line_number for a function from the code index."""
        idx_store = CodeIndexRepository(self.db)
        code_idx = idx_store.get_latest_for_repo(repo_id)
        if not code_idx:
            return None
        from app.models.database import IndexedFunction
        func = (
            self.db.query(IndexedFunction)
            .filter(
                IndexedFunction.code_index_id == code_idx.id,
                IndexedFunction.function_name == function_name,
            )
            .first()
        )
        return func.end_line_number if func else None

    def _call_llm(
        self, ctx: AnalysisContext
    ) -> tuple[LLMAnalysisResult, str, int, int]:
        """Call the Anthropic API and parse the response.

        Returns (parsed_result, raw_response, prompt_tokens, completion_tokens).
        """
        settings = self._settings

        if not settings.ANTHROPIC_API_KEY:
            raise LLMError(
                "Anthropic API key not configured",
                detail="Set ANTHROPIC_API_KEY in your .env file",
            )

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        user_prompt = _build_user_prompt(ctx)

        try:
            response = client.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.AuthenticationError as e:
            raise LLMError("Anthropic authentication failed", detail=str(e)) from e
        except anthropic.RateLimitError as e:
            raise LLMError("Anthropic rate limit exceeded", detail=str(e)) from e
        except anthropic.APIError as e:
            raise LLMError(f"Anthropic API error: {e.message}", detail=str(e)) from e

        raw_text = response.content[0].text
        prompt_tokens = response.usage.input_tokens
        completion_tokens = response.usage.output_tokens

        # Parse JSON from response
        parsed = self._parse_llm_response(raw_text)
        if parsed is None:
            # Retry once with correction prompt
            parsed = self._retry_with_correction(client, settings, raw_text)

        if parsed is None:
            raise LLMError(
                "Failed to parse LLM response after retry",
                detail=f"Raw response: {raw_text[:500]}",
            )

        return parsed, raw_text, prompt_tokens, completion_tokens

    def _parse_llm_response(self, raw_text: str) -> LLMAnalysisResult | None:
        """Extract and validate JSON from LLM response text."""
        # Try to find JSON in the response
        text = raw_text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            json_lines = []
            started = False
            for line in lines:
                if not started and line.strip().startswith("```"):
                    started = True
                    continue
                if started and line.strip() == "```":
                    break
                if started:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        try:
            data = json.loads(text)
            return LLMAnalysisResult(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("First parse attempt failed: %s", e)

        # Try to extract JSON object from mixed text
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                data = json.loads(text[brace_start:brace_end + 1])
                return LLMAnalysisResult(**data)
            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning("JSON extraction failed: %s", e)

        return None

    def _retry_with_correction(
        self, client, settings, bad_response: str
    ) -> LLMAnalysisResult | None:
        """Send a correction prompt and try parsing again."""
        correction_prompt = (
            "Your previous response was not valid JSON. "
            "Please respond with ONLY valid JSON matching the schema I provided. "
            "No markdown, no explanations, just the JSON object.\n\n"
            f"Your previous response started with:\n{bad_response[:300]}"
        )
        try:
            response = client.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": correction_prompt}],
            )
            return self._parse_llm_response(response.content[0].text)
        except Exception as e:
            logger.warning("Retry with correction failed: %s", e)
            return None

    @staticmethod
    def _match_anti_pattern(
        suggestion_title: str, anti_patterns: list[str]
    ) -> str | None:
        """Try to match a suggestion to one of the detected anti-patterns."""
        title_lower = suggestion_title.lower()
        for pattern in anti_patterns:
            # Check if any significant word from the pattern appears in the title
            pattern_words = [w for w in pattern.lower().split() if len(w) > 3]
            if any(w in title_lower for w in pattern_words):
                return pattern
        return anti_patterns[0] if anti_patterns else None
