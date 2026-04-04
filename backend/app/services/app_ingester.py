"""
app_ingester.py
---------------
Orchestrates the full pipeline for uploaded application log files:
  1. Read the saved file
  2. Detect / parse format  →  ParsedFunctionCall[]
  3. Persist AppFunctionCall rows
  4. Update session totals and status
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models.database import AppFunctionCall, AppLogSession
from app.services.app_log_parser import AppLogParser, ParsedFunctionCall


@dataclass
class IngestionResult:
    session_id: int
    detected_format: str
    calls_parsed: int
    total_duration_ms: int
    slowest_function: str
    slowest_duration_ms: int


class AppIngester:
    """Reads an uploaded log file, parses it, and stores results in the DB."""

    def __init__(self, db: Session):
        self.db = db
        self.parser = AppLogParser()

    def ingest_file(
        self,
        session_id: int,
        file_path: str,
        log_format: str = "auto",
        custom_pattern: str = "",
    ) -> IngestionResult:
        """
        Full ingestion pipeline for a single uploaded log file.

        Args:
            session_id:      DB id of the AppLogSession row
            file_path:       absolute path to the saved log file
            log_format:      'auto'|'json'|'syslog'|'tshark'|'logfmt'|'custom'
            custom_pattern:  regex pattern (only used when log_format=='custom')
        """
        session: AppLogSession = self.db.get(AppLogSession, session_id)
        if not session:
            raise ValueError(f"AppLogSession {session_id} not found")

        logger.info(
            "AppIngester: starting ingestion for session %d, file=%s", session_id, file_path
        )

        # 1. Read file
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError as e:
            self._fail(session, str(e))
            raise

        if not lines:
            self._fail(session, "Uploaded file is empty")
            raise ValueError("Uploaded log file is empty")

        # 2. Detect + parse
        try:
            fmt = log_format if log_format != "auto" else self.parser.detect_format(lines)
            parsed: list[ParsedFunctionCall] = self.parser.parse(
                lines, fmt=fmt, custom_pattern=custom_pattern
            )
        except Exception as e:
            self._fail(session, f"Parse error: {e}")
            raise

        if not parsed:
            # Not a hard failure — store zero calls, mark completed
            logger.warning(
                "AppIngester: no function calls found in session %d (format=%s)",
                session_id, fmt,
            )
            session.status = "completed"
            session.log_format = fmt
            session.total_calls = 0
            session.total_duration_ms = 0
            self.db.commit()
            return IngestionResult(
                session_id=session_id,
                detected_format=fmt,
                calls_parsed=0,
                total_duration_ms=0,
                slowest_function="",
                slowest_duration_ms=0,
            )

        # 3. Persist AppFunctionCall rows
        now = datetime.datetime.utcnow()
        db_calls = [
            AppFunctionCall(
                session_id=session_id,
                function_name=p.function_name,
                call_number=p.call_number,
                duration_ms=p.duration_ms,
                started_at=p.started_at,
                ended_at=p.ended_at,
                log_excerpt=p.log_excerpt[:2000] if p.log_excerpt else None,
            )
            for p in parsed
        ]
        self.db.bulk_save_objects(db_calls)

        # 4. Update session totals
        total_ms = sum(p.duration_ms for p in parsed)
        slowest = max(parsed, key=lambda p: p.duration_ms)

        session.status = "completed"
        session.log_format = fmt
        session.total_calls = len(parsed)
        session.total_duration_ms = total_ms

        self.db.commit()

        logger.info(
            "AppIngester: session %d complete — %d calls, total=%dms, slowest=%s (%dms)",
            session_id, len(parsed), total_ms, slowest.function_name, slowest.duration_ms,
        )

        return IngestionResult(
            session_id=session_id,
            detected_format=fmt,
            calls_parsed=len(parsed),
            total_duration_ms=total_ms,
            slowest_function=slowest.function_name,
            slowest_duration_ms=slowest.duration_ms,
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _fail(self, session: AppLogSession, msg: str) -> None:
        session.status = "failed"
        session.error_message = msg
        self.db.commit()
        logger.error("AppIngester: session %d failed — %s", session.id, msg)
