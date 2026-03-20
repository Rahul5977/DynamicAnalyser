import re
from dataclasses import dataclass, field
from datetime import datetime

from app.core.exceptions import LogParseError, LogFormatError
from app.core.logging import logger

# GitHub Actions timestamp pattern: 2024-03-19T10:32:01.4567890Z
TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\s+(.*)"
)

# GitHub Actions annotations: ##[group], ##[endgroup], ##[error], ##[warning]
ANNOTATION_RE = re.compile(r"##\[(group|endgroup|error|warning)\](.*)")

# Step header inside the log archive filename: === job_name/step_number_step_name.txt ===
FILE_HEADER_RE = re.compile(r"^===\s+(.+?)\s+===$")

MAX_EXCERPT_CHARS = 2000


@dataclass
class ParsedLogLine:
    timestamp: datetime
    raw_message: str
    annotation: str | None = None
    message: str = ""


@dataclass
class ParsedStep:
    step_name: str
    step_number: int
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int = 0
    status: str = "success"
    annotation: str | None = None
    log_excerpt: str = ""
    lines: list[ParsedLogLine] = field(default_factory=list)


def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO 8601 timestamp from GitHub Actions logs."""
    # Handle variable fractional seconds by normalising to 6 digits
    ts_str = ts_str.rstrip("Z")
    if "." in ts_str:
        main, frac = ts_str.split(".", 1)
        frac = frac[:6].ljust(6, "0")
        ts_str = f"{main}.{frac}"
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError as e:
        raise LogFormatError(
            f"Invalid timestamp: {ts_str}", detail=str(e)
        ) from e


def parse_log_line(line: str) -> ParsedLogLine | None:
    """Parse a single GitHub Actions log line."""
    line = line.rstrip()
    if not line:
        return None

    ts_match = TIMESTAMP_RE.match(line)
    if not ts_match:
        return None

    timestamp = parse_timestamp(ts_match.group(1))
    rest = ts_match.group(2)

    annotation = None
    message = rest

    ann_match = ANNOTATION_RE.match(rest)
    if ann_match:
        annotation = ann_match.group(1)
        message = ann_match.group(2).strip()

    return ParsedLogLine(
        timestamp=timestamp,
        raw_message=rest,
        annotation=annotation,
        message=message,
    )


def _extract_step_name_from_header(header: str) -> tuple[str, int]:
    """Extract step name and number from log file header path.

    Example: 'build/2_Run npm install.txt' -> ('Run npm install', 2)
    """
    # Remove .txt extension
    path = header.rsplit(".txt", 1)[0] if header.endswith(".txt") else header
    # Take last segment after /
    segment = path.rsplit("/", 1)[-1] if "/" in path else path
    # Try to extract step number prefix: '2_Run npm install'
    step_match = re.match(r"(\d+)_(.+)", segment)
    if step_match:
        return step_match.group(2).strip(), int(step_match.group(1))
    return segment.strip(), 0


def parse_logs(raw_log: str) -> list[ParsedStep]:
    """Parse raw GitHub Actions logs into structured steps with timings.

    Handles two formats:
    1. Archive format with === header === sections (from get_run_logs)
    2. Flat format with group/endgroup annotations
    """
    if not raw_log or not raw_log.strip():
        raise LogParseError(
            "Empty log input",
            detail="The log content is empty or contains only whitespace",
        )

    lines = raw_log.split("\n")
    steps: list[ParsedStep] = []
    current_step: ParsedStep | None = None
    current_lines: list[ParsedLogLine] = []
    archive_mode = False  # True when we detect === file header === sections

    for line in lines:
        # Check for file section header
        header_match = FILE_HEADER_RE.match(line)
        if header_match:
            archive_mode = True
            # Finalize previous step
            if current_step and current_lines:
                _finalize_step(current_step, current_lines)
                steps.append(current_step)

            step_name, step_number = _extract_step_name_from_header(
                header_match.group(1)
            )
            current_step = ParsedStep(
                step_name=step_name,
                step_number=step_number if step_number else len(steps) + 1,
            )
            current_lines = []
            continue

        parsed = parse_log_line(line)
        if not parsed:
            continue

        # Handle group annotations as step boundaries ONLY in flat format
        if not archive_mode and parsed.annotation == "group":
            if current_step and current_lines:
                _finalize_step(current_step, current_lines)
                steps.append(current_step)

            step_name = parsed.message or f"Step {len(steps) + 1}"
            current_step = ParsedStep(
                step_name=step_name,
                step_number=len(steps) + 1,
            )
            current_lines = [parsed]
            continue

        if not archive_mode and parsed.annotation == "endgroup" and current_step:
            current_lines.append(parsed)
            _finalize_step(current_step, current_lines)
            steps.append(current_step)
            current_step = None
            current_lines = []
            continue

        # Track error/warning annotations
        if parsed.annotation in ("error", "warning") and current_step:
            current_step.annotation = parsed.annotation
            if parsed.annotation == "error":
                current_step.status = "failure"

        if current_step is None:
            # Lines before any step header — create an implicit step
            current_step = ParsedStep(
                step_name="Setup",
                step_number=0,
            )
            current_lines = []

        current_lines.append(parsed)

    # Finalize last step
    if current_step and current_lines:
        _finalize_step(current_step, current_lines)
        steps.append(current_step)

    if not steps:
        raise LogParseError(
            "No steps found in log",
            detail="Could not identify any pipeline steps from the log content",
        )

    logger.info("Parsed %d steps from log (%d lines)", len(steps), len(lines))
    return steps


def _finalize_step(step: ParsedStep, lines: list[ParsedLogLine]) -> None:
    """Calculate timing and set excerpt for a step."""
    if not lines:
        return

    timestamps = [l.timestamp for l in lines if l.timestamp]
    if timestamps:
        step.started_at = min(timestamps)
        step.ended_at = max(timestamps)
        delta = step.ended_at - step.started_at
        step.duration_ms = int(delta.total_seconds() * 1000)

    # Build log excerpt (first + last lines, capped)
    all_messages = [l.raw_message for l in lines]
    full_text = "\n".join(all_messages)
    if len(full_text) > MAX_EXCERPT_CHARS:
        half = MAX_EXCERPT_CHARS // 2
        step.log_excerpt = (
            full_text[:half] + "\n... [truncated] ...\n" + full_text[-half:]
        )
    else:
        step.log_excerpt = full_text

    step.lines = lines
