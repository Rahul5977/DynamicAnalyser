"""
log_schema_inferrer.py
----------------------
Uses Claude to infer log schema (regex patterns) for formats the rule-based
detector cannot recognise.  Results are cached in the LogFormatSchema table.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.logging import logger
from app.models.database import LogFormatSchema


@dataclass
class InferredSchema:
    strategy:      str          # "inline" | "enter_exit"
    ts_regex:      str | None   # named group (?P<ts>...)
    func_regex:    str | None   # named group (?P<func>...)
    elapsed_regex: str | None   # named group (?P<elapsed>...)
    elapsed_unit:  str          # "ms" | "s" | "us"
    enter_pattern: str | None   # only if strategy == "enter_exit"
    exit_pattern:  str | None   # only if strategy == "enter_exit"


_INFER_PROMPT_TMPL = """\
These are sample lines from an application log file:

{sample}

Identify the timestamp, function/operation name, and duration fields.
Return ONLY a JSON object with this exact schema (no markdown, no prose):
{{
  "strategy": "inline or enter_exit",
  "ts_regex": "named-group regex (?P<ts>...) or null",
  "func_regex": "named-group regex (?P<func>...) or null",
  "elapsed_regex": "named-group regex (?P<elapsed>[\\\\d.]+) or null",
  "elapsed_unit": "ms or s or us",
  "enter_pattern": "regex for function-entry lines or null",
  "exit_pattern": "regex for function-exit lines or null"
}}

Rules:
- Use "inline" when a single line contains both function name and duration.
- Use "enter_exit" when function start and stop are on separate lines.
- If you cannot determine a field, set it to null.
- All regex strings must be valid Python re patterns.
- Do not include backreferences or lookbehind that Python doesn't support.
"""


class AISchemaInferrer:
    """
    Sends sample lines to Claude and parses the response into InferredSchema.
    Caches the result in the LogFormatSchema table so it is reused on the
    next upload from the same app.
    """

    def __init__(self, db: Session):
        self.db = db
        self._settings = get_settings()

    # ── Public API ────────────────────────────────────────────────────────────

    def infer(
        self,
        sample_lines: list[str],
        app_name: str = "",
    ) -> InferredSchema | None:
        """
        Try to infer a log schema for these sample lines.

        1. Check cache (LogFormatSchema table) for this app_name.
        2. If not found, call Claude.
        3. Validate the returned regex patterns.
        4. Persist to cache, return InferredSchema.
        """
        sample_text = "\n".join(sample_lines[:20])

        # Check cache
        cached = self._load_cached(app_name)
        if cached:
            logger.info("LogSchemaInferrer: using cached schema for '%s'", app_name)
            cached.used_count = (cached.used_count or 0) + 1
            self.db.commit()
            return self._from_db(cached)

        # Call LLM
        schema = self._call_llm(sample_text)
        if schema is None:
            return None

        # Persist
        self._save(schema, sample_text, app_name)
        return schema

    # ── Private ───────────────────────────────────────────────────────────────

    def _call_llm(self, sample_text: str) -> InferredSchema | None:
        if not self._settings.ANTHROPIC_API_KEY:
            logger.warning("LogSchemaInferrer: ANTHROPIC_API_KEY not set — skipping")
            return None
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._settings.ANTHROPIC_API_KEY)
            prompt = _INFER_PROMPT_TMPL.format(sample=sample_text)
            resp = client.messages.create(
                model=self._settings.LLM_MODEL,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            return self._parse_response(raw)
        except Exception as e:
            logger.error("LogSchemaInferrer LLM call failed: %s", e)
            return None

    def _parse_response(self, raw: str) -> InferredSchema | None:
        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            brace = raw.find("{")
            end = raw.rfind("}")
            if brace < 0 or end < brace:
                return None
            try:
                data = json.loads(raw[brace:end + 1])
            except json.JSONDecodeError:
                return None

        # Validate regexes
        for field in ("ts_regex", "func_regex", "elapsed_regex",
                      "enter_pattern", "exit_pattern"):
            val = data.get(field)
            if val:
                try:
                    re.compile(val)
                except re.error:
                    data[field] = None

        return InferredSchema(
            strategy=data.get("strategy", "inline"),
            ts_regex=data.get("ts_regex"),
            func_regex=data.get("func_regex"),
            elapsed_regex=data.get("elapsed_regex"),
            elapsed_unit=data.get("elapsed_unit", "ms"),
            enter_pattern=data.get("enter_pattern"),
            exit_pattern=data.get("exit_pattern"),
        )

    def _load_cached(self, app_name: str) -> LogFormatSchema | None:
        if not app_name:
            return None
        return (
            self.db.query(LogFormatSchema)
            .filter(LogFormatSchema.app_name == app_name)
            .order_by(LogFormatSchema.used_count.desc())
            .first()
        )

    def _from_db(self, row: LogFormatSchema) -> InferredSchema:
        data = json.loads(row.schema_json or "{}")
        return InferredSchema(
            strategy=data.get("strategy", "inline"),
            ts_regex=data.get("ts_regex"),
            func_regex=data.get("func_regex"),
            elapsed_regex=data.get("elapsed_regex"),
            elapsed_unit=data.get("elapsed_unit", "ms"),
            enter_pattern=data.get("enter_pattern"),
            exit_pattern=data.get("exit_pattern"),
        )

    def _save(
        self, schema: InferredSchema, sample_text: str, app_name: str
    ) -> None:
        schema_dict = {
            "strategy":      schema.strategy,
            "ts_regex":      schema.ts_regex,
            "func_regex":    schema.func_regex,
            "elapsed_regex": schema.elapsed_regex,
            "elapsed_unit":  schema.elapsed_unit,
            "enter_pattern": schema.enter_pattern,
            "exit_pattern":  schema.exit_pattern,
        }
        row = LogFormatSchema(
            format_name="ai_inferred",
            strategy="ai_inferred",
            schema_json=json.dumps(schema_dict),
            sample_lines=sample_text[:2000],
            app_name=app_name,
            used_count=1,
            created_at=datetime.utcnow(),
        )
        try:
            self.db.add(row)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.warning("LogSchemaInferrer: could not cache schema: %s", e)
