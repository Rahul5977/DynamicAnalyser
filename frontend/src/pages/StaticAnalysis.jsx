import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Boxes,
  ChevronRight,
  Github,
  LayoutDashboard,
  Loader,
  ScrollText,
  Shield,
  Zap,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import HealthRing from "../components/HealthRing";
import StaticFindingCard from "../components/StaticFindingCard";
import StatusBadge from "../components/StatusBadge";
import { getStaticJob, getStaticReport, listStaticJobs, triggerStaticAnalysis } from "../services/api";

const STAGES = [
  "Ingest Repository",
  "AST Parse & Triage",
  "Vector Store Sync",
  "Orchestrator Agent",
  "Security Agent",
  "Performance Agent",
  "Architecture Agent",
  "Test Coverage Agent",
  "Critique Agent",
  "Synthesis Agent",
];

const SEC_PER_STAGE = 4.5;

const SIDEBAR_AGENTS = [
  { id: "security", label: "Security Agent", icon: "🔴" },
  { id: "performance", label: "Performance Agent", icon: "⚡" },
  { id: "database", label: "Database Agent", icon: "🔵" },
  { id: "frontend", label: "Frontend Agent", icon: "🌐" },
  { id: "architecture", label: "Architecture Agent", icon: "🟣" },
  { id: "memory", label: "Memory Agent", icon: "💧" },
  { id: "test_coverage", label: "Test Coverage", icon: "📋" },
];

function parseRepoLabel(url) {
  try {
    const m = (url || "").replace(/\.git$/, "").match(/github\.com\/([^/]+\/[^/]+)/);
    if (m) return m[1];
    if (url && !url.includes("http")) return url.split("/").slice(-2).join("/");
  } catch {
    /* ignore */
  }
  return url || "Repository";
}

function MiniHealthRing({ score }) {
  const s = score == null ? null : Math.min(100, Math.max(0, Number(score)));
  if (s == null) return <span className="text-muted">—</span>;
  const stroke = s >= 80 ? "var(--green-500)" : s >= 50 ? "var(--amber-500)" : "var(--red-500)";
  const size = 28;
  const r = size / 2 - 4;
  const c = 2 * Math.PI * r;
  const off = c * (1 - s / 100);
  return (
    <svg width={size} height={size} title={`${s}%`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--gray-100)" strokeWidth="5" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={stroke}
        strokeWidth="5"
        strokeDasharray={c}
        strokeDashoffset={off}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 1s ease" }}
      />
    </svg>
  );
}

function godRiskBadge(edges, chunks) {
  const risk = (edges || 0) * 1.5 + (chunks || 0) * 0.8;
  if (risk > 40) return { cls: "badge-red", label: "High" };
  if (risk > 20) return { cls: "badge-amber", label: "Medium" };
  return { cls: "badge-green", label: "Low" };
}

export default function StaticAnalysis() {
  const [repoUrl, setRepoUrl] = useState("");
  const [jobId, setJobId] = useState("");
  const [job, setJob] = useState(null);
  const [report, setReport] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [section, setSection] = useState("all");
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => Date.now());

  const loadJobs = useCallback(() => listStaticJobs().then(setJobs).catch(() => {}), []);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let t;
    const poll = async () => {
      try {
        const next = await getStaticJob(jobId);
        if (cancelled) return;
        setJob(next);
        if (next.status === "completed") {
          const rep = await getStaticReport(jobId);
          if (!cancelled) setReport(rep);
        } else if (next.status === "running" || next.status === "pending") {
          t = setTimeout(poll, 3000);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      }
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [jobId]);

  useEffect(() => {
    if (!job || (job.status !== "running" && job.status !== "pending")) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [job]);

  const run = async () => {
    setError("");
    setReport(null);
    try {
      const res = await triggerStaticAnalysis(repoUrl.trim());
      setJobId(res.job_id);
      setJob(null);
    } catch (e) {
      setError(e.message || "Failed to start static analysis");
    }
  };

  const cards = report?.finding_cards || [];
  const counts = useMemo(() => {
    const out = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    cards.forEach((c) => {
      const sev = (c.finding?.severity || "").toUpperCase();
      if (out[sev] !== undefined) out[sev] += 1;
    });
    return out;
  }, [cards]);

  const countsByAgent = useMemo(() => {
    const m = {};
    SIDEBAR_AGENTS.forEach((a) => {
      m[a.id] = cards.filter((c) => c.finding?.agent_id === a.id).length;
    });
    return m;
  }, [cards]);

  const filteredCards = useMemo(() => {
    if (section === "all") return cards;
    if (section === "arch_view" || section === "critique_log") return [];
    return cards.filter((c) => c.finding?.agent_id === section);
  }, [cards, section]);

  const healthScore = job?.health_score ?? report?.health_score ?? null;

  const showInput = !jobId;
  const showRunning = job && (job.status === "pending" || job.status === "running");
  const showReport = job && job.status === "completed" && report;
  const showFailed = job && job.status === "failed";
  const showJobLoading = Boolean(jobId && !job && !error);

  const elapsedSec =
    job?.created_at && showRunning ? (now - new Date(job.created_at).getTime()) / 1000 : 0;
  const completeStages = Math.min(STAGES.length, Math.floor(elapsedSec / SEC_PER_STAGE));
  const progressPct = Math.round((completeStages / STAGES.length) * 100);
  const estRemaining = Math.max(0, Math.round((STAGES.length - completeStages) * SEC_PER_STAGE));

  const couplingData = (report?.architecture_report?.coupling_scores || []).slice(0, 10).map((row) => ({
    ...row,
    short: (row.file_path || "").split("/").slice(-2).join("/") || row.file_path,
    fill:
      row.coupling_score > 30 ? "#ef4444" : row.coupling_score > 15 ? "#f59e0b" : "#6366f1",
  }));

  const downloadMarkdown = () => {
    if (!job || !report) return;
    const lines = [
      `# Static analysis — ${parseRepoLabel(job.repo_url)}`,
      "",
      `- Health score: ${healthScore ?? "—"}`,
      `- Findings: ${cards.length}`,
      `- Language: ${job.primary_language || "—"}`,
      "",
    ];
    cards.forEach((c, i) => {
      const f = c.finding || {};
      lines.push(`## ${i + 1}. ${f.title}`, `Agent: ${f.agent_id} · Severity: ${f.severity}`, "", (c.explanation_technical || "").slice(0, 2000), "");
    });
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const u = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = u;
    a.download = `static-report-${job.job_id}.md`;
    a.click();
    URL.revokeObjectURL(u);
  };

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1>Static Code Analysis</h1>
        <div className="breadcrumb-row">
          <span className="pill-muted">SAST</span>
          <span className="pill-muted">Multi-Agent</span>
          <span className="pill-muted">LangGraph Council</span>
        </div>
        <p>
          Enterprise security, performance, and architecture analysis powered by specialist AI agents
        </p>
      </div>

      {error && (
        <div className="error-msg" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {showJobLoading && (
        <div className="loading-state card">
          <Loader size={24} className="spin text-brand" />
          <span className="text-muted">Loading analysis job…</span>
        </div>
      )}

      {showInput && (
        <>
          <div className="card centered-hero-input">
            <div className="flex gap-2 flex-wrap" style={{ marginBottom: 20 }}>
              <span className="badge badge-red">
                <Shield size={14} /> Security Scanning
              </span>
              <span className="badge badge-amber">
                <Zap size={14} /> Performance Analysis
              </span>
              <span className="badge badge-blue">
                <Boxes size={14} /> Architecture Review
              </span>
            </div>
            <h2 className="dashboard-hero-title" style={{ fontSize: 20 }}>
              Analyse Your Repository
            </h2>
            <p className="text-muted" style={{ marginTop: 8, marginBottom: 20, lineHeight: 1.55 }}>
              Paste any public GitHub URL. The agent council will analyse security, performance,
              database patterns, memory safety, and code architecture.
            </p>
            <div className="form-input-icon-wrap">
              <Github size={18} className="input-icon-left" strokeWidth={1.75} />
              <input
                className="form-input"
                placeholder="https://github.com/owner/repo"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
              />
            </div>
            <button
              type="button"
              className="btn btn-primary btn-lg btn-block"
              style={{ marginTop: 16 }}
              disabled={!repoUrl.trim()}
              onClick={run}
            >
              <Shield size={20} />
              Run Static Analysis
              <ChevronRight size={20} />
            </button>
            <div className="text-sm text-muted" style={{ marginTop: 16 }}>
              Or try an example:
            </div>
            <div className="chip-row">
              {["facebook/react", "fastapi/fastapi", "OpenLake/canonforces"].map((ex) => (
                <button key={ex} type="button" className="example-repo-chip" onClick={() => setRepoUrl(`https://github.com/${ex}`)}>
                  {ex}
                </button>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">Recent Analyses</div>
            </div>
            {jobs.length === 0 ? (
              <div className="empty-state">
                <div className="empty-state-icon">
                  <ScrollText size={24} />
                </div>
                <h3>No jobs yet</h3>
                <p>Run your first static analysis to populate this table.</p>
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Repository</th>
                      <th>Health Score</th>
                      <th>Findings</th>
                      <th>Language</th>
                      <th>Date</th>
                      <th>Status</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((j) => (
                      <tr key={j.job_id}>
                        <td className="font-mono text-sm">{parseRepoLabel(j.repo_url)}</td>
                        <td>
                          <div className="flex items-center gap-2">
                            <MiniHealthRing score={j.health_score} />
                            <span className="text-sm">{j.health_score ?? "—"}</span>
                          </div>
                        </td>
                        <td>{j.finding_count ?? "—"}</td>
                        <td>{j.primary_language ?? "—"}</td>
                        <td className="text-sm text-muted">
                          {j.created_at ? new Date(j.created_at).toLocaleString() : "—"}
                        </td>
                        <td>
                          <StatusBadge status={j.status === "completed" ? "completed" : j.status} />
                        </td>
                        <td>
                          <button type="button" className="btn btn-sm btn-secondary" onClick={() => { setJobId(j.job_id); setJob(null); setReport(null); }}>
                            View Report
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {showRunning && (
        <div className="card">
          <div className="font-mono text-sm" style={{ marginBottom: 8 }}>
            {job.repo_url}
          </div>
          <div className="flex justify-between text-sm text-muted" style={{ marginBottom: 12 }}>
            <span>
              Elapsed: {Math.floor(elapsedSec)}s
            </span>
            <span>
              Estimated time remaining: ~{estRemaining}s
            </span>
          </div>
          <div className="pipeline-progress-track">
            <div className="pipeline-progress-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="card-title" style={{ margin: "16px 0 8px" }}>
            Running Analysis
          </div>
          {STAGES.map((label, i) => {
            let iconClass = "stage-icon-pending";
            let statusLabel = "Pending";
            let inner = <span className="text-muted">○</span>;
            if (i < completeStages) {
              iconClass = "stage-icon-success";
              statusLabel = "Complete";
              inner = <span className="kpi-trend-up">✓</span>;
            } else if (i === completeStages) {
              iconClass = "stage-icon-running";
              statusLabel = "Running";
              inner = <Loader size={16} className="spin-icon text-brand" />;
            }
            return (
              <div key={label} className="stage-row">
                <div className={`stage-icon-wrap ${iconClass}`}>{inner}</div>
                <div className="stage-title">{label}</div>
                <div className="stage-summary">{statusLabel}</div>
              </div>
            );
          })}
          <div style={{ marginTop: 16 }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setJobId("");
                setJob(null);
                loadJobs();
              }}
            >
              Back to input
            </button>
          </div>
        </div>
      )}

      {showFailed && (
        <div className="card">
          <div className="card-title">Static Analysis Failed</div>
          <div className="error-msg" style={{ marginTop: 8 }}>
            {job.error_message || "The analysis job failed before report generation."}
          </div>
          <div style={{ marginTop: 12 }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setJobId("");
                setJob(null);
                setReport(null);
                setError("");
                loadJobs();
              }}
            >
              Back to input
            </button>
          </div>
        </div>
      )}

      {showReport && (
        <div>
          <div className="card">
            <div className="flex justify-between gap-4 flex-wrap items-start">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span style={{ fontSize: 18, fontWeight: 600 }}>{parseRepoLabel(job.repo_url)}</span>
                  {job.primary_language && <span className="badge badge-teal">{job.primary_language}</span>}
                </div>
                <div className="text-sm text-muted" style={{ marginTop: 4 }}>
                  {job.completed_at
                    ? new Date(job.completed_at).toLocaleString()
                    : job.created_at
                      ? new Date(job.created_at).toLocaleString()
                      : "—"}
                </div>
              </div>
                <div className="flex flex-wrap gap-3 items-center">
                  <div className="flex flex-col items-center gap-1">
                    <HealthRing score={healthScore ?? 0} size={72} />
                    <div className="text-sm text-muted" style={{ fontSize: 11 }}>
                      Health Score
                    </div>
                  </div>
                <div className="flex gap-2 flex-wrap">
                  <span className="badge badge-critical">CRITICAL {counts.CRITICAL}</span>
                  <span className="badge badge-high">HIGH {counts.HIGH}</span>
                  <span className="badge badge-medium">MEDIUM {counts.MEDIUM}</span>
                  <span className="badge badge-low">LOW {counts.LOW}</span>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => {
                      setJobId("");
                      setJob(null);
                      setReport(null);
                      setSection("all");
                      loadJobs();
                    }}
                  >
                    New Analysis
                  </button>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={downloadMarkdown}>
                    Download Report
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="report-layout section">
            <nav className="card report-nav">
              <div className="report-nav-section-label">Overview</div>
              <button
                type="button"
                className={`report-nav-item ${section === "all" ? "active" : ""}`}
                onClick={() => setSection("all")}
              >
                <LayoutDashboard size={16} />
                All Findings
                <span className="report-nav-badge">{cards.length}</span>
              </button>

              <div className="report-nav-section-label">By Agent</div>
              {SIDEBAR_AGENTS.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className={`report-nav-item ${section === a.id ? "active" : ""}`}
                  onClick={() => setSection(a.id)}
                >
                  <span aria-hidden>{a.icon}</span>
                  {a.label}
                  <span className="report-nav-badge">{countsByAgent[a.id] || 0}</span>
                </button>
              ))}

              <div className="report-nav-section-label">Details</div>
              <button
                type="button"
                className={`report-nav-item ${section === "arch_view" ? "active" : ""}`}
                onClick={() => setSection("arch_view")}
              >
                <Boxes size={16} />
                Architecture View
              </button>
              <button
                type="button"
                className={`report-nav-item ${section === "critique_log" ? "active" : ""}`}
                onClick={() => setSection("critique_log")}
              >
                <ScrollText size={16} />
                Critique Log
              </button>
            </nav>

            <div>
              {(section === "all" || SIDEBAR_AGENTS.some((a) => a.id === section)) && (
                <>
                  {filteredCards.length === 0 ? (
                    <div className="empty-state card">
                      <div className="empty-state-icon">
                        <Shield size={24} />
                      </div>
                      <h3>No findings</h3>
                      <p>Nothing matched this filter for this report.</p>
                    </div>
                  ) : (
                    filteredCards.map((c, i) => (
                      <StaticFindingCard key={`${i}-${c.finding?.title}`} card={c} jobId={job.job_id} />
                    ))
                  )}
                </>
              )}

              {section === "arch_view" && (
                <>
                  <div className="card">
                    <div className="card-title">Circular Dependencies</div>
                    {(report.architecture_report?.cycles || []).length === 0 ? (
                      <p className="text-muted text-sm">No cycles detected.</p>
                    ) : (
                      <div className="flex flex-wrap gap-2" style={{ marginTop: 12 }}>
                        {(report.architecture_report?.cycles || []).slice(0, 12).map((cycle, idx) => (
                          <div key={idx} className="flex items-center gap-1 flex-wrap text-sm">
                            {cycle.map((node, j) => (
                              <React.Fragment key={`${idx}-${node}-${j}`}>
                                {j > 0 && <span className="text-muted">→</span>}
                                <span className="pill-muted font-mono" style={{ fontSize: 11 }}>
                                  {node.split("/").slice(-1)[0]}
                                </span>
                              </React.Fragment>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="card">
                    <div className="card-title">Coupling Scores</div>
                    <div style={{ height: 320 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart layout="vertical" data={couplingData} margin={{ left: 8, right: 16 }}>
                          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                          <XAxis type="number" />
                          <YAxis type="category" dataKey="short" width={120} tick={{ fontSize: 11 }} />
                          <Tooltip />
                          <Bar dataKey="coupling_score" radius={[0, 4, 4, 0]}>
                            {couplingData.map((entry, index) => (
                              <Cell key={`c-${entry.file_path}-${index}`} fill={entry.fill} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                  <div className="card">
                    <div className="card-title">God Classes</div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>File</th>
                            <th>Chunks</th>
                            <th>Edges</th>
                            <th>Risk</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(report.architecture_report?.god_classes || []).slice(0, 15).map((g, i) => {
                            const b = godRiskBadge(g.edge_count, g.chunk_count);
                            return (
                              <tr key={i}>
                                <td className="font-mono text-sm">{g.file_path}</td>
                                <td>{g.chunk_count}</td>
                                <td>{g.edge_count}</td>
                                <td>
                                  <span className={`badge ${b.cls}`}>{b.label}</span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              )}

              {section === "critique_log" && (
                <div className="card">
                  <div className="card-title">Critique Log</div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Finding</th>
                          <th>Agent</th>
                          <th>Severity</th>
                          <th>Verdict</th>
                          <th>Note</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(report.critique_log || []).map((row, idx) => {
                          const card = cards[row.finding_index];
                          const f = card?.finding || {};
                          return (
                            <tr key={idx}>
                              <td>{f.title || `Finding #${row.finding_index}`}</td>
                              <td>{f.agent_id || "—"}</td>
                              <td>
                                {f.severity ? <StatusBadge status={f.severity} /> : "—"}
                              </td>
                              <td>
                                <StatusBadge status={(row.verdict || "PLAUSIBLE").toUpperCase()} />
                              </td>
                              <td className="text-sm text-muted">{row.note}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
