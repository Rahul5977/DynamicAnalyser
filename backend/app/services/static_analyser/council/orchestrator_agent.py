from __future__ import annotations

import json

from anthropic import Anthropic

from app.config import get_settings

PROMPT = """You are the Orchestrator Agent of an enterprise SAST analysis council. Given a repository manifest and triage summary, produce a focused investigation plan. Identify the highest-risk files (highest cyclomatic complexity, most smells, external input handlers, database access, authentication code). Return ONLY valid JSON matching this schema:
{
  "security_targets": [{"chunk_id": "...", "file_path": "...", "reason": "..."}],
  "performance_targets": [{"chunk_id": "...", "file_path": "...", "reason": "..."}],
  "architecture_concerns": ["describe concern 1", "describe concern 2"],
  "test_coverage_enabled": true,
  "investigation_notes": "brief overall strategy"
}
Limit to top 10 security targets and top 10 performance targets."""


def run_orchestrator_plan(manifest: dict, triage_summary: dict) -> dict:
    settings = get_settings()
    fallback = {
        "security_targets": [],
        "performance_targets": [],
        "architecture_concerns": [],
        "test_coverage_enabled": True,
        "investigation_notes": "Rule-based fallback plan",
    }
    if not settings.ANTHROPIC_API_KEY:
        return fallback
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    text = json.dumps({"manifest": manifest, "triage_summary": triage_summary})[:120000]
    try:
        resp = client.messages.create(
            model=settings.STATIC_ANALYSIS_COUNCIL_MODEL,
            max_tokens=1800,
            temperature=settings.STATIC_COUNCIL_TEMPERATURE,
            system=PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        content = "".join(
            block.text for block in resp.content if hasattr(block, "text")
        ).strip()
        return json.loads(content)
    except Exception:
        return fallback
