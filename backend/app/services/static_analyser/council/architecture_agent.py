from __future__ import annotations

import json

from anthropic import Anthropic

from app.config import get_settings
from app.services.static_analyser import Finding

PROMPT = """You are the Architecture Agent of an enterprise SAST council. You are given: circular dependency chains, coupling scores, god class candidates, and layer violation patterns. Analyse these for architectural problems. Return ONLY a JSON array of Finding objects where file_path is the primary affected file. Focus on: circular imports that create tight coupling, god classes that violate single responsibility, missing abstraction layers, and violation of dependency direction rules. If no issues, return []."""


def run_architecture_agent(architecture_report: dict) -> list[Finding]:
    findings: list[Finding] = []
    for cycle in architecture_report.get("cycles", [])[:10]:
        findings.append(
            Finding(
                "architecture",
                "Circular dependency detected",
                "MEDIUM",
                "HIGH",
                cycle[0] if cycle else "",
                1,
                1,
                "Files import each other, increasing coupling and change risk.",
                " -> ".join(cycle),
                "Break the cycle with interfaces or dependency inversion.",
            )
        )
    for row in architecture_report.get("god_classes", [])[:10]:
        findings.append(
            Finding(
                "architecture",
                "God class/module candidate",
                "MEDIUM",
                "MEDIUM",
                row.get("file_path", ""),
                1,
                1,
                "File has too many responsibilities and coupling edges.",
                json.dumps(row),
                "Split responsibilities into smaller modules.",
            )
        )

    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        return findings
    try:
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=settings.STATIC_ANALYSIS_COUNCIL_MODEL,
            max_tokens=1600,
            temperature=settings.STATIC_COUNCIL_TEMPERATURE,
            system=PROMPT,
            messages=[{"role": "user", "content": json.dumps(architecture_report)[:120000]}],
        )
        extra = json.loads("".join(b.text for b in resp.content if hasattr(b, "text")).strip())
        for r in extra:
            findings.append(Finding("architecture", r.get("title", "Architecture finding"), r.get("severity", "MEDIUM"), r.get("confidence", "LOW"), r.get("file_path", ""), int(r.get("start_line", 1)), int(r.get("end_line", 1)), r.get("description", ""), r.get("evidence", ""), r.get("recommendation", "")))
    except Exception:
        pass
    return findings
