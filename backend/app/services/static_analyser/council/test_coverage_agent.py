from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

from app.config import get_settings
from app.services.static_analyser import Finding

PROMPT = """You are the Test Coverage Agent. Given a list of function names and file paths, identify functions that likely have no test coverage. Look for: files with no corresponding test_*.py or *.test.js file, complex functions (high cyclomatic complexity) with no tests, public API functions not covered by tests. Return ONLY a JSON array of Finding objects with severity LOW or MEDIUM and a recommendation to add specific test cases."""


def run_test_coverage_agent(chunks, target_files: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    test_files = {p for p in target_files if "test" in Path(p).name.lower()}
    for c in chunks:
        stem = Path(c.file_path).stem
        has_test = any(stem in Path(t).stem for t in test_files)
        if not has_test and c.cyclomatic_complexity >= 8:
            findings.append(
                Finding(
                    "test_coverage",
                    "Complex function likely lacks tests",
                    "MEDIUM",
                    "MEDIUM",
                    c.file_path,
                    c.start_line,
                    c.end_line,
                    "No obvious test file detected for this complex function.",
                    c.code[:400],
                    "Add unit tests for success/failure and edge-case branches.",
                )
            )
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        return findings
    try:
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        payload = [{"file_path": c.file_path, "start_line": c.start_line, "end_line": c.end_line, "complexity": c.cyclomatic_complexity} for c in chunks[:40]]
        resp = client.messages.create(
            model=settings.STATIC_ANALYSIS_COUNCIL_MODEL,
            max_tokens=1500,
            temperature=settings.STATIC_COUNCIL_TEMPERATURE,
            system=PROMPT,
            messages=[{"role": "user", "content": json.dumps({"chunks": payload, "target_files": target_files})}],
        )
        rows = json.loads("".join(b.text for b in resp.content if hasattr(b, "text")).strip())
        for r in rows:
            findings.append(Finding("test_coverage", r.get("title", "Test gap"), r.get("severity", "LOW"), r.get("confidence", "LOW"), r.get("file_path", ""), int(r.get("start_line", 1)), int(r.get("end_line", 1)), r.get("description", ""), r.get("evidence", ""), r.get("recommendation", "")))
    except Exception:
        pass
    return findings
