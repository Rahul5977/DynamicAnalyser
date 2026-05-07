"""
app_trace_correlator.py
-----------------------
Maps AppFunctionCall rows back to source code locations.

Since the log already contains the real function name (unlike CI/CD steps
where we only have a step label), correlation is simpler:

  1. Exact name match → IndexedFunction.function_name
  2. Normalised match → strip `()`, module prefixes, leading underscores
  3. Fuzzy match      → difflib ratio ≥ threshold
  4. No match         → leave source_* columns NULL

After correlation, call_chain_json is filled from the reverse call-graph
stored in the CodeIndex, giving callers of the slow function.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.logging import logger
from app.models.database import AppFunctionCall, AppLogSession, IndexedFunction, CodeIndex
from app.models.schemas import AppTraceResponse, CorrelatedCallResponse


@dataclass
class CorrelatedCall:
    call_id:         int
    function_name:   str
    duration_ms:     int
    source_function: str | None = None
    source_file:     str | None = None
    source_line:     int | None = None
    call_chain:      list[dict] = field(default_factory=list)
    log_excerpt:     str | None = None
    match_method:    str | None = None   # "exact" | "normalised" | "fuzzy" | None


def _normalise(name: str) -> str:
    """Remove parens, leading underscores, module prefixes for fuzzy compare."""
    name = re.sub(r"\(.*\)", "", name).strip()
    name = name.lstrip("_")
    name = name.rsplit(".", 1)[-1]     # strip module prefix
    name = name.rsplit("::", 1)[-1]   # strip C++ / Rust :: prefix
    return name.lower()


# Token aliases for tshark-style labels vs Wireshark C symbols (attach_req, etc.)
_TOKEN_ALIASES = {
    "request": "req",
    "response": "rsp",
    "command": "cmd",
    "failure": "fail",
    "security": "sec",
    "information": "info",
    "authentication": "auth",
    # TLS/SSL — Wireshark historically named TLS as "ssl" internally
    "tls": "ssl",
    "ssl": "tls",
    # Wireshark analysis function naming conventions
    "analysis": "analyze",
    "analyze": "analysis",
    "retransmission": "retransmit",
    "retransmit": "retransmission",
    "check": "verify",
    "segment": "seq",
}


def _expand_token(t: str) -> set[str]:
    t = t.lower()
    out = {t}
    if t in _TOKEN_ALIASES:
        out.add(_TOKEN_ALIASES[t])
    for long, short in _TOKEN_ALIASES.items():
        if short == t:
            out.add(long)
    return out


def _log_tokens(label: str) -> list[str]:
    """Split synthetic log labels (e.g. dissect_nas_attach_request) into tokens."""
    raw = re.sub(r"^dissect_", "", label, flags=re.I)
    raw = re.sub(r"^(diameter|gtpv2)_", "", raw, flags=re.I)
    return [p for p in re.split(r"[^a-z0-9]+", raw.lower()) if len(p) > 1]


def _path_substrings_for_label(log_label: str) -> list[str] | None:
    """
    If the log label maps to a protocol family, return substrings that must
    appear in IndexedFunction.file_path for token matching. None = no filter
    (fall back to scanning the first N functions only).
    """
    t = log_label.lower()
    if "dissect_nas" in t or t.startswith("nas_"):
        return [
            "nas_eps",
            "nas-5gs",
            "nas_5gs",
            "nas-5gs",
            "packet-nas",
            "packet-gsm_a",
            "lte_rrc",
        ]
    if t.startswith("diameter_") or t.startswith("diameter"):
        return ["diameter", "dcca"]
    if "gtpv2" in t or t.startswith("gtp"):
        return ["gtp", "packet-gtp"]
    if "tcp_retransmission" in t:
        return ["tcp", "reassembl"]
    if "dns_retransmission" in t:
        return ["dns"]
    if "out_of_order" in t:
        return ["tcp", "reassembl", "packet-tcp"]
    return None


def _file_matches_path_hint(file_path: str, substrings: list[str]) -> bool:
    fp = file_path.lower()
    return any(s.lower() in fp for s in substrings)


def _canonical_file_score(func_name: str, file_path: str) -> int:
    """
    Score how "canonical" a file is for a given function name.

    When many files define the same symbol (e.g. every Wireshark dissector
    declares a local ``dissect_tcp`` wrapper), we need to pick the one most
    likely to be the *main* implementation.  Strategy:
      +3  file's stem exactly equals the protocol token(s) from the name
      +2  file's stem contains all protocol tokens
      +1  any protocol token appears anywhere in the path
      -1  file is a header (.h) — prefer .c source
    Examples:
      ``dissect_tcp`` vs ``packet-tcp.c``    →  +3  ✓
      ``dissect_tcp`` vs ``packet-synphasor.c`` → 0  ✗
      ``dissect_frame`` vs ``packet-frame.c``   →  +3  ✓
    """
    # Extract the protocol portion: strip leading "dissect_", "diameter_", etc.
    proto_raw = re.sub(r"^(dissect|tcp|diameter|gtpv[12])_+", "", func_name, flags=re.I)
    tokens = [t for t in re.split(r"[^a-z0-9]+", proto_raw.lower()) if len(t) > 1]
    if not tokens:
        return 0

    stem = os.path.splitext(os.path.basename(file_path))[0].lower()
    # strip "packet-" prefix common in Wireshark
    stem_clean = re.sub(r"^packet-", "", stem)

    score = 0
    if all(t in stem_clean for t in tokens):
        score += 3 if stem_clean == "_".join(tokens) or stem_clean == tokens[0] else 2
    else:
        if any(t in file_path.lower() for t in tokens):
            score += 1

    if file_path.endswith(".h"):
        score -= 1
    return score


def _token_overlap_score(log_label: str, symbol_name: str) -> float:
    """Jaccard similarity on token sets with light alias expansion."""
    ta: set[str] = set()
    for t in _log_tokens(log_label):
        ta |= _expand_token(t)
    tb: set[str] = set()
    for t in _log_tokens(symbol_name):
        tb |= _expand_token(t)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    uni = len(ta | tb)
    return inter / uni if uni else 0.0


class AppTraceCorrelator:
    """Correlates an AppLogSession's function calls with source code."""

    def __init__(self, db: Session):
        self.db = db
        self._settings = get_settings()

    # ── Public API ────────────────────────────────────────────────────────────

    def correlate_session(self, session_id: int) -> AppTraceResponse:
        """
        Run correlation for all calls in the session.

        Writes source_function / source_file / source_line / call_chain_json
        back to AppFunctionCall rows, then returns a summary.
        """
        session: AppLogSession = self.db.get(AppLogSession, session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        calls = (
            self.db.query(AppFunctionCall)
            .filter(AppFunctionCall.session_id == session_id)
            .order_by(AppFunctionCall.duration_ms.desc())
            .all()
        )
        if not calls:
            return self._empty_response(session)

        # Load code index for the session's source repo
        code_index, indexed_funcs = self._load_index(session)
        idx_sha = code_index.commit_sha if code_index else None
        if not indexed_funcs:
            logger.info(
                "AppTraceCorrelator: no code index for session %d "
                "(source_repo=%s) — skipping correlation",
                session_id, session.source_repo,
            )
            return self._build_response(session, calls, matched=0, commit_sha=idx_sha)

        # Build lookup structures
        func_by_name:      dict[str, list[IndexedFunction]] = {}
        func_by_norm:      dict[str, list[IndexedFunction]] = {}
        # reverse_call_graph: callee → list of caller names
        reverse_cg: dict[str, list[str]] = {}

        for fn in indexed_funcs:
            # Forward index
            func_by_name.setdefault(fn.function_name, []).append(fn)
            func_by_norm.setdefault(_normalise(fn.function_name), []).append(fn)
            # Build reverse call graph from calls_json
            if fn.calls_json:
                try:
                    callees = json.loads(fn.calls_json)
                    for callee in callees:
                        reverse_cg.setdefault(callee, []).append(fn.function_name)
                except (json.JSONDecodeError, TypeError):
                    pass

        # ── Deduplicated match: compute _match_function once per unique name ──
        # A log file with 46 K calls typically has only ~20-50 unique function
        # names.  Running fuzzy matching on every single call row would be
        # O(total_calls × index_size) — e.g. 46,873 × 8,000 = 374 M difflib
        # ops.  Caching by name reduces this to O(unique_names × index_size).
        unique_log_names: list[str] = list({c.function_name for c in calls})
        match_cache: dict[str, tuple[IndexedFunction | None, str | None, list[dict]]] = {}

        for log_name in unique_log_names:
            best, method = self._match_function(
                log_name, func_by_name, func_by_norm, indexed_funcs
            )
            chain: list[dict] = []
            if best:
                chain = self._build_call_chain(best.function_name, reverse_cg, indexed_funcs)
            match_cache[log_name] = (best, method, chain)

        # Apply cached results to every call row
        matched = 0
        correlated: list[CorrelatedCall] = []

        for call in calls:
            best, method, chain = match_cache[call.function_name]

            if best:
                matched += 1
                # Write back to DB
                call.source_function = best.function_name
                call.source_file     = best.file_path
                call.source_line     = best.line_number
                call.call_chain_json = json.dumps(chain)

            correlated.append(CorrelatedCall(
                call_id=call.id,
                function_name=call.function_name,
                duration_ms=call.duration_ms,
                source_function=best.function_name if best else None,
                source_file=best.file_path if best else None,
                source_line=best.line_number if best else None,
                call_chain=chain,
                log_excerpt=call.log_excerpt,
                match_method=method,
            ))

        self.db.commit()
        logger.info(
            "AppTraceCorrelator: session %d — %d/%d calls correlated",
            session_id, matched, len(calls),
        )
        return self._build_response(
            session, calls, matched, correlated, commit_sha=idx_sha
        )

    # ── Private ───────────────────────────────────────────────────────────────

    def _load_index(
        self, session: AppLogSession
    ) -> tuple[CodeIndex | None, list[IndexedFunction]]:
        """Find the latest CodeIndex for this session's source_repo."""
        if not session.source_repo:
            return None, []

        repo_name = _parse_github_url(session.source_repo)
        if not repo_name:
            return None, []

        # Find matching TrackedRepository
        from app.models.database import TrackedRepository
        tracked = (
            self.db.query(TrackedRepository)
            .filter(TrackedRepository.full_name == repo_name)
            .first()
        )
        if not tracked:
            logger.info(
                "AppTraceCorrelator: repo '%s' not tracked — no code index", repo_name
            )
            return None, []

        code_index = (
            self.db.query(CodeIndex)
            .filter(
                CodeIndex.repository_id == tracked.id,
                CodeIndex.status == "completed",
            )
            .order_by(CodeIndex.created_at.desc())
            .first()
        )
        if not code_index:
            return None, []

        funcs_raw = (
            self.db.query(IndexedFunction)
            .filter(IndexedFunction.code_index_id == code_index.id)
            .all()
        )
        # Deduplicate by (function_name, file_path) — duplicate rows can
        # accumulate when re-indexing is retried without clearing prior rows.
        seen: set[tuple[str, str]] = set()
        funcs: list[IndexedFunction] = []
        for f in funcs_raw:
            key = (f.function_name, f.file_path)
            if key not in seen:
                seen.add(key)
                funcs.append(f)

        return code_index, funcs

    def _match_function(
        self,
        target: str,
        by_name: dict[str, list[IndexedFunction]],
        by_norm: dict[str, list[IndexedFunction]],
        all_funcs: list[IndexedFunction],
    ) -> tuple[IndexedFunction | None, str | None]:
        """Try exact → normalised → fuzzy matching."""
        # 1. Exact — when multiple files define the same symbol, prefer the
        #    most canonical file (e.g. packet-tcp.c over packet-synphasor.c
        #    for dissect_tcp).
        if target in by_name:
            candidates = by_name[target]
            if len(candidates) == 1:
                return candidates[0], "exact"
            best = max(candidates, key=lambda fn: _canonical_file_score(target, fn.file_path))
            return best, "exact"

        # 2. Normalised — same file preference
        norm = _normalise(target)
        if norm in by_norm:
            candidates = by_norm[norm]
            if len(candidates) == 1:
                return candidates[0], "normalised"
            best = max(candidates, key=lambda fn: _canonical_file_score(target, fn.file_path))
            return best, "normalised"

        # 3. Fuzzy — scan a larger prefix (order is DB-defined; cap for CPU)
        threshold = self._settings.FUZZY_MATCH_THRESHOLD
        best_score = 0.0
        best_fn: IndexedFunction | None = None
        fuzzy_cap = min(8000, len(all_funcs))
        for fn in all_funcs[:fuzzy_cap]:
            score = difflib.SequenceMatcher(
                None, norm, _normalise(fn.function_name)
            ).ratio()
            if score > best_score:
                best_score, best_fn = score, fn

        if best_score >= threshold and best_fn:
            return best_fn, "fuzzy"

        # 4. Token overlap (tshark / synthetic labels vs real C names)
        best_tok = 0.0
        best_tfn: IndexedFunction | None = None
        path_hints = _path_substrings_for_label(target)
        if path_hints:
            pool = [
                fn for fn in all_funcs
                if _file_matches_path_hint(fn.file_path, path_hints)
            ]
            if not pool:
                pool = all_funcs[: min(25_000, len(all_funcs))]
        else:
            pool = all_funcs[: min(25_000, len(all_funcs))]
        pool = pool[: min(60_000, len(pool))]

        for fn in pool:
            s = _token_overlap_score(target, fn.function_name)
            if s > best_tok:
                best_tok, best_tfn = s, fn
        if best_tok >= 0.52 and best_tfn:
            return best_tfn, "token_overlap"
        return None, None

    def _build_call_chain(
        self,
        func_name: str,
        reverse_cg: dict[str, list[str]],
        all_funcs: list[IndexedFunction],
    ) -> list[dict]:
        """Return up to 5 callers of func_name, each with file+line."""
        func_index = {f.function_name: f for f in all_funcs}
        callers = reverse_cg.get(func_name, [])[:5]
        chain = []
        for caller_name in callers:
            info = func_index.get(caller_name)
            chain.append({
                "function_name": caller_name,
                "file_path": info.file_path if info else "",
                "line_number": info.line_number if info else 0,
            })
        return chain

    def _empty_response(self, session: AppLogSession) -> AppTraceResponse:
        return AppTraceResponse(
            session_id=session.id,
            app_name=session.app_name,
            total_calls=0,
            matched_calls=0,
            match_rate=0.0,
            source_commit_sha=None,
        )

    def _build_response(
        self,
        session: AppLogSession,
        calls: list[AppFunctionCall],
        matched: int,
        correlated: list[CorrelatedCall] | None = None,
        *,
        commit_sha: str | None = None,
    ) -> AppTraceResponse:
        total = len(calls)
        rate = matched / total if total else 0.0

        resp_calls = []
        if correlated:
            for c in correlated:
                resp_calls.append(CorrelatedCallResponse(
                    id=c.call_id,
                    function_name=c.function_name,
                    duration_ms=c.duration_ms,
                    source_function=c.source_function,
                    source_file=c.source_file,
                    source_line=c.source_line,
                    call_chain=c.call_chain,
                    log_excerpt=c.log_excerpt,
                    match_method=c.match_method,
                ))
        else:
            for call in calls:
                resp_calls.append(CorrelatedCallResponse(
                    id=call.id,
                    function_name=call.function_name,
                    duration_ms=call.duration_ms,
                    log_excerpt=call.log_excerpt,
                    match_method=None,
                ))

        return AppTraceResponse(
            session_id=session.id,
            app_name=session.app_name,
            total_calls=total,
            matched_calls=matched,
            match_rate=round(rate, 3),
            calls=resp_calls,
            source_commit_sha=commit_sha,
        )


def _parse_github_url(url: str) -> str | None:
    """Extract 'owner/repo' from various GitHub URL forms."""
    # https://github.com/owner/repo  or  git@github.com:owner/repo.git
    patterns = [
        re.compile(r"github\.com[:/]([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+?)(?:\.git)?$"),
    ]
    for p in patterns:
        m = p.search(url)
        if m:
            return m.group(1)
    # Already in owner/repo format?
    if re.fullmatch(r"[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+", url):
        return url
    return None


def get_index_commit_sha_for_session(db: Session, session: AppLogSession) -> str | None:
    """Latest completed CodeIndex commit SHA for this session's source_repo."""
    from app.models.database import TrackedRepository, CodeIndex

    if not session.source_repo:
        return None
    repo_name = _parse_github_url(session.source_repo)
    if not repo_name:
        return None
    tracked = (
        db.query(TrackedRepository)
        .filter(TrackedRepository.full_name == repo_name)
        .first()
    )
    if not tracked:
        return None
    code_index = (
        db.query(CodeIndex)
        .filter(
            CodeIndex.repository_id == tracked.id,
            CodeIndex.status == "completed",
        )
        .order_by(CodeIndex.created_at.desc())
        .first()
    )
    return code_index.commit_sha if code_index else None
