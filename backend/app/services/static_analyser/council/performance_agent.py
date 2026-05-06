from __future__ import annotations

import json
import re

from anthropic import Anthropic

from app.config import get_settings
from app.services.static_analyser import Finding

PROMPT = """You are the Performance Agent of an enterprise SAST council. Analyse the provided code chunks for performance issues. Focus on: O(n²) nested loops, blocking I/O in async contexts, N+1 database query patterns, large object copies in loops, unbounded memory growth, inefficient string concatenation, missing caching opportunities. For each issue, estimate the complexity class. Return ONLY a JSON array of Finding objects with the same schema as the Security Agent. If no issues, return []."""


def _rule_findings(chunks) -> list[Finding]:
    out: list[Finding] = []
    for c in chunks:
        code = c.code
        if c.cyclomatic_complexity >= 12:
            out.append(Finding("performance", "High cyclomatic complexity", "MEDIUM", "HIGH", c.file_path, c.start_line, c.end_line, "Function complexity is high; harder to optimize and maintain.", code[:400], "Split into smaller pure functions and simplify branch logic."))
        if re.search(r"for .*:\n(?:[^\n]*\n){0,5}\s*for ", code):
            out.append(Finding("performance", "Potential O(n^2) nested loop", "HIGH", "MEDIUM", c.file_path, c.start_line, c.end_line, "Nested loops can degrade performance on large inputs.", code[:400], "Pre-index data with dict/set and avoid nested scans."))
        if "await " in code and re.search(r"requests\.|time\.sleep\(", code):
            out.append(Finding("performance", "Blocking I/O in async context", "HIGH", "MEDIUM", c.file_path, c.start_line, c.end_line, "Blocking calls in async code can stall event loop.", code[:400], "Use async client libraries and non-blocking sleep."))
    return out


def run_performance_agent(chunks) -> list[Finding]:
    base = _rule_findings(chunks)
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY or not chunks:
        return base
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        payload = [{"file_path": c.file_path, "start_line": c.start_line, "end_line": c.end_line, "complexity": c.cyclomatic_complexity, "code": c.code[:3500]} for c in chunks[:20]]
        resp = client.messages.create(
            model=settings.STATIC_ANALYSIS_COUNCIL_MODEL,
            max_tokens=2200,
            temperature=settings.STATIC_COUNCIL_TEMPERATURE,
            system=PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        rows = json.loads("".join(b.text for b in resp.content if hasattr(b, "text")).strip())
        for r in rows:
            base.append(Finding("performance", r.get("title", "Performance finding"), r.get("severity", "MEDIUM"), r.get("confidence", "LOW"), r.get("file_path", ""), int(r.get("start_line", 1)), int(r.get("end_line", 1)), r.get("description", ""), r.get("evidence", ""), r.get("recommendation", "")))
    except Exception:
        pass
    return base
