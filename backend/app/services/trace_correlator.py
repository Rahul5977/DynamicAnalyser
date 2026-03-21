"""Trace correlator: maps pipeline steps to source code locations."""

import difflib
import json
import re

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import CorrelationError, RunNotFoundError
from app.core.logging import logger
from app.db.repository import (
    CodeIndexRepository,
    PipelineRunRepository,
    TrackedRepoRepository,
)
from app.models.database import CodeIndex, IndexedFunction, IndexedLogCall
from app.models.schemas import (
    AnnotatedStep,
    AnnotatedTrace,
    CallChainEntry,
    SourceLocation,
)
from app.services.ast_parser import CodeIndexData, SourceLocation as ASTSourceLocation


# Regex to strip GitHub Actions timestamps from log lines
TIMESTAMP_STRIP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s*")
ANNOTATION_STRIP_RE = re.compile(r"##\[(group|endgroup|error|warning)\]\s*")


def _clean_log_line(line: str) -> str:
    """Strip timestamps and annotations from a log line."""
    line = TIMESTAMP_STRIP_RE.sub("", line)
    line = ANNOTATION_STRIP_RE.sub("", line)
    return line.strip()


class TraceCorrelator:
    """Correlates pipeline steps with source code locations."""

    def __init__(self, db: Session):
        self.db = db
        self._settings = get_settings()

    def correlate_run(self, run_id: int) -> AnnotatedTrace:
        """Produce an AnnotatedTrace for a pipeline run."""
        run_store = PipelineRunRepository(self.db)
        run = run_store.get_by_id(run_id)

        # Find the code index for this run's commit
        repo_store = TrackedRepoRepository(self.db)
        repo = repo_store.get_by_id(run.repository_id)
        code_index_data = self._load_code_index(repo.id, run.head_sha)

        annotated_steps: list[AnnotatedStep] = []
        matched_count = 0

        # Sort steps by duration descending for the response
        sorted_steps = sorted(run.step_timings, key=lambda s: s.duration_ms, reverse=True)

        for step in sorted_steps:
            source_loc = None
            call_chain: list[CallChainEntry] = []
            confidence = None
            method = None

            if code_index_data and step.log_excerpt:
                source_loc, confidence, method = self._match_step(
                    step.log_excerpt, code_index_data
                )

                if source_loc:
                    # Build call chain
                    chain = code_index_data.get_callers(source_loc.function_name)
                    call_chain = [
                        CallChainEntry(
                            function_name=c.function_name,
                            file_path=c.file_path,
                            line_number=c.line_number,
                        )
                        for c in chain
                    ]
                    # Update DB
                    step.source_function = source_loc.function_name
                    matched_count += 1

            # Grep fallback if no match from log excerpt
            if not source_loc and code_index_data:
                source_loc, confidence, method = self._grep_fallback(
                    step.step_name, code_index_data
                )
                if source_loc:
                    step.source_function = source_loc.function_name
                    matched_count += 1

            pydantic_loc = None
            if source_loc:
                pydantic_loc = SourceLocation(
                    file_path=source_loc.file_path,
                    line_number=source_loc.line_number,
                    function_name=source_loc.function_name,
                    qualified_name=source_loc.qualified_name,
                )

            annotated_steps.append(AnnotatedStep(
                step_name=step.step_name,
                step_number=step.step_number,
                duration_ms=step.duration_ms,
                status=step.status,
                source_location=pydantic_loc,
                call_chain=call_chain,
                match_confidence=confidence,
                match_method=method,
            ))

        # Commit source_function updates
        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to update source_function: %s", e)

        total = len(sorted_steps)
        return AnnotatedTrace(
            run_id=run.id,
            github_run_id=run.github_run_id,
            workflow_name=run.workflow_name,
            total_steps=total,
            matched_steps=matched_count,
            match_rate=matched_count / total if total > 0 else 0.0,
            steps=annotated_steps,
        )

    def _load_code_index(
        self, repo_id: int, commit_sha: str | None
    ) -> CodeIndexData | None:
        """Load code index from DB and reconstruct in-memory representation."""
        idx_store = CodeIndexRepository(self.db)

        code_idx = None
        if commit_sha:
            code_idx = idx_store.get_by_repo_and_sha(repo_id, commit_sha)
        if not code_idx:
            code_idx = idx_store.get_latest_for_repo(repo_id)
        if not code_idx or code_idx.status != "completed":
            return None

        # Reconstruct in-memory CodeIndexData from DB
        idx_store.load_index_data(code_idx)

        functions_info = []
        for f in code_idx.functions:
            calls = json.loads(f.calls_json) if f.calls_json else []
            functions_info.append(type('FI', (), {
                'name': f.function_name,
                'qualified_name': f.qualified_name,
                'file_path': f.file_path,
                'line_number': f.line_number,
                'end_line_number': f.end_line_number or f.line_number,
                'calls': calls,
                'language': f.language,
            })())

        log_calls_info = []
        for lc in code_idx.log_calls:
            log_calls_info.append(type('LCI', (), {
                'log_string': lc.log_string,
                'file_path': lc.file_path,
                'line_number': lc.line_number,
                'function_name': lc.function_name,
                'log_level': lc.log_level,
                'language': lc.language,
            })())

        # Build graphs
        from app.services.ast_parser import CodeIndexer
        call_graph = CodeIndexer._build_call_graph(functions_info)
        reverse_graph = CodeIndexer._build_reverse_graph(call_graph)
        log_line_map = CodeIndexer._build_log_line_map(log_calls_info, functions_info)

        return CodeIndexData(
            repo_full_name="",
            commit_sha=code_idx.commit_sha,
            functions=functions_info,
            log_calls=log_calls_info,
            call_graph=call_graph,
            reverse_call_graph=reverse_graph,
            log_line_map=log_line_map,
        )

    def _match_step(
        self, log_excerpt: str, index: CodeIndexData
    ) -> tuple[ASTSourceLocation | None, float | None, str | None]:
        """Try exact then fuzzy matching of log excerpt against code index."""
        lines = log_excerpt.split("\n")
        cleaned_lines = [_clean_log_line(l) for l in lines if _clean_log_line(l)]

        # 1. Exact match
        for line in cleaned_lines:
            if line in index.log_line_map:
                return index.log_line_map[line], 1.0, "exact"

        # 2. Fuzzy match
        threshold = self._settings.FUZZY_MATCH_THRESHOLD
        best_match = None
        best_ratio = 0.0
        best_key = None

        all_keys = list(index.log_line_map.keys())
        for line in cleaned_lines:
            if not line or len(line) < 5:
                continue
            matches = difflib.get_close_matches(line, all_keys, n=1, cutoff=threshold)
            if matches:
                ratio = difflib.SequenceMatcher(None, line, matches[0]).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_key = matches[0]

        if best_key:
            return index.log_line_map[best_key], best_ratio, "fuzzy"

        return None, None, None

    def _grep_fallback(
        self, step_name: str, index: CodeIndexData
    ) -> tuple[ASTSourceLocation | None, float | None, str | None]:
        """Search for step name as substring in function names and file paths."""
        # Normalize step name: "Run npm install" → "npm install"
        search_term = step_name.lower()
        for prefix in ("run ", "step ", "execute "):
            if search_term.startswith(prefix):
                search_term = search_term[len(prefix):]

        if len(search_term) < 3:
            return None, None, None

        # Search in function names
        for func in index.functions:
            if search_term in func.name.lower():
                return ASTSourceLocation(
                    file_path=func.file_path,
                    line_number=func.line_number,
                    function_name=func.name,
                    qualified_name=func.qualified_name,
                ), 0.5, "grep"

        # Search in file paths
        for func in index.functions:
            if search_term in func.file_path.lower():
                return ASTSourceLocation(
                    file_path=func.file_path,
                    line_number=func.line_number,
                    function_name=func.name,
                    qualified_name=func.qualified_name,
                ), 0.3, "grep"

        return None, None, None
