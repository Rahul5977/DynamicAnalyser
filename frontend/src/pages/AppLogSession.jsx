import React, { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getAppSession,
  getAppSessionAnalysis,
  analyseAppSession,
  getAppTrace,
  indexSourceForSession,
  submitFeedback,
} from "../services/api";
import SuggestionCard from "../components/SuggestionCard";
import KPICard from "../components/KPICard";
import StatusBadge from "../components/StatusBadge";

function formatMs(ms) {
  if (ms === null || ms === undefined) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

function pct(part, total) {
  if (!total) return "—";
  return `${((part / total) * 100).toFixed(1)}%`;
}

function barColor(v, max) {
  const r = v / (max || 1);
  return r > 0.7 ? "#ef4444" : r > 0.35 ? "#f59e0b" : "#22c55e";
}

/** Build a GitHub blob URL from a repo URL, file path, and line number. */
function githubFileUrl(sourceRepo, filePath, lineNumber) {
  if (!sourceRepo || !filePath) return null;
  // Normalise: accept https://github.com/owner/repo or owner/repo
  let base = sourceRepo.replace(/\.git$/, "").replace(/\/$/, "");
  if (!base.startsWith("http")) base = `https://github.com/${base}`;
  const line = lineNumber ? `#L${lineNumber}` : "";
  return `${base}/blob/main/${filePath}${line}`;
}

// ── Source location badge ─────────────────────────────────────────────────────

function SourceBadge({ sourceFile, sourceLine, sourceRepo }) {
  if (!sourceFile) return null;
  const label = `${sourceFile.split("/").slice(-1)[0]}:${sourceLine || "?"}`;
  const url = githubFileUrl(sourceRepo, sourceFile, sourceLine);

  const style = {
    display: "inline-block",
    fontSize: 11,
    padding: "1px 6px",
    borderRadius: 4,
    background: "rgba(99,102,241,.15)",
    color: "var(--color-primary, #6366f1)",
    fontFamily: "monospace",
    whiteSpace: "nowrap",
    textDecoration: "none",
    border: "1px solid rgba(99,102,241,.3)",
    marginLeft: 6,
  };

  return url ? (
    <a href={url} target="_blank" rel="noreferrer" style={style} title={`${sourceFile}:${sourceLine}`}>
      {label}
    </a>
  ) : (
    <span style={style} title={`${sourceFile}:${sourceLine}`}>{label}</span>
  );
}

// ── Flamebar ──────────────────────────────────────────────────────────────────

function FlameBar({ value, max }) {
  const w = max ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div style={{ height: 8, background: "var(--border)", borderRadius: 4, overflow: "hidden", minWidth: 80 }}>
      <div style={{ height: "100%", width: `${w}%`, background: barColor(value, max), borderRadius: 4 }} />
    </div>
  );
}

// ── Time-breakdown flamegraph with source badges ───────────────────────────────

function TimeBreakdown({ calls, totalMs, sourceRepo }) {
  // Aggregate by function name, keeping first source info seen
  const byFunc = {};
  for (const c of calls) {
    if (!byFunc[c.function_name]) {
      byFunc[c.function_name] = {
        total: 0,
        source_file: c.source_file || null,
        source_line: c.source_line || null,
      };
    }
    byFunc[c.function_name].total += c.duration_ms;
  }
  const top = Object.entries(byFunc).sort((a, b) => b[1].total - a[1].total).slice(0, 10);
  const maxFuncMs = top[0]?.[1].total || 1;

  return (
    <div className="card">
      <div className="card-title">Time breakdown — top functions</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {top.map(([fn, info]) => (
          <div key={fn} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {/* Function name + source badge */}
            <div style={{ minWidth: 240, maxWidth: 240, display: "flex", alignItems: "center" }}>
              <span style={{
                fontSize: 13, fontFamily: "monospace",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                maxWidth: info.source_file ? 160 : 240,
              }}>
                {fn}
              </span>
              {info.source_file && (
                <SourceBadge
                  sourceFile={info.source_file}
                  sourceLine={info.source_line}
                  sourceRepo={sourceRepo}
                />
              )}
            </div>
            {/* Bar */}
            <div style={{ flex: 1, height: 18, background: "var(--border)", borderRadius: 4, overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: `${(info.total / maxFuncMs) * 100}%`,
                background: barColor(info.total, totalMs),
                borderRadius: 4,
              }} />
            </div>
            {/* Label */}
            <div style={{ minWidth: 120, textAlign: "right", fontSize: 13, color: "var(--text-muted)" }}>
              {formatMs(info.total)} ({pct(info.total, totalMs)})
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Source trace panel ────────────────────────────────────────────────────────

function SourceTrace({ sessionId, sourceRepo }) {
  const [trace, setTrace]       = useState(null);
  const [loading, setLoading]   = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [error, setError]       = useState(null);
  const [ghUrl, setGhUrl]       = useState(sourceRepo || "");

  const loadTrace = async () => {
    setLoading(true); setError(null);
    try { setTrace(await getAppTrace(sessionId)); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleIndex = async () => {
    setIndexing(true); setError(null);
    try { await indexSourceForSession(sessionId, ghUrl); await loadTrace(); }
    catch (e) { setError(e.message); }
    finally { setIndexing(false); }
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="card-title" style={{ margin: 0 }}>Source Correlation</div>
        <button className="btn btn-sm btn-secondary" onClick={loadTrace} disabled={loading}>
          {loading ? "Loading…" : "Correlate"}
        </button>
      </div>

      {!sourceRepo && (
        <div style={{ marginTop: 12 }}>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 8 }}>
            No source repo linked. Add a GitHub URL to map slow functions to source lines.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="url"
              placeholder="https://github.com/owner/repo"
              value={ghUrl}
              onChange={(e) => setGhUrl(e.target.value)}
              style={{
                flex: 1, padding: "6px 12px", borderRadius: 6,
                border: "1px solid var(--border)",
                background: "var(--bg-input, var(--bg-card))",
                color: "inherit", fontSize: 13,
              }}
            />
            <button
              className="btn btn-sm btn-primary"
              onClick={handleIndex}
              disabled={indexing || !ghUrl}
            >
              {indexing ? "Indexing…" : "Index & Correlate"}
            </button>
          </div>
        </div>
      )}

      {error && <div className="error-msg" style={{ marginTop: 12 }}>{error}</div>}

      {trace && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 12 }}>
            {trace.matched_calls} / {trace.total_calls} calls matched to source
            ({Math.round(trace.match_rate * 100)}%)
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Function</th><th>Duration</th><th>Source location</th><th>Callers</th>
                </tr>
              </thead>
              <tbody>
                {trace.calls.filter((c) => c.source_file).slice(0, 30).map((c) => {
                  const url = githubFileUrl(sourceRepo, c.source_file, c.source_line);
                  return (
                    <tr key={c.id}>
                      <td><code style={{ fontSize: 13 }}>{c.function_name}</code></td>
                      <td style={{ fontWeight: 600 }}>{formatMs(c.duration_ms)}</td>
                      <td style={{ fontSize: 12 }}>
                        {url ? (
                          <a href={url} target="_blank" rel="noreferrer"
                            style={{ fontFamily: "monospace", color: "var(--color-primary,#6366f1)" }}>
                            {c.source_file.split("/").slice(-2).join("/")}:{c.source_line}
                          </a>
                        ) : (
                          <span style={{ fontFamily: "monospace", color: "var(--text-muted)" }}>
                            {c.source_file}:{c.source_line}
                          </span>
                        )}
                      </td>
                      <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                        {c.call_chain?.length
                          ? c.call_chain.map((e) => e.function_name).join(" → ")
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── AI Analysis panel ─────────────────────────────────────────────────────────

function AIAnalysisPanel({ sessionId, sessionStatus }) {
  const [analysis, setAnalysis]     = useState(null);
  const [loading, setLoading]       = useState(false);
  const [analysing, setAnalysing]   = useState(false);
  const [polling, setPolling]       = useState(false);
  const [error, setError]           = useState(null);
  const [feedbackSent, setFeedbackSent] = useState({});
  const pollRef = useRef(null);

  // Load existing analysis on mount
  useEffect(() => {
    setLoading(true);
    getAppSessionAnalysis(sessionId)
      .then(setAnalysis)
      .catch(() => {})
      .finally(() => setLoading(false));
    return () => clearInterval(pollRef.current);
  }, [sessionId]);

  const startPolling = (startedId) => {
    setPolling(true);
    pollRef.current = setInterval(async () => {
      try {
        const a = await getAppSessionAnalysis(sessionId);
        if (a.status === "completed" || a.status === "failed") {
          clearInterval(pollRef.current);
          setPolling(false);
          setAnalysing(false);
          setAnalysis(a);
        }
      } catch (_) {}
    }, 2000);
  };

  const handleAnalyse = async (force = false) => {
    setAnalysing(true); setError(null);
    try {
      const result = await analyseAppSession(sessionId, force);
      if (result.status === "completed") {
        setAnalysis(result);
        setAnalysing(false);
      } else {
        startPolling(result.id);
      }
    } catch (e) {
      setError(e.message);
      setAnalysing(false);
    }
  };

  const handleFeedback = async (analysisId, suggestionId, verdict) => {
    try {
      await submitFeedback(analysisId, { suggestion_id: suggestionId, verdict });
      setFeedbackSent((prev) => ({ ...prev, [suggestionId]: verdict }));
    } catch (e) {
      console.error("Feedback failed:", e.message);
    }
  };

  const busy = analysing || polling;

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="card-title" style={{ margin: 0 }}>AI Performance Analysis</div>
        <div style={{ display: "flex", gap: 8 }}>
          {analysis && (
            <button
              className="btn btn-sm btn-secondary"
              onClick={() => handleAnalyse(true)}
              disabled={busy || sessionStatus !== "completed"}
            >
              Re-analyse
            </button>
          )}
          <button
            className="btn btn-sm btn-primary"
            onClick={() => handleAnalyse(false)}
            disabled={busy || loading || sessionStatus !== "completed"}
          >
            {polling ? "Analysing… (polling)" : analysing ? "Running…" : analysis ? "Analysis loaded" : "Run AI Analysis"}
          </button>
        </div>
      </div>

      {error && <div className="error-msg" style={{ marginTop: 12 }}>{error}</div>}

      {loading && (
        <div style={{ color: "var(--text-muted)", fontSize: 14, marginTop: 12 }}>
          Loading previous analysis…
        </div>
      )}

      {!analysis && !loading && !busy && (
        <p style={{ color: "var(--text-muted)", fontSize: 14, marginTop: 12 }}>
          Click "Run AI Analysis" to get root-cause insights and fix suggestions from Claude.
          Requires <code>ANTHROPIC_API_KEY</code> to be configured.
        </p>
      )}

      {analysis && (
        <div style={{ marginTop: 16 }}>
          <StatusBadge status={analysis.status} />

          {/* ── Root cause card ── */}
          {analysis.root_cause && (
            <div className="card" style={{ marginTop: 12, padding: "14px 16px" }}>
              <div className="card-title" style={{ margin: "0 0 8px" }}>Root cause</div>
              <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6 }}>{analysis.root_cause}</p>

              {/* KPI row */}
              <div className="kpi-grid" style={{ marginTop: 16, gridTemplateColumns: "repeat(3,1fr)" }}>
                <KPICard
                  label="Primary bottleneck"
                  value={analysis.primary_bottleneck || "—"}
                />
                <KPICard
                  label="Estimated saving"
                  value={formatMs(analysis.estimated_total_saving_ms)}
                />
                <KPICard
                  label="Anti-patterns found"
                  value={analysis.anti_patterns?.length ?? 0}
                />
              </div>
            </div>
          )}

          {/* Anti-pattern tags */}
          {analysis.anti_patterns?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Detected anti-patterns</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {analysis.anti_patterns.map((p, i) => (
                  <span key={i} style={{
                    fontSize: 12, padding: "3px 10px", borderRadius: 12,
                    background: "rgba(239,68,68,.15)", color: "#ef4444", fontWeight: 600,
                  }}>
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Suggestion cards — reuse SuggestionCard unchanged */}
          {analysis.suggestions?.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10 }}>
                Fix suggestions ({analysis.suggestions.length})
              </div>
              {analysis.suggestions.map((s) => (
                <div key={s.id} style={{ marginBottom: 12 }}>
                  <SuggestionCard
                    suggestion={s}
                    onFeedback={
                      !feedbackSent[s.id]
                        ? (sid, verdict) => handleFeedback(analysis.id, sid, verdict)
                        : undefined
                    }
                  />
                  {feedbackSent[s.id] && (
                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4, paddingLeft: 4 }}>
                      Feedback recorded: {feedbackSent[s.id]}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Function-calls table ──────────────────────────────────────────────────────

function CallsTable({ calls, totalMs, sourceRepo }) {
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("duration");
  const maxDur = calls.length ? Math.max(...calls.map((c) => c.duration_ms)) : 1;

  const visible = calls
    .filter((c) => !search || c.function_name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (sortBy === "name")        return a.function_name.localeCompare(b.function_name);
      if (sortBy === "call_number") return a.call_number - b.call_number;
      return b.duration_ms - a.duration_ms;
    });

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <div className="card-title" style={{ margin: 0 }}>
          Function Calls ({visible.length} of {calls.length})
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            placeholder="Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              padding: "5px 10px", borderRadius: 6, border: "1px solid var(--border)",
              background: "var(--bg-input, var(--bg-card))", color: "inherit",
              fontSize: 13, width: 160,
            }}
          />
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            style={{
              padding: "5px 10px", borderRadius: 6, border: "1px solid var(--border)",
              background: "var(--bg-input, var(--bg-card))", color: "inherit", fontSize: 13,
            }}
          >
            <option value="duration">Slowest first</option>
            <option value="name">Name A–Z</option>
            <option value="call_number">Call order</option>
          </select>
        </div>
      </div>

      {visible.length === 0 ? (
        <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
          {search ? "No calls match the search." : "No function calls parsed."}
        </p>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Function</th>
                  <th>Duration</th>
                  <th>% of total</th>
                  <th>Call #</th>
                  <th>Source</th>
                  <th>Excerpt</th>
                </tr>
              </thead>
              <tbody>
                {visible.slice(0, 300).map((c, i) => {
                  const url = githubFileUrl(sourceRepo, c.source_file, c.source_line);
                  return (
                    <tr key={c.id}>
                      <td style={{ color: "var(--text-muted)", fontSize: 12 }}>{i + 1}</td>
                      <td><code style={{ fontSize: 13 }}>{c.function_name}</code></td>
                      <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span>{formatMs(c.duration_ms)}</span>
                          <FlameBar value={c.duration_ms} max={maxDur} />
                        </div>
                      </td>
                      <td style={{ color: "var(--text-muted)", fontSize: 13 }}>
                        {pct(c.duration_ms, totalMs)}
                      </td>
                      <td style={{ color: "var(--text-muted)", fontSize: 13 }}>#{c.call_number}</td>
                      <td>
                        {c.source_file ? (
                          url ? (
                            <a href={url} target="_blank" rel="noreferrer"
                              style={{
                                fontSize: 11, fontFamily: "monospace",
                                padding: "1px 6px", borderRadius: 4,
                                background: "rgba(99,102,241,.12)",
                                color: "var(--color-primary,#6366f1)",
                                border: "1px solid rgba(99,102,241,.3)",
                                textDecoration: "none", whiteSpace: "nowrap",
                              }}
                            >
                              {c.source_file.split("/").slice(-1)[0]}:{c.source_line}
                            </a>
                          ) : (
                            <span style={{ fontSize: 12, fontFamily: "monospace", color: "var(--text-muted)" }}>
                              {c.source_file.split("/").slice(-1)[0]}:{c.source_line}
                            </span>
                          )
                        ) : "—"}
                      </td>
                      <td>
                        {c.log_excerpt ? (
                          <details>
                            <summary style={{ cursor: "pointer", fontSize: 12, color: "var(--text-muted)" }}>view</summary>
                            <pre style={{
                              fontSize: 11, whiteSpace: "pre-wrap", wordBreak: "break-all",
                              margin: "4px 0 0", color: "var(--text-muted)",
                              maxHeight: 100, overflow: "auto",
                            }}>
                              {c.log_excerpt}
                            </pre>
                          </details>
                        ) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {visible.length > 300 && (
            <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 8 }}>
              Showing 300 of {visible.length}. Use search to narrow.
            </p>
          )}
        </>
      )}
    </div>
  );
}

// ── Root page ─────────────────────────────────────────────────────────────────

export default function AppLogSession() {
  const { id } = useParams();
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    getAppSession(id)
      .then(setSession)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="loading">Loading session…</div>;
  if (error)   return <div className="error-msg">{error}</div>;
  if (!session) return null;

  const calls = session.function_calls || [];

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <Link to="/" style={{ color: "var(--text-muted)", fontSize: 13 }}>Dashboard</Link>
          <span style={{ color: "var(--text-muted)" }}>/</span>
          <Link
            to={`/app-logs/apps/${encodeURIComponent(session.app_name)}`}
            style={{ color: "var(--text-muted)", fontSize: 13 }}
          >
            {session.app_name}
          </Link>
          <span style={{ color: "var(--text-muted)" }}>/</span>
          <span style={{ fontSize: 13 }}>Session #{session.id}</span>
        </div>
        <h1 style={{ margin: "0 0 4px" }}>{session.app_name}</h1>
        <p style={{ margin: 0, fontSize: 14, color: "var(--text-muted)" }}>
          Format: <strong>{session.log_format}</strong>
          {" · "}{session.total_calls ?? 0} calls
          {" · "}{formatMs(session.total_duration_ms)} total
          {" · "}
          <span style={{
            textTransform: "capitalize",
            color: session.status === "completed" ? "#22c55e"
              : session.status === "failed" ? "#ef4444" : "var(--text-muted)",
          }}>
            {session.status}
          </span>
        </p>
        {session.source_repo && (
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--text-muted)" }}>
            Source:{" "}
            <a href={session.source_repo} target="_blank" rel="noreferrer"
              style={{ color: "var(--color-primary,#6366f1)" }}>
              {session.source_repo}
            </a>
          </p>
        )}
      </div>

      {session.status === "failed" && session.error_message && (
        <div className="error-msg">{session.error_message}</div>
      )}

      {/* Flamegraph with source badges */}
      {calls.length > 0 && (
        <TimeBreakdown
          calls={calls}
          totalMs={session.total_duration_ms || 1}
          sourceRepo={session.source_repo}
        />
      )}

      {/* AI Analysis — button + KPI card + SuggestionCards */}
      <AIAnalysisPanel sessionId={id} sessionStatus={session.status} />

      {/* Source correlation */}
      <SourceTrace sessionId={id} sourceRepo={session.source_repo} />

      {/* All calls table */}
      {calls.length > 0 && (
        <CallsTable
          calls={calls}
          totalMs={session.total_duration_ms || 1}
          sourceRepo={session.source_repo}
        />
      )}

      {calls.length === 0 && session.status === "completed" && (
        <div className="card">
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            No function calls were extracted. Try a different format or re-upload.
          </p>
        </div>
      )}
    </div>
  );
}
