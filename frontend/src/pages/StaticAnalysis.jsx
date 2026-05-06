import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Shield,
  Loader2,
  GitBranch,
  Layers,
  FileCode2,
  ArrowRight,
} from "lucide-react";
import {
  startStaticAnalysis,
  getStaticReport,
  listStaticReports,
} from "../services/api";

function severityStyle(sev) {
  const s = (sev || "").toLowerCase();
  if (s === "critical") return { background: "#7f1d1d", color: "#fecaca" };
  if (s === "high") return { background: "#9a3412", color: "#ffedd5" };
  if (s === "medium") return { background: "#854d0e", color: "#fef9c3" };
  return { background: "#334155", color: "#e2e8f0" };
}

export default function StaticAnalysis() {
  const [githubUrl, setGithubUrl] = useState("");
  const [fullName, setFullName] = useState("");
  const [commitSha, setCommitSha] = useState("");
  const [report, setReport] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const [domainFilter, setDomainFilter] = useState("all");

  useEffect(() => {
    listStaticReports(25).then(setHistory).catch(() => {});
  }, []);

  useEffect(() => {
    if (!report?.id) return;
    if (report.status === "completed" || report.status === "failed") return;
    const timer = setInterval(async () => {
      try {
        const r = await getStaticReport(report.id);
        setReport(r);
        if (r.status === "completed" || r.status === "failed") {
          clearInterval(timer);
          listStaticReports(25).then(setHistory).catch(() => {});
        }
      } catch {
        clearInterval(timer);
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [report?.id, report?.status]);

  const onStart = async () => {
    setError(null);
    setStarting(true);
    try {
      const payload = {};
      if (fullName.trim()) payload.full_name = fullName.trim();
      if (githubUrl.trim()) payload.github_url = githubUrl.trim();
      if (commitSha.trim()) payload.commit_sha = commitSha.trim();
      if (!payload.github_url && !payload.full_name) {
        setError("Enter a GitHub URL or owner/repo.");
        setStarting(false);
        return;
      }
      const r = await startStaticAnalysis(payload);
      setReport(r);
      listStaticReports(25).then(setHistory).catch(() => {});
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setStarting(false);
    }
  };

  const loadReport = async (id) => {
    setError(null);
    try {
      const r = await getStaticReport(id);
      setReport(r);
    } catch (e) {
      setError(e.message || String(e));
    }
  };

  const findings = report?.findings || [];
  const filtered =
    domainFilter === "all"
      ? findings
      : findings.filter((f) => f.domain === domainFilter);

  const domains = report?.domains || [];
  const domainNames = [...new Set(findings.map((f) => f.domain))].sort();

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1>Static code analysis</h1>
        <p>
          Large repositories are split into <strong>domains</strong> (security,
          database, backend, frontend, infrastructure). Each chunk is parsed with
          AST tools (including ORM / DB patterns) and reviewed by Claude Sonnet,
          with <strong>before</strong> and <strong>after</strong> code and
          explanations.
        </p>
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <div
          className="flex items-center gap-3"
          style={{ marginBottom: 20, flexWrap: "wrap" }}
        >
          <div className="feature-tile-icon indigo">
            <Shield size={22} />
          </div>
          <div>
            <div className="card-title" style={{ margin: 0 }}>
              Analyse a GitHub repository
            </div>
            <div className="card-subtitle">
              Uses GitHub API + chunked LLM calls. Ensure <code>GITHUB_TOKEN</code>{" "}
              and <code>ANTHROPIC_API_KEY</code> are set on the API server.
            </div>
          </div>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 12,
            marginBottom: 12,
          }}
        >
          <label className="form-label">
            GitHub URL
            <input
              className="form-input"
              placeholder="https://github.com/org/repo"
              value={githubUrl}
              onChange={(e) => setGithubUrl(e.target.value)}
            />
          </label>
          <label className="form-label">
            or owner/repo
            <input
              className="form-input"
              placeholder="octocat/Hello-World"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </label>
          <label className="form-label">
            Commit SHA (optional)
            <input
              className="form-input"
              placeholder="default branch HEAD"
              value={commitSha}
              onChange={(e) => setCommitSha(e.target.value)}
            />
          </label>
        </div>

        {error && (
          <div
            className="card-subtitle"
            style={{ color: "#fca5a5", marginBottom: 12 }}
          >
            {error}
          </div>
        )}

        <button
          type="button"
          className="btn btn-primary"
          onClick={onStart}
          disabled={
            starting || (!githubUrl.trim() && !fullName.trim())
          }
          style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
        >
          {starting ? (
            <Loader2 size={18} className="spin" />
          ) : (
            <GitBranch size={18} />
          )}
          {starting ? "Starting…" : "Run chunked analysis"}
        </button>
        <Link to="/" className="btn btn-secondary" style={{ marginLeft: 12 }}>
          Dashboard
        </Link>
      </div>

      {history.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Layers size={18} />
            Recent runs
          </div>
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Repository</th>
                  <th>Commit</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id}>
                    <td>{h.id}</td>
                    <td>{h.github_full_name}</td>
                    <td style={{ fontFamily: "monospace", fontSize: "0.85em" }}>
                      {(h.commit_sha || "").slice(0, 12)}
                    </td>
                    <td>{h.status}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => loadReport(h.id)}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {report && (
        <div className="card">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: 12,
              alignItems: "flex-start",
            }}
          >
            <div>
              <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <FileCode2 size={20} />
                Report #{report.id}
              </div>
              <div className="card-subtitle">
                {report.github_full_name} @{" "}
                <code>{(report.commit_sha || "").slice(0, 12)}</code>
                {" · "}
                <strong>{report.status}</strong>
                {report.llm_model &&
                  ` · ${report.llm_model} (${report.llm_prompt_tokens ?? 0}↓ ${
                    report.llm_completion_tokens ?? 0
                  }↑ tok)`}
              </div>
              {report.error_message && (
                <p style={{ color: "#fca5a5", marginTop: 8 }}>{report.error_message}</p>
              )}
            </div>
          </div>

          {domains.length > 0 && (
            <div style={{ marginTop: 16, marginBottom: 8 }}>
              <div className="card-subtitle" style={{ marginBottom: 8 }}>
                Domain chunks (files analysed per bucket)
              </div>
              <div className="chip-row" style={{ flexWrap: "wrap" }}>
                {domains.map((d) => (
                  <span key={d.name} className="example-repo-chip">
                    {d.name}: {d.file_count} files · {d.llm_issues_count} LLM issues
                  </span>
                ))}
              </div>
            </div>
          )}

          {report.summary_markdown && report.status === "completed" && (
            <div style={{ marginTop: 20 }}>
              <h3 className="card-title">Executive summary</h3>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  fontFamily: "var(--font-sans, system-ui)",
                  fontSize: "0.95rem",
                  lineHeight: 1.55,
                  background: "rgba(0,0,0,0.25)",
                  padding: 16,
                  borderRadius: 8,
                  marginTop: 8,
                }}
              >
                {report.summary_markdown}
              </pre>
            </div>
          )}

          {findings.length > 0 && (
            <div style={{ marginTop: 24 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  flexWrap: "wrap",
                  marginBottom: 16,
                }}
              >
                <h3 className="card-title" style={{ margin: 0 }}>
                  Findings
                </h3>
                <select
                  className="form-input"
                  style={{ maxWidth: 200 }}
                  value={domainFilter}
                  onChange={(e) => setDomainFilter(e.target.value)}
                >
                  <option value="all">All domains</option>
                  {domainNames.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
                <span className="card-subtitle">{filtered.length} shown</span>
              </div>

              {filtered.map((f, idx) => (
                <div
                  key={`${f.file_path}-${f.line_start}-${idx}`}
                  className="card"
                  style={{
                    marginBottom: 16,
                    background: "rgba(15,23,42,0.6)",
                    border: "1px solid rgba(148,163,184,0.15)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 8,
                      alignItems: "center",
                      marginBottom: 8,
                    }}
                  >
                    <span
                      style={{
                        fontSize: "0.7rem",
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                        padding: "4px 8px",
                        borderRadius: 6,
                        ...severityStyle(f.severity),
                      }}
                    >
                      {f.severity}
                    </span>
                    <span className="example-repo-chip">{f.domain}</span>
                    {f.source && (
                      <span className="example-repo-chip">source: {f.source}</span>
                    )}
                  </div>
                  <div className="card-title" style={{ fontSize: "1.05rem" }}>
                    {f.title}
                  </div>
                  {(f.file_path || f.line_start) && (
                    <div className="card-subtitle" style={{ fontFamily: "monospace" }}>
                      {f.file_path}
                      {f.line_start
                        ? ` — L${f.line_start}${f.line_end && f.line_end !== f.line_start ? `–${f.line_end}` : ""}`
                        : ""}
                    </div>
                  )}
                  {f.explanation && (
                    <p style={{ marginTop: 10, lineHeight: 1.55 }}>{f.explanation}</p>
                  )}
                  {(f.before_code || f.after_code) && (
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
                        gap: 12,
                        marginTop: 12,
                      }}
                    >
                      <div>
                        <div
                          className="card-subtitle"
                          style={{ marginBottom: 6, color: "#fca5a5" }}
                        >
                          Previous code
                        </div>
                        <pre
                          style={{
                            margin: 0,
                            padding: 12,
                            borderRadius: 8,
                            background: "rgba(0,0,0,0.35)",
                            fontSize: "0.8rem",
                            overflow: "auto",
                            maxHeight: 320,
                          }}
                        >
                          {f.before_code || "—"}
                        </pre>
                      </div>
                      <div>
                        <div
                          className="card-subtitle"
                          style={{
                            marginBottom: 6,
                            color: "#86efac",
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          <ArrowRight size={14} />
                          Suggested code
                        </div>
                        <pre
                          style={{
                            margin: 0,
                            padding: 12,
                            borderRadius: 8,
                            background: "rgba(22,101,52,0.25)",
                            fontSize: "0.8rem",
                            overflow: "auto",
                            maxHeight: 320,
                          }}
                        >
                          {f.after_code || "—"}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {report.status === "running" && (
            <div
              className="card-subtitle"
              style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 8 }}
            >
              <Loader2 size={18} className="spin" />
              Fetching tree, running DB layer AST scan, calling Claude per domain…
            </div>
          )}
        </div>
      )}
    </div>
  );
}
