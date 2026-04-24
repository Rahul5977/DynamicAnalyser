import React, { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getAppSession,
  getAppSessionAnalysis,
  analyseAppSession,
  getAppTrace,
  indexSourceForSession,
  getAppBenchmark,
  sendChatMessage,
  getChatHistory,
} from "../services/api";
import KPICard from "../components/KPICard";
import StatusBadge from "../components/StatusBadge";
import { EffortBadge } from "../components/StatusBadge";

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

function LocalSuggestionCard({ suggestion, onFeedback }) {
  const [expanded, setExpanded] = useState(false);

  const diff = suggestion.enriched_diff || suggestion.diff_hint;
  const formatMsLocal = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`);

  const getLineStyle = (line) => {
    if (line.startsWith("+++") || line.startsWith("---")) {
      return { color: "#888", fontWeight: 500 };
    }
    if (line.startsWith("+") && !line.startsWith("+++")) {
      return { background: "#EAF3DE", color: "#1A6B3A" };
    }
    if (line.startsWith("-") && !line.startsWith("---")) {
      return { background: "#FCEBEB", color: "#8B1A1A" };
    }
    if (line.startsWith("@@")) {
      return { background: "#E6F1FB", color: "#0C447C", fontStyle: "italic" };
    }
    return { color: "var(--color-text-secondary)" };
  };

  return (
    <div className="suggestion-card">
      <h4>
        #{suggestion.rank} {suggestion.title}
      </h4>
      <p>{suggestion.description}</p>
      <div className="suggestion-meta">
        {suggestion.target_file && (
          <span>
            {suggestion.target_file}
            {suggestion.target_function ? `:${suggestion.target_function}` : ""}
          </span>
        )}
        <span style={{ color: "var(--green)", fontWeight: 600 }}>
          ~{formatMsLocal(suggestion.estimated_saving_ms)} saving
        </span>
        <EffortBadge effort={suggestion.effort} />
        {suggestion.confidence_score != null && (
          <span>Confidence: {Math.round(suggestion.confidence_score * 100)}%</span>
        )}
        {suggestion.anti_pattern && (
          <span className="badge badge-warning">{suggestion.anti_pattern}</span>
        )}
      </div>
      {diff && (
        <>
          <button
            className="btn btn-secondary btn-sm"
            style={{ marginTop: 8 }}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Hide diff" : "Show diff"}
          </button>
          {expanded && (
            <div className="diff-block" style={{ position: "relative" }}>
              <div style={{ color: "#1A6B3A", fontSize: 11, fontWeight: 600, marginBottom: 6 }}>
                AI-Generated Code Diff
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                style={{ position: "absolute", top: 0, right: 0 }}
                onClick={() => navigator.clipboard.writeText(suggestion.enriched_diff || "")}
              >
                Copy diff
              </button>
              <pre
                style={{
                  fontSize: 11,
                  lineHeight: 1.7,
                  fontFamily: "monospace",
                  overflowX: "auto",
                  margin: 0,
                  padding: "10px 0",
                }}
              >
                {diff.split("\n").map((line, i) => (
                  <div key={i} style={getLineStyle(line)}>
                    {line}
                  </div>
                ))}
              </pre>
            </div>
          )}
        </>
      )}
      {onFeedback && (
        <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
          <button
            className="btn btn-sm btn-primary"
            onClick={() => onFeedback(suggestion.id, "accepted")}
          >
            Accept
          </button>
          <button
            className="btn btn-sm btn-secondary"
            onClick={() => onFeedback(suggestion.id, "rejected")}
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
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

function BenchmarkCard({ appName }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError("");
    getAppBenchmark(appName)
      .then((res) => {
        if (mounted) setData(res);
      })
      .catch((e) => {
        if (mounted) setError(e.message);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [appName]);

  if (loading) {
    return (
      <div
        style={{
          background: "var(--color-background-primary)",
          border: "0.5px solid var(--color-border-tertiary)",
          borderRadius: "var(--border-radius-lg)",
          padding: "1rem 1.25rem",
          marginTop: "1rem",
          color: "var(--color-text-secondary)",
        }}
      >
        Loading benchmark...
      </div>
    );
  }
  if (error || !data || data.total_apps_in_fleet < 2) return null;
  if (data.speed_percentile == null) {
    return (
      <div
        style={{
          background: "var(--color-background-primary)",
          border: "0.5px solid var(--color-border-tertiary)",
          borderRadius: "var(--border-radius-lg)",
          padding: "1rem 1.25rem",
          marginTop: "1rem",
          color: "var(--color-text-secondary)",
        }}
      >
        Not enough data — you are the first {appName} session.
      </div>
    );
  }

  const percentileColor =
    data.speed_percentile >= 50 ? "#22c55e" : data.speed_percentile >= 25 ? "#f59e0b" : "#ef4444";

  return (
    <div
      style={{
        background: "var(--color-background-primary)",
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: "var(--border-radius-lg)",
        padding: "1rem 1.25rem",
        marginTop: "1rem",
      }}
    >
      <div
        title={`Based on ${data.session_count} sessions across ${data.total_apps_in_fleet} applications`}
        style={{ fontSize: 56, fontWeight: 500, color: percentileColor, lineHeight: 1 }}
      >
        {data.speed_percentile}th
      </div>
      <div style={{ marginTop: 6, color: "var(--color-text-secondary)", fontSize: 13 }}>
        percentile — faster than {data.speed_percentile}% of {data.total_apps_in_fleet} tracked apps
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginTop: 14 }}>
        <div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>Your avg</div>
          <div style={{ fontWeight: 600 }}>{formatMs(data.avg_duration_ms)}</div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>Fleet median</div>
          <div style={{ fontWeight: 600 }}>{formatMs(data.fleet_p50_ms)}</div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>Fleet p95</div>
          <div style={{ fontWeight: 600 }}>{formatMs(data.fleet_p95_ms)}</div>
        </div>
      </div>

      <div
        style={{
          marginTop: 12,
          display: "inline-block",
          fontSize: 12,
          color: "var(--color-text-secondary)",
          padding: "4px 8px",
          borderRadius: 999,
          background: "var(--color-background-secondary)",
          border: "0.5px solid var(--color-border-tertiary)",
        }}
      >
        Fleet&apos;s most common issue: {data.fleet_most_common_anti_pattern || "N/A"}
      </div>
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

// ── Function selector table ───────────────────────────────────────────────────

function FunctionSelectorTable({ calls, totalMs, selectedFunctions, onSelectionChange }) {
  const [search, setSearch] = useState("");

  // Aggregate by function name
  const byFunc = {};
  for (const c of calls) {
    if (!byFunc[c.function_name]) {
      byFunc[c.function_name] = { count: 0, total: 0, max: 0 };
    }
    byFunc[c.function_name].count += 1;
    byFunc[c.function_name].total += c.duration_ms;
    byFunc[c.function_name].max = Math.max(byFunc[c.function_name].max, c.duration_ms);
  }

  const funcs = Object.entries(byFunc)
    .filter(([name]) => !search || name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => b[1].total - a[1].total);
  const allNames = Object.keys(byFunc);
  const maxTotal = funcs[0]?.[1].total || 1;

  const allSelected = allNames.length > 0 && allNames.every((n) => selectedFunctions.has(n));

  const toggleAll = () => {
    if (allSelected) {
      onSelectionChange(new Set());
    } else {
      onSelectionChange(new Set(allNames));
    }
  };

  const toggle = (name) => {
    const next = new Set(selectedFunctions);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    onSelectionChange(next);
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <div>
          <div className="card-title" style={{ margin: "0 0 4px" }}>
            Function Summary ({allNames.length} unique functions)
          </div>
          <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
            Select one or more functions, then click "Analyze Selected" to get AI insights.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="text"
            placeholder="Search functions…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              padding: "5px 10px", borderRadius: 6, border: "1px solid var(--border)",
              background: "var(--bg-input, var(--bg-card))", color: "inherit", fontSize: 13, width: 180,
            }}
          />
          <button className="btn btn-sm btn-secondary" onClick={toggleAll}>
            {allSelected ? "Clear All" : "Select All"}
          </button>
          {selectedFunctions.size > 0 && (
            <span style={{
              padding: "4px 10px", borderRadius: 6,
              background: "rgba(99,102,241,.15)", color: "var(--color-primary,#6366f1)",
              fontSize: 13, fontWeight: 600, whiteSpace: "nowrap",
            }}>
              {selectedFunctions.size} selected
            </span>
          )}
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 36 }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  title="Select / deselect all"
                />
              </th>
              <th>#</th>
              <th>Function</th>
              <th>Calls</th>
              <th>Total time</th>
              <th>Avg time</th>
              <th>Max time</th>
              <th>% of total</th>
            </tr>
          </thead>
          <tbody>
            {funcs.map(([name, stats], i) => {
              const avg = Math.round(stats.total / stats.count);
              const selected = selectedFunctions.has(name);
              return (
                <tr
                  key={name}
                  onClick={() => toggle(name)}
                  style={{
                    cursor: "pointer",
                    background: selected ? "rgba(99,102,241,.07)" : undefined,
                    outline: selected ? "1px solid rgba(99,102,241,.25)" : undefined,
                  }}
                >
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected} onChange={() => toggle(name)} />
                  </td>
                  <td style={{ color: "var(--text-muted)", fontSize: 12 }}>{i + 1}</td>
                  <td><code style={{ fontSize: 13 }}>{name}</code></td>
                  <td style={{ color: "var(--text-muted)", fontSize: 13 }}>{stats.count}</td>
                  <td style={{ fontWeight: 600 }}>{formatMs(stats.total)}</td>
                  <td style={{ color: "var(--text-muted)", fontSize: 13 }}>{formatMs(avg)}</td>
                  <td style={{ color: "var(--text-muted)", fontSize: 13 }}>{formatMs(stats.max)}</td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 12, color: "var(--text-muted)", minWidth: 40 }}>
                        {pct(stats.total, totalMs)}
                      </span>
                      <FlameBar value={stats.total} max={maxTotal} />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {funcs.length === 0 && (
        <p style={{ color: "var(--text-muted)", fontSize: 14, marginTop: 8 }}>
          No functions match the search.
        </p>
      )}
    </div>
  );
}


// ── AI Analysis panel ─────────────────────────────────────────────────────────

function AIAnalysisPanel({
  sessionId,
  appName,
  sessionStatus,
  targetFunctions,
  onClearSelection,
}) {
  const [analysis, setAnalysis]     = useState(null);
  const [analysing, setAnalysing]   = useState(false);
  const [polling, setPolling]       = useState(false);
  const [error, setError]           = useState(null);
  const [feedbackSent, setFeedbackSent] = useState({});
  const [patternRows, setPatternRows] = useState([]);
  const pollRef = useRef(null);

  // Reset panel whenever the target function selection changes
  useEffect(() => {
    setAnalysis(null);
    setError(null);
    return () => clearInterval(pollRef.current);
  }, [JSON.stringify(targetFunctions)]);

  const startPolling = () => {
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

  const handleAnalyse = async () => {
    setAnalysing(true); setError(null);
    try {
      const result = await analyseAppSession(sessionId, false, targetFunctions);
      if (result.status === "completed") {
        setAnalysis(result);
        setAnalysing(false);
      } else {
        startPolling();
      }
    } catch (e) {
      setError(e.message);
      setAnalysing(false);
    }
  };

  const handleFeedback = async (analysisId, suggestionId, verdict) => {
    try {
      const res = await fetch(`/api/app-logs/sessions/${sessionId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ suggestion_id: suggestionId, verdict, comment: null }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        throw new Error(err.detail || err.error || "Failed to submit feedback");
      }
      setFeedbackSent((prev) => ({ ...prev, [suggestionId]: verdict }));
      await loadPatternConfidence();
    } catch (e) {
      console.error("Feedback failed:", e.message);
    }
  };

  const loadPatternConfidence = async () => {
    if (!appName) return;
    try {
      const res = await fetch(`/api/app-logs/apps/${encodeURIComponent(appName)}/pattern-confidence`);
      if (!res.ok) return;
      const data = await res.json();
      const rows = (data.patterns || []).filter(
        (r) => (r.accepted_count + r.rejected_count + r.partial_count) > 0
      );
      setPatternRows(rows);
    } catch (_) {}
  };

  useEffect(() => {
    if (analysis) {
      loadPatternConfidence();
    }
  }, [analysis, appName]);

  const busy = analysing || polling;

  return (
    <div className="card" style={{ border: "1px solid rgba(99,102,241,.3)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="card-title" style={{ margin: "0 0 4px" }}>AI Performance Analysis</div>
          {targetFunctions && targetFunctions.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
              <span style={{ fontSize: 12, color: "var(--text-muted)", marginRight: 4 }}>Analyzing:</span>
              {targetFunctions.slice(0, 5).map((fn) => (
                <span key={fn} style={{
                  fontSize: 11, padding: "2px 8px", borderRadius: 4,
                  background: "rgba(99,102,241,.12)", color: "var(--color-primary,#6366f1)",
                  fontFamily: "monospace", border: "1px solid rgba(99,102,241,.25)",
                }}>
                  {fn}
                </span>
              ))}
              {targetFunctions.length > 5 && (
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  +{targetFunctions.length - 5} more
                </span>
              )}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          <button
            className="btn btn-sm btn-secondary"
            onClick={onClearSelection}
            title="Go back to function selection"
          >
            ← Change Selection
          </button>
          {analysis && (
            <button
              className="btn btn-sm btn-secondary"
              onClick={handleAnalyse}
              disabled={busy || sessionStatus !== "completed"}
            >
              Re-analyse
            </button>
          )}
          <button
            className="btn btn-sm btn-primary"
            onClick={handleAnalyse}
            disabled={busy || sessionStatus !== "completed"}
          >
            {polling ? "Analysing…" : analysing ? "Running…" : analysis ? "Analyse Again" : "Analyze Selected"}
          </button>
        </div>
      </div>

      {error && <div className="error-msg" style={{ marginTop: 12 }}>{error}</div>}

      {!analysis && !busy && (
        <p style={{ color: "var(--text-muted)", fontSize: 14, marginTop: 12 }}>
          Click "Analyze Selected" to get root-cause insights and fix suggestions from Claude
          for the {targetFunctions?.length ?? 0} selected function(s).
        </p>
      )}

      {busy && (
        <div style={{ color: "var(--text-muted)", fontSize: 14, marginTop: 12 }}>
          Running AI analysis… this may take 15–30 seconds.
        </div>
      )}

      {analysis && (
        <div style={{ marginTop: 16 }}>
          <StatusBadge status={analysis.status} />

          {/* Root cause */}
          {analysis.root_cause && (
            <div className="card" style={{ marginTop: 12, padding: "14px 16px" }}>
              <div className="card-title" style={{ margin: "0 0 8px" }}>Root cause</div>
              <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6 }}>{analysis.root_cause}</p>
              <div className="kpi-grid" style={{ marginTop: 16, gridTemplateColumns: "repeat(3,1fr)" }}>
                <KPICard label="Primary bottleneck" value={analysis.primary_bottleneck || "—"} />
                <KPICard label="Estimated saving" value={formatMs(analysis.estimated_total_saving_ms)} />
                <KPICard label="Anti-patterns found" value={analysis.anti_patterns?.length ?? 0} />
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

          {patternRows.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Pattern Learning</div>
              <div
                style={{
                  border: "0.5px solid var(--color-border-tertiary)",
                  borderRadius: 8,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1.5fr 120px 110px",
                    gap: 8,
                    padding: "8px 10px",
                    fontSize: 12,
                    fontWeight: 600,
                    color: "var(--color-text-secondary)",
                    background: "var(--color-background-secondary)",
                  }}
                >
                  <div>Pattern</div>
                  <div>Acceptance</div>
                  <div>Feedbacks</div>
                </div>
                {patternRows.map((row) => {
                  const accepted = row.accepted_count || 0;
                  const rejected = row.rejected_count || 0;
                  const partial = row.partial_count || 0;
                  const total = accepted + rejected + partial;
                  const acceptedPct = total ? Math.round((accepted / total) * 100) : 0;
                  const rejectedPct = total ? Math.round((rejected / total) * 100) : 0;
                  return (
                    <div
                      key={row.anti_pattern}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1.5fr 120px 110px",
                        gap: 8,
                        padding: "8px 10px",
                        fontSize: 12,
                        borderTop: "0.5px solid var(--color-border-tertiary)",
                        alignItems: "center",
                      }}
                    >
                      <div style={{ color: "var(--color-text-primary)" }}>{row.anti_pattern}</div>
                      <div>
                        <div
                          style={{
                            width: 100,
                            height: 8,
                            borderRadius: 999,
                            overflow: "hidden",
                            background: "var(--color-background-secondary)",
                            display: "flex",
                          }}
                        >
                          <div style={{ width: `${acceptedPct}%`, background: "#22c55e" }} />
                          <div style={{ width: `${rejectedPct}%`, background: "#ef4444" }} />
                        </div>
                      </div>
                      <div style={{ color: "var(--color-text-secondary)" }}>{total}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Suggestion cards */}
          {analysis.suggestions?.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10 }}>
                Fix suggestions ({analysis.suggestions.length})
              </div>
              {analysis.suggestions.map((s) => (
                <div key={s.id} style={{ marginBottom: 12 }}>
                  <LocalSuggestionCard
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

          {/* Analyze another */}
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
            <button className="btn btn-secondary" onClick={onClearSelection}>
              ← Analyze Different Functions
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ChatPanel({ sessionId }) {
  const [msgs, setMsgs] = useState([]);
  const [inputText, setInputText] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");
  const listRef = useRef(null);

  useEffect(() => {
    let mounted = true;
    getChatHistory(sessionId)
      .then((history) => {
        if (mounted) {
          setMsgs(history.map((m) => ({ role: m.role, content: m.content })));
        }
      })
      .catch((e) => {
        if (mounted) setError(e.message);
      });
    return () => {
      mounted = false;
    };
  }, [sessionId]);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [msgs, isSending]);

  const doSend = async (text) => {
    const trimmed = (text || "").trim();
    if (!trimmed || isSending) return;
    const history = msgs.slice(-10);

    setError("");
    setMsgs((prev) => [...prev, { role: "user", content: trimmed }]);
    setInputText("");
    setIsSending(true);

    try {
      const res = await sendChatMessage(sessionId, trimmed, history);
      setMsgs((prev) => [...prev, { role: "assistant", content: res.reply }]);
    } catch (e) {
      setError(e.message || "Failed to send message");
    } finally {
      setIsSending(false);
    }
  };

  const suggestions = [
    "Why is the primary bottleneck slow?",
    "Show me the fix for the top suggestion",
    "Which functions can be parallelised?",
  ];

  return (
    <div
      style={{
        background: "var(--color-background-primary)",
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: "var(--border-radius-lg)",
        padding: "1rem 1.25rem",
        marginTop: "1rem",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 18 }}>🤖</span>
        <div style={{ fontWeight: 600, color: "var(--color-text-primary)" }}>
          Ask AI about this session
        </div>
      </div>

      <div
        ref={listRef}
        style={{
          maxHeight: 400,
          overflowY: "auto",
          padding: "8px 4px",
          marginBottom: 12,
          border: "0.5px solid var(--color-border-tertiary)",
          borderRadius: "var(--border-radius-md)",
          background: "var(--color-background-primary)",
        }}
      >
        {msgs.length === 0 && !isSending ? (
          <div style={{ color: "var(--color-text-secondary)", fontSize: 13, padding: "4px 8px" }}>
            No messages yet. Ask about bottlenecks, timings, or fixes.
          </div>
        ) : (
          msgs.map((m, i) => (
            <div
              key={`${m.role}-${i}`}
              style={{
                display: "flex",
                justifyContent: m.role === "user" ? "flex-end" : "flex-start",
              }}
            >
              <div
                style={{
                  maxWidth: "78%",
                  background:
                    m.role === "user"
                      ? "var(--color-background-info)"
                      : "var(--color-background-secondary)",
                  color: "var(--color-text-primary)",
                  borderRadius: 10,
                  padding: "8px 12px",
                  marginBottom: 8,
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.5,
                  fontSize: 14,
                }}
              >
                {m.content}
              </div>
            </div>
          ))
        )}
        {isSending && (
          <div style={{ display: "flex", justifyContent: "flex-start" }}>
            <div
              style={{
                maxWidth: "78%",
                background: "var(--color-background-secondary)",
                color: "var(--color-text-primary)",
                borderRadius: 10,
                padding: "8px 12px",
                marginBottom: 8,
                fontSize: 14,
              }}
            >
              Thinking...
            </div>
          </div>
        )}
      </div>

      {msgs.length === 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => doSend(s)}
              disabled={isSending}
              style={{
                border: "0.5px solid var(--color-border-tertiary)",
                borderRadius: 999,
                background: "var(--color-background-secondary)",
                color: "var(--color-text-primary)",
                padding: "6px 10px",
                fontSize: 12,
                cursor: isSending ? "not-allowed" : "pointer",
              }}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          placeholder="Ask about any function, bottleneck, or fix..."
          disabled={isSending}
          onKeyDown={(e) => {
            if (e.key === "Enter") doSend(inputText);
          }}
          style={{
            flex: 1,
            padding: "10px 12px",
            borderRadius: "var(--border-radius-md)",
            border: "0.5px solid var(--color-border-tertiary)",
            background: "var(--color-background-primary)",
            color: "var(--color-text-primary)",
          }}
        />
        <button
          type="button"
          onClick={() => doSend(inputText)}
          disabled={isSending || !inputText.trim()}
          style={{
            padding: "10px 14px",
            borderRadius: "var(--border-radius-md)",
            border: "0.5px solid var(--color-border-tertiary)",
            background: "var(--color-background-secondary)",
            color: "var(--color-text-primary)",
            cursor: isSending ? "not-allowed" : "pointer",
          }}
        >
          Send
        </button>
      </div>
      {error && (
        <div style={{ color: "var(--color-danger, #ef4444)", fontSize: 13, marginTop: 8 }}>
          {error}
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
  const [session, setSession]             = useState(null);
  const [loading, setLoading]             = useState(true);
  const [error, setError]                 = useState(null);
  const [selectedFunctions, setSelectedFunctions] = useState(new Set());

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
  const totalMs = session.total_duration_ms || 1;
  const hasSelection = selectedFunctions.size > 0;

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
          {" · "}{formatMs(totalMs)} total
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

      <div className="kpi-grid" style={{ marginBottom: 16 }}>
        <KPICard label="Total duration" value={formatMs(totalMs)} />
        <KPICard label="Total calls" value={session.total_calls ?? 0} />
      </div>

      <BenchmarkCard appName={session.app_name} />

      {/* Time breakdown flamegraph */}
      {calls.length > 0 && (
        <TimeBreakdown calls={calls} totalMs={totalMs} sourceRepo={session.source_repo} />
      )}

      {/* Function selector — always visible when calls exist */}
      {calls.length > 0 && session.status === "completed" && (
        <FunctionSelectorTable
          calls={calls}
          totalMs={totalMs}
          selectedFunctions={selectedFunctions}
          onSelectionChange={setSelectedFunctions}
        />
      )}

      {/* "Analyze Selected" call-to-action — shown when functions are selected but analysis not started */}
      {hasSelection && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 16px", borderRadius: 8, marginBottom: 16,
          background: "rgba(99,102,241,.08)", border: "1px solid rgba(99,102,241,.25)",
        }}>
          <span style={{ fontSize: 14, color: "var(--color-primary,#6366f1)", fontWeight: 600 }}>
            {selectedFunctions.size} function{selectedFunctions.size > 1 ? "s" : ""} selected — ready for AI analysis
          </span>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setSelectedFunctions(new Set())}
            style={{ fontSize: 12 }}
          >
            Clear selection
          </button>
        </div>
      )}

      {/* AI Analysis panel — shown only when functions are selected */}
      {hasSelection && (
        <AIAnalysisPanel
          sessionId={id}
          appName={session.app_name}
          sessionStatus={session.status}
          targetFunctions={Array.from(selectedFunctions)}
          onClearSelection={() => setSelectedFunctions(new Set())}
        />
      )}

      {/* Source correlation */}
      <SourceTrace sessionId={id} sourceRepo={session.source_repo} />

      {/* All individual calls table */}
      {calls.length > 0 && (
        <CallsTable calls={calls} totalMs={totalMs} sourceRepo={session.source_repo} />
      )}

      {calls.length === 0 && session.status === "completed" && (
        <div className="card">
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            No function calls were extracted. Try a different format or re-upload.
          </p>
        </div>
      )}

      <ChatPanel sessionId={id} />
    </div>
  );
}
