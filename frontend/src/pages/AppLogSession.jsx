import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getAppSession, analyseAppSession } from "../services/api";

function formatMs(ms) {
  if (ms === null || ms === undefined) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

function pct(part, total) {
  if (!total) return "—";
  return `${((part / total) * 100).toFixed(1)}%`;
}

function Bar({ value, max, color = "#6366f1" }) {
  const w = max ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div style={{
      height: 8,
      background: "var(--border)",
      borderRadius: 4,
      overflow: "hidden",
      minWidth: 80,
    }}>
      <div style={{
        height: "100%",
        width: `${w}%`,
        background: color,
        borderRadius: 4,
        transition: "width .3s",
      }} />
    </div>
  );
}

function barColor(durationMs, maxMs) {
  if (!maxMs) return "#6366f1";
  const ratio = durationMs / maxMs;
  if (ratio > 0.7) return "#ef4444";
  if (ratio > 0.35) return "#f59e0b";
  return "#22c55e";
}

// ── AI Analysis display ───────────────────────────────────────────────────────

function AIAnalysis({ raw }) {
  let data = null;
  try { data = JSON.parse(raw); } catch { /* not valid JSON */ }

  if (!data) {
    return (
      <pre style={{
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        fontSize: 13,
        color: "var(--text-muted)",
        margin: 0,
      }}>
        {raw}
      </pre>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {data.root_cause && (
        <div>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Root cause: </span>
          <span style={{ fontSize: 13 }}>{data.root_cause}</span>
        </div>
      )}
      {data.primary_bottleneck && (
        <div>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Primary bottleneck: </span>
          <code style={{ fontSize: 13 }}>{data.primary_bottleneck}</code>
        </div>
      )}
      {data.anti_patterns?.length > 0 && (
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Anti-patterns</div>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {data.anti_patterns.map((p, i) => (
              <li key={i} style={{ fontSize: 13, marginBottom: 2 }}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      {data.suggestions?.length > 0 && (
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Suggestions</div>
          {data.suggestions.map((s) => (
            <div key={s.rank} className="card" style={{ marginBottom: 10, padding: "12px 16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 600 }}>
                  #{s.rank} {s.title}
                </span>
                <span style={{
                  fontSize: 12,
                  padding: "2px 8px",
                  borderRadius: 4,
                  background: s.effort === "low"
                    ? "rgba(34,197,94,.15)"
                    : s.effort === "high"
                    ? "rgba(239,68,68,.15)"
                    : "rgba(245,158,11,.15)",
                  color: s.effort === "low" ? "#22c55e"
                    : s.effort === "high" ? "#ef4444" : "#f59e0b",
                }}>
                  {s.effort} effort
                </span>
              </div>
              <p style={{ margin: "8px 0 4px", fontSize: 13 }}>{s.description}</p>
              {s.target_function && (
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  Target: <code>{s.target_function}</code>
                </div>
              )}
              {s.estimated_saving_ms > 0 && (
                <div style={{ fontSize: 12, color: "#22c55e", marginTop: 4 }}>
                  Estimated saving: {formatMs(s.estimated_saving_ms)}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {data.estimated_total_saving_ms > 0 && (
        <div style={{ fontWeight: 600, fontSize: 13, color: "#22c55e" }}>
          Total estimated saving: {formatMs(data.estimated_total_saving_ms)}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AppLogSession() {
  const { id } = useParams();
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [analysing, setAnalysing] = useState(false);
  const [analyseError, setAnalyseError] = useState(null);
  const [search, setSearch]   = useState("");
  const [sortBy, setSortBy]   = useState("duration"); // duration | name | call_number

  useEffect(() => {
    getAppSession(id)
      .then(setSession)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  const handleAnalyse = async () => {
    setAnalysing(true);
    setAnalyseError(null);
    try {
      const result = await analyseAppSession(id);
      setSession((prev) => ({ ...prev, ai_analysis: result.ai_analysis }));
    } catch (e) {
      setAnalyseError(e.message);
    } finally {
      setAnalysing(false);
    }
  };

  if (loading) return <div className="loading">Loading session…</div>;
  if (error)   return <div className="error-msg">{error}</div>;
  if (!session) return null;

  const calls = session.function_calls || [];
  const maxDur = calls.length ? Math.max(...calls.map((c) => c.duration_ms)) : 0;

  // Filter + sort
  const visible = calls
    .filter((c) =>
      !search || c.function_name.toLowerCase().includes(search.toLowerCase())
    )
    .sort((a, b) => {
      if (sortBy === "name") return a.function_name.localeCompare(b.function_name);
      if (sortBy === "call_number") return a.call_number - b.call_number;
      return b.duration_ms - a.duration_ms; // default: slowest first
    });

  // Top-5 unique functions by total time for mini flamegraph
  const byFunc: Record<string, number> = {};
  for (const c of calls) {
    byFunc[c.function_name] = (byFunc[c.function_name] || 0) + c.duration_ms;
  }
  const topFuncs = Object.entries(byFunc)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);
  const totalCapture = session.total_duration_ms || 1;

  return (
    <div>
      {/* ── Header ── */}
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Link to="/" style={{ color: "var(--text-muted)", fontSize: 13 }}>Dashboard</Link>
          <span style={{ color: "var(--text-muted)" }}>/</span>
          <span style={{ fontSize: 13 }}>Session #{session.id}</span>
        </div>
        <h1 style={{ margin: "8px 0 4px" }}>{session.app_name}</h1>
        <p style={{ color: "var(--text-muted)", margin: 0, fontSize: 14 }}>
          Format: <strong>{session.log_format}</strong> ·{" "}
          {session.total_calls ?? 0} calls ·{" "}
          {formatMs(session.total_duration_ms)} total ·{" "}
          <span style={{
            color: session.status === "completed" ? "#22c55e"
              : session.status === "failed" ? "#ef4444" : "var(--text-muted)",
            textTransform: "capitalize",
          }}>
            {session.status}
          </span>
        </p>
      </div>

      {session.status === "failed" && session.error_message && (
        <div className="error-msg">{session.error_message}</div>
      )}

      {/* ── Time breakdown mini-flamegraph ── */}
      {topFuncs.length > 0 && (
        <div className="card">
          <div className="card-title">Time breakdown (top functions)</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {topFuncs.map(([fn, ms]) => (
              <div key={fn} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{
                  minWidth: 200,
                  maxWidth: 200,
                  fontSize: 13,
                  fontFamily: "monospace",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  color: "var(--text)",
                }}>
                  {fn}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{
                    height: 18,
                    background: "var(--border)",
                    borderRadius: 4,
                    overflow: "hidden",
                  }}>
                    <div style={{
                      height: "100%",
                      width: `${(ms / totalCapture) * 100}%`,
                      background: barColor(ms, totalCapture),
                      borderRadius: 4,
                    }} />
                  </div>
                </div>
                <div style={{
                  minWidth: 90,
                  textAlign: "right",
                  fontSize: 13,
                  color: "var(--text-muted)",
                }}>
                  {formatMs(ms)} ({pct(ms, totalCapture)})
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── AI Analysis ── */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div className="card-title" style={{ margin: 0 }}>AI Analysis</div>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleAnalyse}
            disabled={analysing || session.status !== "completed"}
          >
            {analysing ? "Analysing…" : session.ai_analysis ? "Re-analyse" : "Run AI Analysis"}
          </button>
        </div>
        {analyseError && (
          <div className="error-msg" style={{ marginTop: 12 }}>{analyseError}</div>
        )}
        {session.ai_analysis ? (
          <div style={{ marginTop: 16 }}>
            <AIAnalysis raw={session.ai_analysis} />
          </div>
        ) : (
          <p style={{ color: "var(--text-muted)", fontSize: 14, marginTop: 12 }}>
            Click "Run AI Analysis" to get root-cause insights and fix suggestions from Claude.
          </p>
        )}
      </div>

      {/* ── Function calls table ── */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <div className="card-title" style={{ margin: 0 }}>
            Function Calls ({visible.length} of {calls.length})
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="text"
              placeholder="Search by name…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                padding: "5px 10px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "var(--bg-input, var(--bg-card))",
                color: "inherit",
                fontSize: 13,
                width: 180,
              }}
            />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              style={{
                padding: "5px 10px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "var(--bg-input, var(--bg-card))",
                color: "inherit",
                fontSize: 13,
              }}
            >
              <option value="duration">Sort: slowest first</option>
              <option value="name">Sort: name A–Z</option>
              <option value="call_number">Sort: call order</option>
            </select>
          </div>
        </div>

        {visible.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            {search ? "No calls match the search." : "No function calls were parsed from this log."}
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Function</th>
                  <th>Duration</th>
                  <th style={{ minWidth: 120 }}>% of total</th>
                  <th>Call #</th>
                  <th>Log excerpt</th>
                </tr>
              </thead>
              <tbody>
                {visible.slice(0, 200).map((c, i) => (
                  <tr key={c.id}>
                    <td style={{ color: "var(--text-muted)", fontSize: 12 }}>{i + 1}</td>
                    <td>
                      <code style={{ fontSize: 13 }}>{c.function_name}</code>
                    </td>
                    <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span>{formatMs(c.duration_ms)}</span>
                        <Bar value={c.duration_ms} max={maxDur} color={barColor(c.duration_ms, maxDur)} />
                      </div>
                    </td>
                    <td style={{ color: "var(--text-muted)", fontSize: 13 }}>
                      {pct(c.duration_ms, session.total_duration_ms)}
                    </td>
                    <td style={{ color: "var(--text-muted)", fontSize: 13 }}>
                      call #{c.call_number}
                    </td>
                    <td style={{ maxWidth: 300 }}>
                      {c.log_excerpt ? (
                        <details>
                          <summary style={{ cursor: "pointer", fontSize: 12, color: "var(--text-muted)" }}>
                            view
                          </summary>
                          <pre style={{
                            fontSize: 11,
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-all",
                            margin: "4px 0 0",
                            color: "var(--text-muted)",
                            maxHeight: 120,
                            overflow: "auto",
                          }}>
                            {c.log_excerpt}
                          </pre>
                        </details>
                      ) : (
                        <span style={{ color: "var(--text-muted)", fontSize: 12 }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {visible.length > 200 && (
              <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 8 }}>
                Showing first 200 of {visible.length} results. Use search to filter.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
