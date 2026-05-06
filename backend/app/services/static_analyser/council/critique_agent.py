from __future__ import annotations

import json

from anthropic import Anthropic

from app.config import get_settings

PROMPT = """You are the Critique Agent — an adversarial reviewer. Your job is to verify, dispute, or confirm findings from other agents. For each finding, assess: Is the evidence convincing? Is the severity correctly calibrated? Is this a false positive? Could a real attack exploit this? Return ONLY a JSON array where each element is: {"finding_index": N, "verdict": "CONFIRMED|PLAUSIBLE|DISPUTED", "note": "brief explanation of your verdict"}. Be strict — dispute findings that lack solid evidence or are over-hyped."""


def run_critique_agent(findings: list[dict]) -> list[dict]:
    if not findings:
        return []
    settings = get_settings()
    fallback = [{"finding_index": i, "verdict": "PLAUSIBLE", "note": "Rule-based default critique."} for i, _ in enumerate(findings)]
    if not settings.ANTHROPIC_API_KEY:
        return fallback
    try:
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=settings.STATIC_ANALYSIS_COUNCIL_MODEL,
            max_tokens=1800,
            temperature=settings.STATIC_COUNCIL_TEMPERATURE,
            system=PROMPT,
            messages=[{"role": "user", "content": json.dumps(findings)[:120000]}],
        )
        return json.loads("".join(b.text for b in resp.content if hasattr(b, "text")).strip())
    except Exception:
        return fallback
