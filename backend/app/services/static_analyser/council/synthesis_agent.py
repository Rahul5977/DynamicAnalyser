from __future__ import annotations

import json

from anthropic import Anthropic

from app.config import get_settings

PROMPT = """You are the Synthesis Agent. Convert confirmed and plausible findings into actionable FindingCards. For each finding, generate: a diff-style fix snippet (with - for removed lines, + for added lines), and three explanations at different levels. Return ONLY a JSON array where each element is: {"finding_index": N, "fix_snippet": "diff-format code", "explanation_technical": "2-3 sentences for developers", "explanation_manager": "1 sentence for managers", "explanation_executive": "1 sentence business impact"}. Be specific and actionable."""


def run_synthesis_agent(findings: list[dict]) -> list[dict]:
    fallback = []
    for i, _ in enumerate(findings):
        fallback.append(
            {
                "finding_index": i,
                "fix_snippet": "- // problematic code\n+ // safer refactor",
                "explanation_technical": "Refactor this area to remove the risky pattern and add validation.",
                "explanation_manager": "This reduces defect risk and maintenance overhead.",
                "explanation_executive": "This lowers security/performance risk with minimal scope.",
            }
        )

    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY or not findings:
        return fallback
    try:
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=settings.STATIC_ANALYSIS_COUNCIL_MODEL,
            max_tokens=2200,
            temperature=settings.STATIC_COUNCIL_TEMPERATURE,
            system=PROMPT,
            messages=[{"role": "user", "content": json.dumps(findings)[:120000]}],
        )
        return json.loads("".join(b.text for b in resp.content if hasattr(b, "text")).strip())
    except Exception:
        return fallback
