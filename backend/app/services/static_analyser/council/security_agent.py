from __future__ import annotations

import json
import re

from anthropic import Anthropic

from app.config import get_settings
from app.services.static_analyser import Finding

PROMPT = """You are the Security Agent of an enterprise SAST council. Analyse the provided code chunks for security vulnerabilities. Focus on: SQL injection, XSS, hardcoded secrets, command injection, path traversal, insecure deserialization, broken authentication, IDOR. For each issue found, return a Finding JSON object. Return ONLY a JSON array of findings. Each finding: {"title": "...", "severity": "CRITICAL|HIGH|MEDIUM|LOW|INFO", "confidence": "HIGH|MEDIUM|LOW", "file_path": "...", "start_line": N, "end_line": N, "description": "...", "evidence": "code snippet", "recommendation": "specific fix"}. If no issues found, return []."""


def _rule_findings(chunks) -> list[Finding]:
    out: list[Finding] = []
    for c in chunks:
        code = c.code
        if re.search(r"eval\s*\(", code):
            out.append(Finding("security", "Use of eval()", "HIGH", "HIGH", c.file_path, c.start_line, c.end_line, "Dynamic eval may execute attacker-controlled input.", code[:400], "Replace eval with strict parsing/allow-listed handlers."))
        if re.search(r"(api[_-]?key|password|secret)\s*[:=]\s*['\"][^'\"]+['\"]", code, re.IGNORECASE):
            out.append(Finding("security", "Hardcoded secret", "CRITICAL", "HIGH", c.file_path, c.start_line, c.end_line, "Credential-like literal found in code.", code[:400], "Move secret to env/config vault and rotate key."))
        if re.search(r"subprocess\..*shell\s*=\s*True|os\.system\(", code):
            out.append(Finding("security", "Command injection risk", "HIGH", "MEDIUM", c.file_path, c.start_line, c.end_line, "Shell command execution pattern detected.", code[:400], "Use parameterized subprocess calls and avoid shell=True."))
    return out


def run_security_agent(chunks) -> list[Finding]:
    base = _rule_findings(chunks)
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY or not chunks:
        return base
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        payload = [{"file_path": c.file_path, "start_line": c.start_line, "end_line": c.end_line, "code": c.code[:4000]} for c in chunks[:20]]
        resp = client.messages.create(
            model=settings.STATIC_ANALYSIS_COUNCIL_MODEL,
            max_tokens=2200,
            temperature=settings.STATIC_COUNCIL_TEMPERATURE,
            system=PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        text = "".join(block.text for block in resp.content if hasattr(block, "text")).strip()
        rows = json.loads(text)
        for r in rows:
            base.append(Finding("security", r.get("title", "Security finding"), r.get("severity", "MEDIUM"), r.get("confidence", "LOW"), r.get("file_path", ""), int(r.get("start_line", 1)), int(r.get("end_line", 1)), r.get("description", ""), r.get("evidence", ""), r.get("recommendation", "")))
    except Exception:
        pass
    return base
