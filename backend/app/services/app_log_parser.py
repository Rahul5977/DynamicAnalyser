"""
app_log_parser.py
-----------------
Universal log parser for any running program that produces timing logs.

Architecture:
  FormatDetector  – scores each format against sample lines → returns (fmt, confidence)
  Per-format parsers  – each returns list[UniversalLogRecord]
  AppLogParser    – thin dispatcher; backward-compat entry point for the ingester

Formats:
  json       – structured JSON lines
  syslog     – RFC 3164 / journald
  logfmt     – key=value (Go, Rust, etc.)
  spring     – Spring Boot multi-level log lines
  rails      – Ruby on Rails request logs
  tshark     – Wireshark / tshark text / fields export
  enter_exit – generic paired ENTER / EXIT tracing (C, Python, Java, custom)
  heuristic  – fallback: any line with "func … Xms"
  custom     – user-supplied named-group regex
  unknown    – detector couldn't reach 0.3 confidence (falls back to heuristic)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class UniversalLogRecord:
    """Single normalised output from every parser."""
    func_name:   str
    duration_ms: int
    timestamp:   datetime
    log_excerpt: str    # 3–5 surrounding lines
    raw_line:    str    # original matched line
    call_number: int = 1


@dataclass
class ParsedFunctionCall:
    """Backward-compat type consumed by AppIngester.  Maps 1-to-1 with UniversalLogRecord."""
    function_name: str
    call_number:   int
    duration_ms:   int
    started_at:    datetime
    ended_at:      datetime
    log_excerpt:   str = ""
    raw_line:      str = ""


def _ulr_to_parsed(r: UniversalLogRecord) -> ParsedFunctionCall:
    return ParsedFunctionCall(
        function_name=r.func_name,
        call_number=r.call_number,
        duration_ms=r.duration_ms,
        started_at=r.timestamp,
        ended_at=r.timestamp,
        log_excerpt=r.log_excerpt,
        raw_line=r.raw_line,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════════

_ISO_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
_SYSLOG_MONTHS = {
    m: i for i, m in enumerate(
        ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1
    )
}
_SYSLOG_TS_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+"
    r"(\d{2}:\d{2}:\d{2}(?:\.\d+)?)",
    re.I,
)


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_iso_ts(line: str) -> Optional[datetime]:
    m = _ISO_RE.search(line)
    return _parse_iso(m.group(1)) if m else None


def _parse_syslog_ts(month: str, day: str, time_s: str) -> Optional[datetime]:
    try:
        mo = _SYSLOG_MONTHS.get(month.lower(), 0)
        if not mo:
            return None
        parts = time_s.split(".")
        h, mi, sec = parts[0].split(":")
        us = int(parts[1].ljust(6, "0")[:6]) if len(parts) > 1 else 0
        now = datetime.now()
        return datetime(now.year, mo, int(day), int(h), int(mi), int(sec), us)
    except Exception:
        return None


def _duration_to_ms(value: str, unit: str) -> int:
    try:
        v = float(value)
    except ValueError:
        return 0
    u = unit.lower().strip(".")
    if u in ("ms", "millisecond", "milliseconds", "msec"):
        return int(v)
    if u in ("s", "sec", "second", "seconds", "secs"):
        return int(v * 1_000)
    if u in ("us", "µs", "μs", "microsecond", "microseconds"):
        return max(1, int(v / 1_000))
    if u in ("ns", "nanosecond", "nanoseconds"):
        return max(1, int(v / 1_000_000))
    if u in ("m", "min", "minute", "minutes"):
        return int(v * 60_000)
    return int(v)


def _excerpt(lines: list[str], idx: int, before: int = 2, after: int = 2) -> str:
    lo = max(0, idx - before)
    hi = min(len(lines), idx + after + 1)
    return "\n".join(l.rstrip() for l in lines[lo:hi])


_NOW = datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════════
# FormatDetector
# ═══════════════════════════════════════════════════════════════════════════════

class FormatDetector:
    """Score-based format detection.  Returns (format_name, confidence 0.0-1.0)."""

    _ENTER_PAT = re.compile(
        r"\b(enter|start|begin|ENTER|START|CALL|>>|→|>)\b.{0,60}\b\w{3,}\b", re.I
    )
    _EXIT_PAT = re.compile(
        r"\b(exit|end|finish|EXIT|END|RETURN|<<|←|<)\b.{0,60}\b\w{3,}\b", re.I
    )
    _SPRING_PAT = re.compile(
        r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[.,]\d+\s+"
        r"(ERROR|WARN|INFO|DEBUG|TRACE)\s+\[",
        re.I,
    )
    _RAILS_PAT = re.compile(
        r"(Completed\s+\d{3}|Processing by|Started\s+(?:GET|POST|PUT|PATCH|DELETE))",
        re.I,
    )
    _TSHARK_DISSECT = re.compile(r"\belapsed\s*=\s*[\d.]+|Frame\s+\d+:|dissect_\w+", re.I)
    _LOGFMT_PAT = re.compile(r'(?:\w+=(?:"[^"]*"|\S+)\s*){3,}')

    def detect(self, lines: list[str]) -> tuple[str, float]:
        sample = [l for l in lines[:100] if l.strip()]
        if not sample:
            return "unknown", 0.0

        scores = {
            "json":       self._score_json(sample),
            "spring":     self._score_spring(sample),
            "rails":      self._score_rails(sample),
            "tshark":     self._score_tshark(sample),
            "syslog":     self._score_syslog(sample),
            "logfmt":     self._score_logfmt(sample),
            "enter_exit": self._score_enter_exit(sample),
        }
        best = max(scores, key=scores.get)
        conf = scores[best]
        return (best, conf) if conf > 0.3 else ("unknown", conf)

    # ── individual scorers ────────────────────────────────────────────────────

    def _score_json(self, sample: list[str]) -> float:
        hits = 0
        for l in sample[:30]:
            s = l.strip()
            if s.startswith("{"):
                try:
                    json.loads(s); hits += 1
                except json.JSONDecodeError:
                    pass
        return hits / max(len(sample[:30]), 1)

    def _score_spring(self, sample: list[str]) -> float:
        hits = sum(1 for l in sample[:40] if self._SPRING_PAT.match(l))
        return hits / max(len(sample[:40]), 1)

    def _score_rails(self, sample: list[str]) -> float:
        hits = sum(1 for l in sample[:40] if self._RAILS_PAT.search(l))
        return hits / max(len(sample[:40]), 1)

    def _score_tshark(self, sample: list[str]) -> float:
        hits = sum(
            2 if re.search(r"Frame\s+\d+:|dissect_\w+", l) else
            1 if re.search(r"\belapsed\s*=\s*[\d.]", l) else 0
            for l in sample[:60]
        )
        return min(hits / max(len(sample[:60]), 1) * 3, 1.0)

    def _score_syslog(self, sample: list[str]) -> float:
        hits = sum(1 for l in sample[:30] if _SYSLOG_TS_RE.match(l))
        return hits / max(len(sample[:30]), 1)

    def _score_logfmt(self, sample: list[str]) -> float:
        hits = sum(
            1 for l in sample[:40]
            if self._LOGFMT_PAT.search(l) and not l.strip().startswith("{")
        )
        return hits / max(len(sample[:40]), 1)

    def _score_enter_exit(self, sample: list[str]) -> float:
        has_enter = any(self._ENTER_PAT.search(l) for l in sample[:50])
        has_exit  = any(self._EXIT_PAT.search(l) for l in sample[:50])
        return 0.9 if (has_enter and has_exit) else 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Per-format parsers  →  list[UniversalLogRecord]
# ═══════════════════════════════════════════════════════════════════════════════

class JsonLogParser:
    _FUNC_KEYS = ("func", "function", "method", "operation", "name",
                  "fn", "handler", "action", "procedure", "routine", "rpc")
    _TS_KEYS   = ("ts", "timestamp", "time", "@timestamp", "datetime",
                  "t", "at", "logged_at", "event_time")
    _EVENT_KEYS = ("event", "phase", "type", "kind", "stage",
                   "lifecycle", "hook", "state", "msg", "message")
    _DUR_KEYS  = ("elapsed_ms", "duration_ms", "latency_ms", "time_ms",
                  "elapsed", "duration", "latency", "elapsed_s", "duration_s",
                  "latency_s", "took", "took_ms", "response_time", "process_time",
                  "time_taken", "rt")
    _ENTER_EV = frozenset(("enter","start","begin","call","invoke",
                            "request","in","open","init","entry","received"))
    _EXIT_EV  = frozenset(("exit","end","return","finish","done","response",
                            "out","close","complete","completed","ok","error","err","sent"))

    def _get(self, obj: dict, keys: tuple) -> Optional[str]:
        for k in keys:
            if k in obj: return str(obj[k])
        return None

    def parse(self, lines: list[str]) -> list[UniversalLogRecord]:
        results: list[UniversalLogRecord] = []
        pending: dict[str, tuple[datetime, str]] = {}
        counters: dict[str, int] = {}

        for i, raw in enumerate(lines):
            s = raw.strip()
            if not s.startswith("{"): continue
            try: obj = json.loads(s)
            except json.JSONDecodeError: continue
            if not isinstance(obj, dict): continue

            fn = self._get(obj, self._FUNC_KEYS)
            if not fn: continue

            ts_raw = self._get(obj, self._TS_KEYS)
            ts = _parse_iso(ts_raw) if ts_raw else _NOW
            event = (self._get(obj, self._EVENT_KEYS) or "").lower()

            dur_raw = self._get(obj, self._DUR_KEYS)
            if dur_raw is not None:
                try: dv = float(dur_raw)
                except ValueError: dv = 0.0
                dur_key = next((k for k in self._DUR_KEYS if k in obj), "elapsed_ms")
                if "_ms" not in dur_key and "ms" not in dur_key and dv < 1000:
                    dur_ms = int(dv * 1000)
                else:
                    dur_ms = int(dv)
                counters[fn] = counters.get(fn, 0) + 1
                start_ts = pending.pop(fn, (ts, ""))[0]
                results.append(UniversalLogRecord(
                    func_name=fn, duration_ms=dur_ms, timestamp=start_ts,
                    log_excerpt=s, raw_line=s, call_number=counters[fn],
                ))
                continue

            if event in self._ENTER_EV or not event:
                pending[fn] = (ts, s)
            elif event in self._EXIT_EV and fn in pending:
                st, sr = pending.pop(fn)
                dur_ms = max(0, int((ts - st).total_seconds() * 1000))
                counters[fn] = counters.get(fn, 0) + 1
                results.append(UniversalLogRecord(
                    func_name=fn, duration_ms=dur_ms, timestamp=st,
                    log_excerpt=sr + "\n" + s, raw_line=s, call_number=counters[fn],
                ))

        return results


class SyslogParser:
    _HDR = re.compile(
        r"^(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
        r"(?P<day>\d{1,2})\s+(?P<time>[\d:.]+)\s+"
        r"(?P<host>\S+)\s+(?P<proc>[^\[:]+)(?:\[(?P<pid>\d+)\])?:\s*(?P<msg>.+)$",
        re.I,
    )
    _INLINE = re.compile(
        r"(?P<func>[a-z_]\w{2,})\b.*?"
        r"(?:took|elapsed|duration|latency|time)[\s:=]+(?P<val>[\d.]+)\s*"
        r"(?P<unit>ms|s|sec|us|μs|ns)\b",
        re.I,
    )
    _ENTER = re.compile(
        r"(?:\[(?:TRACE|DEBUG)\]\s+)?(?P<func>[a-z_]\w{2,})\s*\(?\)?\s+"
        r"(?:start|enter|begin|called|invoke|entry)\b",
        re.I,
    )
    _EXIT = re.compile(
        r"(?:\[(?:TRACE|DEBUG)\]\s+)?(?P<func>[a-z_]\w{2,})\s*\(?\)?\s+"
        r"(?:exit|end|return|finish|done|complete)\b",
        re.I,
    )

    def parse(self, lines: list[str]) -> list[UniversalLogRecord]:
        results: list[UniversalLogRecord] = []
        pending: dict[str, tuple[datetime, str]] = {}
        counters: dict[str, int] = {}

        for i, raw in enumerate(lines):
            hdr = self._HDR.match(raw)
            msg = hdr.group("msg") if hdr else raw.strip()
            ts = (
                _parse_syslog_ts(hdr.group("month"), hdr.group("day"), hdr.group("time"))
                if hdr else None
            ) or _extract_iso_ts(raw) or _NOW

            dm = self._INLINE.search(msg)
            if dm:
                fn = dm.group("func")
                dur_ms = _duration_to_ms(dm.group("val"), dm.group("unit"))
                counters[fn] = counters.get(fn, 0) + 1
                results.append(UniversalLogRecord(
                    func_name=fn, duration_ms=dur_ms, timestamp=ts,
                    log_excerpt=_excerpt(lines, i), raw_line=raw.rstrip(),
                    call_number=counters[fn],
                ))
                continue

            em = self._ENTER.search(msg)
            if em:
                pending[em.group("func")] = (ts, raw.rstrip()); continue

            xm = self._EXIT.search(msg)
            if xm:
                fn = xm.group("func")
                if fn in pending:
                    st, sr = pending.pop(fn)
                    dur_ms = max(0, int((ts - st).total_seconds() * 1000))
                    counters[fn] = counters.get(fn, 0) + 1
                    results.append(UniversalLogRecord(
                        func_name=fn, duration_ms=dur_ms, timestamp=st,
                        log_excerpt=sr + "\n" + raw.rstrip(), raw_line=raw.rstrip(),
                        call_number=counters[fn],
                    ))

        return results or HeuristicParser().parse(lines)


class LogfmtParser:
    _PAIR = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')
    _FUNC_KEYS = ("func", "function", "method", "handler",
                  "operation", "rpc", "route", "caller", "endpoint")
    _DUR_KEYS  = ("duration", "elapsed", "latency", "took",
                  "duration_ms", "elapsed_ms", "response_time", "rt")
    _EVENT_KEYS = ("event", "msg", "message", "level", "type", "action")

    def parse(self, lines: list[str]) -> list[UniversalLogRecord]:
        results: list[UniversalLogRecord] = []
        pending: dict[str, tuple[datetime, str]] = {}
        counters: dict[str, int] = {}

        for i, raw in enumerate(lines):
            pairs = {k: v.strip('"') for k, v in self._PAIR.findall(raw)}
            if not pairs: continue
            fn = next((pairs[k] for k in self._FUNC_KEYS if k in pairs), None)
            if not fn: continue
            ts_raw = pairs.get("ts") or pairs.get("time") or pairs.get("t")
            ts = _parse_iso(ts_raw) if ts_raw else _NOW

            dur_raw = next((pairs[k] for k in self._DUR_KEYS if k in pairs), None)
            if dur_raw is not None:
                m = re.match(r"([\d.]+)(.*)", dur_raw)
                unit = m.group(2).strip() or "ms" if m else "ms"
                val  = m.group(1) if m else "0"
                dur_ms = _duration_to_ms(val, unit)
                counters[fn] = counters.get(fn, 0) + 1
                results.append(UniversalLogRecord(
                    func_name=fn, duration_ms=dur_ms, timestamp=ts,
                    log_excerpt=raw.rstrip(), raw_line=raw.rstrip(),
                    call_number=counters[fn],
                ))
                continue

            event = next(
                (pairs[k].lower() for k in self._EVENT_KEYS if k in pairs), ""
            )
            if any(e in event for e in ("start","begin","enter","call","received")):
                pending[fn] = (ts, raw.rstrip())
            elif any(e in event for e in ("end","done","finish","exit","return","sent")):
                if fn in pending:
                    st, sr = pending.pop(fn)
                    dur_ms = max(0, int((ts - st).total_seconds() * 1000))
                    counters[fn] = counters.get(fn, 0) + 1
                    results.append(UniversalLogRecord(
                        func_name=fn, duration_ms=dur_ms, timestamp=st,
                        log_excerpt=sr + "\n" + raw.rstrip(), raw_line=raw.rstrip(),
                        call_number=counters[fn],
                    ))

        return results or HeuristicParser().parse(lines)


class SpringBootParser:
    """
    Spring Boot log format:
      2024-03-19 10:32:01.456  INFO [main] c.e.MyService - fetchUsers() in 1234ms
      2024-03-19 10:32:01.456 DEBUG [pool] c.e.Dao - executeQuery executed in 2.1s
    """
    _LINE = re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2}[\s,T]\d{2}:\d{2}:\d{2}[.,]\d+)\s+"
        r"(?P<level>ERROR|WARN|INFO|DEBUG|TRACE)\s+\[(?P<thread>[^\]]+)\]\s+"
        r"(?P<logger>\S+)\s+-\s+(?P<msg>.+)$",
        re.I,
    )
    # msg patterns:  "methodName() in 1234ms"  /  "executed in 1.23s"
    _INLINE = re.compile(
        r"(?P<func>[a-zA-Z_]\w{1,})\s*(?:\(\))?\s+"
        r"(?:in|took|executed in|completed in|finished in|elapsed)[:\s]*"
        r"(?P<val>[\d.]+)\s*(?P<unit>ms|s|sec|us|ns|m(?:in)?)\b",
        re.I,
    )
    # "Executed SQL (1234ms)"  style
    _BRACKET_DUR = re.compile(
        r"(?P<func>[A-Za-z_]\w{1,})[^(]*\((?P<val>[\d.]+)\s*(?P<unit>ms|s|sec)\)",
        re.I,
    )

    def parse(self, lines: list[str]) -> list[UniversalLogRecord]:
        results: list[UniversalLogRecord] = []
        counters: dict[str, int] = {}

        for i, raw in enumerate(lines):
            lm = self._LINE.match(raw)
            if not lm:
                # Try heuristic on this line as Spring plain fallback
                continue
            msg = lm.group("msg")
            ts_s = lm.group("ts").replace(",", ".").replace("T", " ")
            ts = _parse_iso(ts_s.replace(" ", "T")) or _NOW

            m = self._INLINE.search(msg) or self._BRACKET_DUR.search(msg)
            if not m: continue
            fn = m.group("func")
            dur_ms = _duration_to_ms(m.group("val"), m.group("unit"))
            counters[fn] = counters.get(fn, 0) + 1
            results.append(UniversalLogRecord(
                func_name=fn, duration_ms=dur_ms, timestamp=ts,
                log_excerpt=_excerpt(lines, i), raw_line=raw.rstrip(),
                call_number=counters[fn],
            ))

        return results or HeuristicParser().parse(lines)


class RailsParser:
    """
    Rails request logs:
      Started GET "/api/users" for 127.0.0.1 at 2024-03-19 10:32:01 +0000
      Processing by UsersController#index as JSON
      Completed 200 OK in 1234ms (Views: 12.3ms | ActiveRecord: 890ms)
    """
    _STARTED  = re.compile(
        r"Started\s+(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD)\s+\"(?P<path>[^\"]+)\".*"
        r"at\s+(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
        re.I,
    )
    _PROC     = re.compile(
        r"Processing by\s+(?P<ctrl>[A-Za-z0-9:]+#\w+)", re.I
    )
    _COMPLETED = re.compile(
        r"Completed\s+\d{3}[^i]*in\s+(?P<val>[\d.]+)\s*(?P<unit>ms|s)\b", re.I
    )
    # Sub-timings:  (Views: 12ms | ActiveRecord: 890ms)
    _SUB = re.compile(r"(?P<key>[A-Za-z ]+):\s+(?P<val>[\d.]+)(?P<unit>ms|s)", re.I)

    def parse(self, lines: list[str]) -> list[UniversalLogRecord]:
        results: list[UniversalLogRecord] = []
        counters: dict[str, int] = {}

        i = 0
        while i < len(lines):
            sm = self._STARTED.search(lines[i])
            if sm:
                ts = _parse_iso(sm.group("ts").replace(" ", "T")) or _NOW
                path = sm.group("path")
                method = sm.group("method")
                fn = path  # default function label

                # Try to find controller name in subsequent lines
                for j in range(i + 1, min(i + 5, len(lines))):
                    pm = self._PROC.search(lines[j])
                    if pm:
                        fn = pm.group("ctrl")
                        break

                # Find the Completed line
                for j in range(i + 1, min(i + 20, len(lines))):
                    cm = self._COMPLETED.search(lines[j])
                    if cm:
                        dur_ms = _duration_to_ms(cm.group("val"), cm.group("unit"))
                        counters[fn] = counters.get(fn, 0) + 1
                        excerpt = "\n".join(l.rstrip() for l in lines[i:j+1])
                        results.append(UniversalLogRecord(
                            func_name=fn, duration_ms=dur_ms, timestamp=ts,
                            log_excerpt=excerpt, raw_line=lines[j].rstrip(),
                            call_number=counters[fn],
                        ))
                        # Also extract sub-timings
                        for sub in self._SUB.finditer(lines[j]):
                            sfn = f"{fn}:{sub.group('key').strip()}"
                            sdur = _duration_to_ms(sub.group("val"), sub.group("unit"))
                            counters[sfn] = counters.get(sfn, 0) + 1
                            results.append(UniversalLogRecord(
                                func_name=sfn, duration_ms=sdur, timestamp=ts,
                                log_excerpt=lines[j].rstrip(), raw_line=lines[j].rstrip(),
                                call_number=counters[sfn],
                            ))
                        i = j
                        break
            i += 1

        return results or HeuristicParser().parse(lines)


class TsharkParser:
    _FUNC_DUR = re.compile(
        r"(?P<func>[a-z_][a-z0-9_.:\-]*)\s+elapsed\s*=\s*(?P<val>[\d.]+)\s*"
        r"(?P<unit>ms|s|us|μs)?\b",
        re.I,
    )
    _FIELDS = re.compile(r"^[\d.]+\t")

    def parse(self, lines: list[str]) -> list[UniversalLogRecord]:
        results: list[UniversalLogRecord] = []
        counters: dict[str, int] = {}
        _base = _NOW

        for i, raw in enumerate(lines):
            m = self._FUNC_DUR.search(raw)
            if m:
                fn  = m.group("func")
                dur_ms = _duration_to_ms(m.group("val"), m.group("unit") or "s")
                ts  = _extract_iso_ts(raw) or _base
                counters[fn] = counters.get(fn, 0) + 1
                results.append(UniversalLogRecord(
                    func_name=fn, duration_ms=dur_ms, timestamp=ts,
                    log_excerpt=_excerpt(lines, i, 2, 0), raw_line=raw.rstrip(),
                    call_number=counters[fn],
                ))
                continue

            if self._FIELDS.match(raw):
                parts = raw.strip().split("\t")
                try:
                    rel_s = float(parts[0])
                    dur_ms = max(1, int(rel_s * 1000))
                except (ValueError, IndexError):
                    continue
                fn = (parts[1].strip() if len(parts) > 1 else "frame") or "frame"
                counters[fn] = counters.get(fn, 0) + 1
                results.append(UniversalLogRecord(
                    func_name=fn, duration_ms=dur_ms, timestamp=_base,
                    log_excerpt=raw.rstrip(), raw_line=raw.rstrip(),
                    call_number=counters[fn],
                ))

        return results or HeuristicParser().parse(lines)


class EnterExitParser:
    """
    General paired ENTER / EXIT tracing.  Handles many conventions:
      TRACE > myFunc          /  TRACE < myFunc
      --> processPayment      /  <-- processPayment (1234ms)
      [ENTER] func_name       /  [EXIT] func_name
      >>> methodName          /  <<< methodName : 456ms
      calling methodName      /  returning methodName
    """
    _ENTER = re.compile(
        r"(?:ENTER|START|BEGIN|>+|→+|\[ENTER\]|\[START\]|calling|entered?|invoke[ds]?)\s*"
        r"[:\s]*(?P<func>[A-Za-z_]\w{2,})\b",
        re.I,
    )
    _EXIT = re.compile(
        r"(?:EXIT|END|FINISH|RETURN|<+|←+|\[EXIT\]|\[END\]|returning|exited?|return(?:ed|ing)?)\s*"
        r"[:\s]*(?P<func>[A-Za-z_]\w{2,})\b"
        r"(?:.*?(?:in|took|elapsed|\()[:\s]*(?P<val>[\d.]+)\s*(?P<unit>ms|s|us))?",
        re.I,
    )

    def parse(self, lines: list[str]) -> list[UniversalLogRecord]:
        results: list[UniversalLogRecord] = []
        stack: dict[str, tuple[datetime, int]] = {}
        counters: dict[str, int] = {}

        for i, raw in enumerate(lines):
            ts = _extract_iso_ts(raw) or _NOW

            em = self._ENTER.search(raw)
            if em:
                fn = em.group("func")
                stack[fn] = (ts, i)
                continue

            xm = self._EXIT.search(raw)
            if xm:
                fn = xm.group("func")
                if fn in stack:
                    enter_ts, enter_idx = stack.pop(fn)
                    if xm.group("val"):
                        dur_ms = _duration_to_ms(xm.group("val"), xm.group("unit") or "ms")
                    else:
                        dur_ms = max(0, int((ts - enter_ts).total_seconds() * 1000))
                    counters[fn] = counters.get(fn, 0) + 1
                    excerpt = "\n".join(l.rstrip() for l in lines[max(0, enter_idx-1):i+2])
                    results.append(UniversalLogRecord(
                        func_name=fn, duration_ms=dur_ms, timestamp=enter_ts,
                        log_excerpt=excerpt, raw_line=raw.rstrip(),
                        call_number=counters[fn],
                    ))

        return results


class HeuristicParser:
    """
    Last-resort fallback.  Looks for lines like:
      "parse_frame took 12.3ms"
      "handle_request elapsed 456ms"
      "reassemble_stream: 200ms"
      "completed in 1.2s: process_packet"
    """
    _DIRECT = re.compile(
        r"\b(?P<func>[a-z_]\w{2,})\s+"
        r"(?:took|elapsed|duration|latency|time|finished in|completed in)"
        r"[\s:=]*(?P<val>[\d.]+)\s*(?P<unit>ms|s|sec|us|μs|ns|m(?:in)?)\b",
        re.I,
    )
    _REVERSE = re.compile(
        r"(?:took|elapsed|duration|completed in|finished in|latency)"
        r"[\s:=]*(?P<val>[\d.]+)\s*(?P<unit>ms|s|sec|us|μs|ns|m(?:in)?)\b"
        r"[^a-z_]*(?P<func>[a-z_]\w{2,})\b",
        re.I,
    )
    _COLON = re.compile(
        r"\b(?P<func>[a-z_]\w{2,}):\s*(?P<val>[\d.]+)\s*(?P<unit>ms|s|sec|us|μs|ns)\b",
        re.I,
    )
    _SKIP = frozenset({
        "the","in","at","by","on","for","to","and","not","with","from","into",
        "done","took","elapsed","duration","time","latency","sec","second",
        "seconds","minute","total","http","api",
    })

    def parse(self, lines: list[str]) -> list[UniversalLogRecord]:
        results: list[UniversalLogRecord] = []
        counters: dict[str, int] = {}

        for i, raw in enumerate(lines):
            m = (
                self._DIRECT.search(raw)
                or self._COLON.search(raw)
                or self._REVERSE.search(raw)
            )
            if not m: continue
            gd = m.groupdict()
            fn  = gd.get("func", "").strip()
            val = gd.get("val", "0")
            unit = gd.get("unit", "ms")
            if not fn or fn.lower() in self._SKIP: continue
            if re.fullmatch(r"\d+", fn) or re.fullmatch(r"[vV]\d+", fn): continue
            dur_ms = _duration_to_ms(val, unit)
            ts = _extract_iso_ts(raw) or _NOW
            counters[fn] = counters.get(fn, 0) + 1
            results.append(UniversalLogRecord(
                func_name=fn, duration_ms=dur_ms, timestamp=ts,
                log_excerpt=_excerpt(lines, i, 1, 1), raw_line=raw.rstrip(),
                call_number=counters[fn],
            ))

        return results


class CustomPatternParser:
    """User-supplied named-group regex."""
    _ENTER_EV = frozenset(("start","begin","enter","call","open","invoke"))
    _EXIT_EV  = frozenset(("end","done","finish","exit","return","close","complete"))

    def parse(self, lines: list[str], pattern: str) -> list[UniversalLogRecord]:
        results: list[UniversalLogRecord] = []
        pending: dict[str, tuple[datetime, str]] = {}
        counters: dict[str, int] = {}
        try:
            rx = re.compile(pattern, re.I)
        except re.error:
            return HeuristicParser().parse(lines)

        for i, raw in enumerate(lines):
            m = rx.search(raw)
            if not m: continue
            gd = m.groupdict()
            fn = gd.get("func", "").strip()
            if not fn: continue
            ts_raw = gd.get("timestamp", "")
            ts = _parse_iso(ts_raw) if ts_raw else _NOW

            dur_raw = gd.get("duration")
            if dur_raw is not None:
                unit = gd.get("unit") or "ms"
                dur_ms = _duration_to_ms(dur_raw, unit)
                counters[fn] = counters.get(fn, 0) + 1
                results.append(UniversalLogRecord(
                    func_name=fn, duration_ms=dur_ms, timestamp=ts,
                    log_excerpt=raw.rstrip(), raw_line=raw.rstrip(),
                    call_number=counters[fn],
                ))
                continue

            event = (gd.get("event") or "").lower()
            if any(e in event for e in self._ENTER_EV):
                pending[fn] = (ts, raw.rstrip())
            elif any(e in event for e in self._EXIT_EV) and fn in pending:
                st, sr = pending.pop(fn)
                dur_ms = max(0, int((ts - st).total_seconds() * 1000))
                counters[fn] = counters.get(fn, 0) + 1
                results.append(UniversalLogRecord(
                    func_name=fn, duration_ms=dur_ms, timestamp=st,
                    log_excerpt=sr + "\n" + raw.rstrip(), raw_line=raw.rstrip(),
                    call_number=counters[fn],
                ))

        return results


# ═══════════════════════════════════════════════════════════════════════════════
# AppLogParser  –  backward-compat entry point used by AppIngester
# ═══════════════════════════════════════════════════════════════════════════════

_DETECTOR = FormatDetector()
_PARSERS: dict[str, object] = {
    "json":       JsonLogParser(),
    "syslog":     SyslogParser(),
    "logfmt":     LogfmtParser(),
    "spring":     SpringBootParser(),
    "rails":      RailsParser(),
    "tshark":     TsharkParser(),
    "enter_exit": EnterExitParser(),
}


def detect_format(lines: list[str]) -> tuple[str, float]:
    """Thin wrapper: returns (format_name, confidence)."""
    return _DETECTOR.detect(lines)


def parse_to_universal(
    lines: list[str],
    *,
    fmt: str = "auto",
    custom_pattern: str = "",
) -> tuple[str, list[UniversalLogRecord]]:
    """
    Parse lines → list[UniversalLogRecord].
    Returns (detected_format, records).
    """
    if fmt in ("auto", "unknown"):
        fmt, _ = _DETECTOR.detect(lines)
    if fmt in ("unknown", "heuristic", ""):
        fmt = "heuristic"

    if fmt == "custom" and custom_pattern:
        return fmt, CustomPatternParser().parse(lines, custom_pattern)

    parser = _PARSERS.get(fmt)
    if parser:
        return fmt, parser.parse(lines)
    return "heuristic", HeuristicParser().parse(lines)


class AppLogParser:
    """
    Backward-compatible wrapper for AppIngester.
    Returns list[ParsedFunctionCall] (same type as Phase 1/2).
    """

    def detect_format(self, lines: list[str]) -> str:
        fmt, _ = _DETECTOR.detect(lines)
        return fmt

    def parse(
        self,
        lines: list[str],
        *,
        fmt: str = "auto",
        custom_pattern: str = "",
    ) -> list[ParsedFunctionCall]:
        detected_fmt, records = parse_to_universal(
            lines, fmt=fmt, custom_pattern=custom_pattern
        )
        return [_ulr_to_parsed(r) for r in records]

    # keep legacy method names so nothing breaks
    def parse_json_logs(self, lines):
        return [_ulr_to_parsed(r) for r in JsonLogParser().parse(lines)]
    def parse_tshark(self, lines):
        return [_ulr_to_parsed(r) for r in TsharkParser().parse(lines)]
    def parse_syslog(self, lines):
        return [_ulr_to_parsed(r) for r in SyslogParser().parse(lines)]
    def parse_logfmt(self, lines):
        return [_ulr_to_parsed(r) for r in LogfmtParser().parse(lines)]
    def parse_heuristic(self, lines):
        return [_ulr_to_parsed(r) for r in HeuristicParser().parse(lines)]
    def parse_custom(self, lines, pattern):
        return [_ulr_to_parsed(r) for r in CustomPatternParser().parse(lines, pattern)]
