"""
app_log_parser.py
-----------------
Parses log output from *any* running program and extracts function-call timings.

Supported formats (auto-detected unless caller specifies):
  json    – structured JSON lines, one object per line
  syslog  – RFC 3164 / journald-style text logs
  tshark  – Wireshark / tshark text or fields export
  logfmt  – key=value pairs (common in Go / Rust programs)
  custom  – caller supplies a named-group regex pattern

Auto-detection priority: json → tshark → syslog → logfmt → heuristic
The heuristic extractor is a final best-effort pass that works on any log
that mentions durations (ms / s / μs) near an identifier-looking token.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ── Data structure ────────────────────────────────────────────────────────────

@dataclass
class ParsedFunctionCall:
    function_name: str
    call_number: int
    duration_ms: int
    started_at: datetime
    ended_at: datetime
    log_excerpt: str = ""


# ── Timestamp helpers ─────────────────────────────────────────────────────────

_ISO_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
_SYSLOG_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_SYSLOG_TS_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+"
    r"(\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
)


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _parse_syslog_ts(month: str, day: str, time_s: str) -> Optional[datetime]:
    try:
        m = _SYSLOG_MONTHS.get(month.lower(), 0)
        if not m:
            return None
        now = datetime.now()
        parts = time_s.split(".")
        h, mi, sec = parts[0].split(":")
        micros = int(parts[1].ljust(6, "0")[:6]) if len(parts) > 1 else 0
        return datetime(now.year, m, int(day), int(h), int(mi), int(sec), micros)
    except Exception:
        return None


def _extract_iso_ts(line: str) -> Optional[datetime]:
    m = _ISO_RE.search(line)
    return _parse_iso(m.group(1)) if m else None


def _duration_to_ms(value: str, unit: str) -> int:
    """Convert a duration string + unit to milliseconds."""
    try:
        v = float(value)
    except ValueError:
        return 0
    unit = unit.lower().strip(".")
    if unit in ("ms", "millisecond", "milliseconds", "msec"):
        return int(v)
    if unit in ("s", "sec", "second", "seconds", "secs"):
        return int(v * 1000)
    if unit in ("us", "µs", "μs", "microsecond", "microseconds"):
        return max(1, int(v / 1000))
    if unit in ("ns", "nanosecond", "nanoseconds"):
        return max(1, int(v / 1_000_000))
    if unit in ("m", "min", "minute", "minutes"):
        return int(v * 60_000)
    return int(v)  # default: assume ms


# ── Main parser class ─────────────────────────────────────────────────────────

class AppLogParser:
    """Detect format and parse a log file into ParsedFunctionCall objects."""

    # ── Format detection ──────────────────────────────────────────────────────

    def detect_format(self, lines: list[str]) -> str:
        sample = [l for l in lines[:200] if l.strip()]

        # JSON: first meaningful line is an object
        for line in sample[:30]:
            stripped = line.strip()
            if stripped.startswith("{"):
                try:
                    json.loads(stripped)
                    return "json"
                except json.JSONDecodeError:
                    pass

        # tshark: has Frame N: / dissect_ / elapsed= patterns
        tshark_hits = 0
        for line in sample[:80]:
            if re.search(r"Frame\s+\d+:", line):
                tshark_hits += 2
            if re.search(r"\belapsed\s*=\s*\d", line, re.I):
                tshark_hits += 1
            if re.search(r"\bdissect_\w+", line):
                tshark_hits += 2
            if re.search(r"^\s+(Ethernet|Internet Protocol|TCP|UDP|HTTP|TLS)\b", line):
                tshark_hits += 1
        if tshark_hits >= 3:
            return "tshark"

        # syslog: Mon DD HH:MM:SS pattern
        for line in sample[:30]:
            if _SYSLOG_TS_RE.match(line):
                return "syslog"

        # logfmt: key=value pairs dominate
        logfmt_hits = sum(
            1 for l in sample[:40]
            if re.search(r'\b\w+=(?:"[^"]*"|\S+)', l) and not l.strip().startswith("{")
        )
        if logfmt_hits >= len(sample[:40]) * 0.4:
            return "logfmt"

        return "heuristic"

    # ── Dispatcher ────────────────────────────────────────────────────────────

    def parse(
        self,
        lines: list[str],
        *,
        fmt: str = "auto",
        custom_pattern: str = "",
    ) -> list[ParsedFunctionCall]:
        if fmt == "auto":
            fmt = self.detect_format(lines)
        if fmt == "json":
            return self.parse_json_logs(lines)
        if fmt == "tshark":
            return self.parse_tshark(lines)
        if fmt == "syslog":
            return self.parse_syslog(lines)
        if fmt == "logfmt":
            return self.parse_logfmt(lines)
        if fmt == "custom" and custom_pattern:
            return self.parse_custom(lines, custom_pattern)
        return self.parse_heuristic(lines)

    # ── JSON log parser ───────────────────────────────────────────────────────

    # Supported field-name aliases
    _JSON_FUNC_KEYS = ("func", "function", "method", "operation", "name",
                       "fn", "handler", "action", "procedure", "routine")
    _JSON_TS_KEYS = ("ts", "timestamp", "time", "@timestamp", "datetime",
                     "t", "at", "logged_at", "event_time")
    _JSON_EVENT_KEYS = ("event", "phase", "type", "kind", "stage",
                        "lifecycle", "hook", "state")
    _JSON_DUR_KEYS = ("elapsed_ms", "duration_ms", "latency_ms", "time_ms",
                      "elapsed", "duration", "latency", "elapsed_s",
                      "duration_s", "latency_s", "took", "took_ms",
                      "response_time", "process_time")
    _JSON_DUR_UNIT_KEYS = ("duration_unit", "time_unit", "unit")

    _ENTER_EVENTS = frozenset(("enter", "start", "begin", "call", "invoke",
                                "request", "in", "open", "init", "entry"))
    _EXIT_EVENTS = frozenset(("exit", "end", "return", "finish", "done",
                               "response", "out", "close", "complete",
                               "completed", "result", "ok", "error", "err"))

    def _json_get(self, obj: dict, keys: tuple) -> Optional[str]:
        for k in keys:
            if k in obj:
                return str(obj[k])
        return None

    def parse_json_logs(self, lines: list[str]) -> list[ParsedFunctionCall]:
        """
        Parse structured JSON-line logs.  Handles both:
          • inline duration  {"func":"foo","elapsed_ms":42}
          • paired enter/exit {"func":"foo","event":"start","ts":"..."} + exit line
        """
        results: list[ParsedFunctionCall] = []
        # pending[func_name] = (ts, line_index, raw_line)
        pending: dict[str, tuple[datetime, int, str]] = {}
        call_counters: dict[str, int] = {}
        _now = datetime.now(timezone.utc)

        for i, raw in enumerate(lines):
            line = raw.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            func = self._json_get(obj, self._JSON_FUNC_KEYS)
            if not func:
                continue

            ts_raw = self._json_get(obj, self._JSON_TS_KEYS)
            ts = _parse_iso(ts_raw) if ts_raw else _now
            event = (self._json_get(obj, self._JSON_EVENT_KEYS) or "").lower()

            # --- Case 1: inline duration present ---
            dur_raw = self._json_get(obj, self._JSON_DUR_KEYS)
            if dur_raw is not None:
                try:
                    dur_val = float(dur_raw)
                except ValueError:
                    dur_val = 0.0
                # Guess unit from key name
                dur_key = next(
                    (k for k in self._JSON_DUR_KEYS if k in obj), "elapsed_ms"
                )
                if "_s" in dur_key or dur_key in ("elapsed", "duration", "latency",
                                                    "took", "response_time",
                                                    "process_time"):
                    # Could be seconds if < 1000 and key doesn't say ms
                    if "_ms" not in dur_key and "ms" not in dur_key and dur_val < 1000:
                        dur_ms = int(dur_val * 1000)
                    else:
                        dur_ms = int(dur_val)
                else:
                    dur_ms = int(dur_val)

                call_counters[func] = call_counters.get(func, 0) + 1
                started = pending.pop(func, (ts, i, raw))[0]
                ended = ts if ts > started else datetime.fromtimestamp(
                    started.timestamp() + dur_ms / 1000, tz=timezone.utc
                )
                results.append(ParsedFunctionCall(
                    function_name=func,
                    call_number=call_counters[func],
                    duration_ms=dur_ms,
                    started_at=started,
                    ended_at=ended,
                    log_excerpt=raw.strip(),
                ))
                continue

            # --- Case 2: enter event ---
            if event in self._ENTER_EVENTS or not event:
                pending[func] = (ts, i, raw.strip())

            # --- Case 3: exit event ---
            elif event in self._EXIT_EVENTS:
                if func in pending:
                    start_ts, start_idx, start_raw = pending.pop(func)
                    dur_ms = max(0, int((ts - start_ts).total_seconds() * 1000))
                    call_counters[func] = call_counters.get(func, 0) + 1
                    excerpt = start_raw + "\n" + raw.strip()
                    results.append(ParsedFunctionCall(
                        function_name=func,
                        call_number=call_counters[func],
                        duration_ms=dur_ms,
                        started_at=start_ts,
                        ended_at=ts,
                        log_excerpt=excerpt,
                    ))

        return results

    # ── tshark parser ─────────────────────────────────────────────────────────

    # Matches: "dissect_tcp  elapsed=0.342s" or "Frame 1 dissect elapsed=5ms"
    _TSHARK_FUNC_DUR = re.compile(
        r"(?P<func>[a-z_][a-z0-9_.:\-]*)\s+elapsed\s*=\s*(?P<val>[\d.]+)\s*(?P<unit>ms|s|us|μs)?\b",
        re.I,
    )
    # frame timestamp line: "   0.000000 192.168.0.1 → 192.168.0.2 TCP 74 …"
    _TSHARK_FRAME_TS = re.compile(
        r"^\s*(?P<rel>[\d.]+)\s+\d{4}-\d{2}-\d{2}\s+[\d:.]+", re.I
    )
    # tshark fields mode: tab-separated, first column = frame.time_relative
    _TSHARK_FIELDS = re.compile(r"^[\d.]+\t")

    def parse_tshark(self, lines: list[str]) -> list[ParsedFunctionCall]:
        results: list[ParsedFunctionCall] = []
        call_counters: dict[str, int] = {}
        _base = datetime.now(timezone.utc)

        for i, raw in enumerate(lines):
            # Try dissect_XXX elapsed= pattern
            m = self._TSHARK_FUNC_DUR.search(raw)
            if m:
                func = m.group("func")
                val = m.group("val")
                unit = m.group("unit") or "s"
                dur_ms = _duration_to_ms(val, unit)
                ts = _extract_iso_ts(raw) or _base
                call_counters[func] = call_counters.get(func, 0) + 1
                # Build excerpt: previous 2 lines + this line
                excerpt_lines = lines[max(0, i - 2): i + 1]
                results.append(ParsedFunctionCall(
                    function_name=func,
                    call_number=call_counters[func],
                    duration_ms=dur_ms,
                    started_at=ts,
                    ended_at=ts,
                    log_excerpt="\n".join(l.rstrip() for l in excerpt_lines),
                ))
                continue

            # tshark fields mode: frame.time_relative\tframe.len\t...
            if self._TSHARK_FIELDS.match(raw):
                parts = raw.strip().split("\t")
                try:
                    rel_s = float(parts[0])
                    dur_ms = max(1, int(rel_s * 1000))
                except (ValueError, IndexError):
                    continue
                func = parts[1] if len(parts) > 1 else "frame"
                func = func.strip() or "frame"
                call_counters[func] = call_counters.get(func, 0) + 1
                results.append(ParsedFunctionCall(
                    function_name=func,
                    call_number=call_counters[func],
                    duration_ms=dur_ms,
                    started_at=_base,
                    ended_at=_base,
                    log_excerpt=raw.strip(),
                ))

        # If nothing found via dissect/fields, fall back to heuristic
        if not results:
            results = self.parse_heuristic(lines)
        return results

    # ── syslog parser ─────────────────────────────────────────────────────────

    _SYSLOG_HDR = re.compile(
        r"^(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
        r"(?P<day>\d{1,2})\s+(?P<time>[\d:.]+)\s+"
        r"(?P<host>\S+)\s+(?P<proc>[^\[:]+)(?:\[(?P<pid>\d+)\])?:\s*"
        r"(?P<msg>.+)$",
        re.I,
    )
    # Message patterns that indicate a function call event
    _SYSLOG_ENTER_RE = re.compile(
        r"(?:\[(?:TRACE|DEBUG)\]\s+)?(?P<func>[a-z_][a-z0-9_.:\-]+)\s*\(?\)?\s+"
        r"(?:start|enter|begin|called|invoke|entry)",
        re.I,
    )
    _SYSLOG_EXIT_RE = re.compile(
        r"(?:\[(?:TRACE|DEBUG)\]\s+)?(?P<func>[a-z_][a-z0-9_.:\-]+)\s*\(?\)?\s+"
        r"(?:exit|end|return|finish|done|complete)",
        re.I,
    )
    _SYSLOG_INLINE_DUR = re.compile(
        r"(?P<func>[a-z_][a-z0-9_.:\-]+).*?"
        r"(?:took|elapsed|duration|latency|time)[\s:=]+(?P<val>[\d.]+)\s*"
        r"(?P<unit>ms|s|sec|us|μs|ns)\b",
        re.I,
    )

    def parse_syslog(self, lines: list[str]) -> list[ParsedFunctionCall]:
        results: list[ParsedFunctionCall] = []
        pending: dict[str, tuple[datetime, str]] = {}
        call_counters: dict[str, int] = {}

        for i, raw in enumerate(lines):
            hdr = self._SYSLOG_HDR.match(raw)
            msg = hdr.group("msg") if hdr else raw.strip()
            ts = (
                _parse_syslog_ts(hdr.group("month"), hdr.group("day"), hdr.group("time"))
                if hdr else None
            ) or _extract_iso_ts(raw) or datetime.now(timezone.utc)

            # Inline duration in message?
            dm = self._SYSLOG_INLINE_DUR.search(msg)
            if dm:
                func = dm.group("func")
                dur_ms = _duration_to_ms(dm.group("val"), dm.group("unit"))
                call_counters[func] = call_counters.get(func, 0) + 1
                excerpt_lines = lines[max(0, i - 1): i + 2]
                results.append(ParsedFunctionCall(
                    function_name=func,
                    call_number=call_counters[func],
                    duration_ms=dur_ms,
                    started_at=ts,
                    ended_at=ts,
                    log_excerpt="\n".join(l.rstrip() for l in excerpt_lines),
                ))
                continue

            em = self._SYSLOG_ENTER_RE.search(msg)
            if em:
                pending[em.group("func")] = (ts, raw.strip())
                continue

            xm = self._SYSLOG_EXIT_RE.search(msg)
            if xm:
                func = xm.group("func")
                if func in pending:
                    start_ts, start_raw = pending.pop(func)
                    dur_ms = max(0, int((ts - start_ts).total_seconds() * 1000))
                    call_counters[func] = call_counters.get(func, 0) + 1
                    results.append(ParsedFunctionCall(
                        function_name=func,
                        call_number=call_counters[func],
                        duration_ms=dur_ms,
                        started_at=start_ts,
                        ended_at=ts,
                        log_excerpt=start_raw + "\n" + raw.strip(),
                    ))

        if not results:
            results = self.parse_heuristic(lines)
        return results

    # ── logfmt parser ─────────────────────────────────────────────────────────

    _LOGFMT_PAIR = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')
    _LOGFMT_FUNC_KEYS = ("func", "function", "method", "handler",
                          "operation", "rpc", "route", "caller")
    _LOGFMT_DUR_KEYS = ("duration", "elapsed", "latency", "took",
                         "duration_ms", "elapsed_ms", "response_time")
    _LOGFMT_EVENT_KEYS = ("event", "msg", "message", "level", "type")

    def parse_logfmt(self, lines: list[str]) -> list[ParsedFunctionCall]:
        results: list[ParsedFunctionCall] = []
        pending: dict[str, tuple[datetime, str]] = {}
        call_counters: dict[str, int] = {}
        _now = datetime.now(timezone.utc)

        for i, raw in enumerate(lines):
            pairs = {k: v.strip('"') for k, v in self._LOGFMT_PAIR.findall(raw)}
            if not pairs:
                continue

            func = next((pairs[k] for k in self._LOGFMT_FUNC_KEYS if k in pairs), None)
            if not func:
                continue

            ts_raw = pairs.get("ts") or pairs.get("time") or pairs.get("t")
            ts = _parse_iso(ts_raw) if ts_raw else _now

            dur_raw = next((pairs[k] for k in self._LOGFMT_DUR_KEYS if k in pairs), None)
            if dur_raw is not None:
                # Strip trailing unit letters
                num_m = re.match(r"([\d.]+)(.*)", dur_raw)
                if num_m:
                    unit = num_m.group(2).strip() or "ms"
                    dur_ms = _duration_to_ms(num_m.group(1), unit)
                else:
                    dur_ms = 0
                call_counters[func] = call_counters.get(func, 0) + 1
                results.append(ParsedFunctionCall(
                    function_name=func,
                    call_number=call_counters[func],
                    duration_ms=dur_ms,
                    started_at=ts,
                    ended_at=ts,
                    log_excerpt=raw.strip(),
                ))
                continue

            event = next(
                (pairs[k].lower() for k in self._LOGFMT_EVENT_KEYS if k in pairs), ""
            )
            if any(e in event for e in ("start", "begin", "enter", "call")):
                pending[func] = (ts, raw.strip())
            elif any(e in event for e in ("end", "done", "finish", "exit", "return")):
                if func in pending:
                    start_ts, start_raw = pending.pop(func)
                    dur_ms = max(0, int((ts - start_ts).total_seconds() * 1000))
                    call_counters[func] = call_counters.get(func, 0) + 1
                    results.append(ParsedFunctionCall(
                        function_name=func,
                        call_number=call_counters[func],
                        duration_ms=dur_ms,
                        started_at=start_ts,
                        ended_at=ts,
                        log_excerpt=start_raw + "\n" + raw.strip(),
                    ))

        if not results:
            results = self.parse_heuristic(lines)
        return results

    # ── Custom / regex parser ─────────────────────────────────────────────────

    def parse_custom(self, lines: list[str], pattern: str) -> list[ParsedFunctionCall]:
        """
        User-supplied regex with named groups:
          func        – function / operation name (required)
          timestamp   – ISO-ish timestamp (optional)
          duration    – numeric duration value (optional)
          unit        – duration unit: ms|s|us (optional, default ms)
          event       – start|end (optional)

        If 'duration' group is absent, pairs lines by func+event.
        """
        results: list[ParsedFunctionCall] = []
        pending: dict[str, tuple[datetime, str]] = {}
        call_counters: dict[str, int] = {}
        _now = datetime.now(timezone.utc)

        try:
            rx = re.compile(pattern, re.I)
        except re.error:
            return self.parse_heuristic(lines)

        for i, raw in enumerate(lines):
            m = rx.search(raw)
            if not m:
                continue
            gd = m.groupdict()
            func = gd.get("func", "").strip()
            if not func:
                continue

            ts_raw = gd.get("timestamp", "")
            ts = _parse_iso(ts_raw) if ts_raw else _now

            dur_raw = gd.get("duration")
            if dur_raw is not None:
                unit = gd.get("unit") or "ms"
                dur_ms = _duration_to_ms(dur_raw, unit)
                call_counters[func] = call_counters.get(func, 0) + 1
                results.append(ParsedFunctionCall(
                    function_name=func,
                    call_number=call_counters[func],
                    duration_ms=dur_ms,
                    started_at=ts,
                    ended_at=ts,
                    log_excerpt=raw.strip(),
                ))
                continue

            event = (gd.get("event") or "").lower()
            if any(e in event for e in ("start", "begin", "enter", "call", "open")):
                pending[func] = (ts, raw.strip())
            elif any(e in event for e in ("end", "done", "finish", "exit", "return", "close")):
                if func in pending:
                    start_ts, start_raw = pending.pop(func)
                    dur_ms = max(0, int((ts - start_ts).total_seconds() * 1000))
                    call_counters[func] = call_counters.get(func, 0) + 1
                    results.append(ParsedFunctionCall(
                        function_name=func,
                        call_number=call_counters[func],
                        duration_ms=dur_ms,
                        started_at=start_ts,
                        ended_at=ts,
                        log_excerpt=start_raw + "\n" + raw.strip(),
                    ))

        return results

    # ── Heuristic / fallback parser ───────────────────────────────────────────
    #
    # Two patterns tried per line:
    #   1. Direct:  <func>  (took|elapsed|...)  <value><unit>
    #      e.g.  "parse_frame took 12.3ms"
    #   2. Reverse: (took|elapsed|...) <value><unit> ... <func>
    #      e.g.  "completed in 2.1s: process_packet"
    # Function names: letters/digits/underscores only (no colons → avoids timestamps).
    # The leading char must be a letter or underscore; subsequent chars via \w.

    _HEURISTIC_DIRECT = re.compile(
        r"\b(?P<func>[a-z_]\w{2,})\s+"
        r"(?:took|elapsed|duration|latency|time|finished in|completed in)"
        r"[\s:=]*(?P<val>[\d.]+)\s*(?P<unit>ms|s|sec|us|μs|ns|m(?:in)?)\b",
        re.I,
    )
    _HEURISTIC_REVERSE = re.compile(
        r"(?:took|elapsed|duration|completed in|finished in|latency)"
        r"[\s:=]*(?P<val>[\d.]+)\s*(?P<unit>ms|s|sec|us|μs|ns|m(?:in)?)\b"
        r"[^a-z_]*(?P<func>[a-z_]\w{2,})\b",
        re.I,
    )
    # Inline colon pattern:  "func_name: 12.3ms"
    _HEURISTIC_COLON = re.compile(
        r"\b(?P<func>[a-z_]\w{2,}):\s*(?P<val>[\d.]+)\s*(?P<unit>ms|s|sec|us|μs|ns)\b",
        re.I,
    )

    # Generic tokens that are not function names
    _HEURISTIC_SKIP = frozenset({
        "the", "in", "at", "by", "on", "for", "to", "and", "not",
        "with", "from", "into", "done", "took", "elapsed", "duration",
        "time", "latency", "sec", "second", "seconds", "minute", "total",
    })

    def parse_heuristic(self, lines: list[str]) -> list[ParsedFunctionCall]:
        results: list[ParsedFunctionCall] = []
        call_counters: dict[str, int] = {}
        _now = datetime.now(timezone.utc)

        for i, raw in enumerate(lines):
            m = (
                self._HEURISTIC_DIRECT.search(raw)
                or self._HEURISTIC_COLON.search(raw)
                or self._HEURISTIC_REVERSE.search(raw)
            )
            if not m:
                continue
            gd = m.groupdict()
            func = gd.get("func", "").strip()
            val = gd.get("val", "0")
            unit = gd.get("unit", "ms")
            if not func or func.lower() in self._HEURISTIC_SKIP:
                continue
            # Reject tokens that are all-digits or look like version strings (v1, v2)
            if re.fullmatch(r"\d+", func) or re.fullmatch(r"[vV]\d+", func):
                continue
            dur_ms = _duration_to_ms(val, unit)
            ts = _extract_iso_ts(raw) or _now
            call_counters[func] = call_counters.get(func, 0) + 1
            excerpt_lines = lines[max(0, i - 1): i + 2]
            results.append(ParsedFunctionCall(
                function_name=func,
                call_number=call_counters[func],
                duration_ms=dur_ms,
                started_at=ts,
                ended_at=ts,
                log_excerpt="\n".join(l.rstrip() for l in excerpt_lines),
            ))

        return results
