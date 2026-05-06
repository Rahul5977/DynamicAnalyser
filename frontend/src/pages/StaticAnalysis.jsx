import React, { useEffect, useMemo, useState } from "react";
import { Boxes, Shield, Zap } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import StaticFindingCard from "../components/StaticFindingCard";
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

function statusBadge(status) {
  if (status === "completed") return <span className="badge badge-success">completed</span>;
  if (status === "failed") return <span className="badge badge-failure">failed</span>;
  return <span className="badge badge-info">{status}</span>;
}

export default function StaticAnalysis() {
  const [repoUrl, setRepoUrl] = useState("");
  const [jobId, setJobId] = useState("");
  const [job, setJob] = useState(null);
  const [report, setReport] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [section, setSection] = useState("all");
  const [error, setError] = useState("");

  const loadJobs = () => listStaticJobs().then(setJobs).catch(() => {});
  useEffect(() => { loadJobs(); }, []);

  useEffect(() => {
    if (!jobId) return;
    let t;
    const poll = async () => {
      try {
        const next = await getStaticJob(jobId);
        setJob(next);
        if (next.status === "completed") {
          const rep = await getStaticReport(jobId);
          setReport(rep);
        } else if (next.status === "running" || next.status === "pending") {
          t = setTimeout(poll, 3000);
        }
      } catch (e) {
        setError(e.message);
      }
    };
    poll();
    return () => clearTimeout(t);
  }, [jobId]);

  const run = async () => {
    setError("");
    setReport(null);
    try {
      const res = await triggerStaticAnalysis(repoUrl);
      setJobId(res.job_id);
    } catch (e) {
      setError(e.message || "Failed to start static analysis");
    }
  };

  const cards = report?.finding_cards || [];
  const counts = useMemo(() => {
    const out = { CRITICAL: 0, HIGH: 0, MEDIUM: 0 };
    cards.forEach((c) => { out[c.finding?.severity] = (out[c.finding?.severity] || 0) + 1; });
    return out;
  }, [cards]);

  const filteredCards = cards.filter((c) => {
    if (section === "all") return true;
    if (section === "critique") return false;
    if (section === "architecture") return false;
    return c.finding?.agent_id === section;
  });

  const showInput = !jobId || (!job && !report);
  const showRunning = job && (job.status === "pending" || job.status === "running");
  const showReport = job && job.status === "completed" && report;
  const showFailed = job && job.status === "failed";

  return (
    <div>
      <div className="page-header">
        <h1>Static Analysis</h1>
        <p>Enterprise multi-agent SAST powered by LangGraph Council</p>
      </div>
      {error && <div className="error-msg" style={{ marginBottom: 12 }}>{error}</div>}

      {showInput && (
        <>
          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <div>
                <div className="card-title">Static Code Analyser</div>
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Enterprise multi-agent SAST powered by LangGraph Council</div>
              </div>
              <div style={{ display: "flex", gap: 12, color: "var(--text-muted)" }}>
                <Shield size={18} /><Zap size={18} /><Boxes size={18} />
              </div>
            </div>
            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              <input className="form-input" placeholder="https://github.com/owner/repo" value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} />
              <button className="btn btn-primary" onClick={run} disabled={!repoUrl}><Shield size={15} /> Run Static Analysis</button>
            </div>
          </div>

          <div className="card">
            <div className="card-title">Recent Static Jobs</div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Repo</th><th>Status</th><th>Health</th><th>Findings</th><th>Date</th><th>Action</th></tr></thead>
                <tbody>
                  {jobs.map((j) => (
                    <tr key={j.job_id}>
                      <td>{j.repo_url}</td>
                      <td>{statusBadge(j.status)}</td>
                      <td>{j.health_score ?? "—"}</td>
                      <td>{j.finding_count ?? "—"}</td>
                      <td>{j.created_at ? new Date(j.created_at).toLocaleString() : "—"}</td>
                      <td><button className="btn btn-sm btn-secondary" onClick={() => setJobId(j.job_id)}>View Report</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {showRunning && (
        <div className="card">
          <div className="card-title">Static Analysis Pipeline</div>
          <div style={{ color: "var(--text-muted)", marginBottom: 12 }}>Analysis running — this may take 30-90 seconds</div>
          {STAGES.map((s, i) => {
            const elapsed = job?.created_at ? (Date.now() - new Date(job.created_at).getTime()) / 1000 : 0;
            const completeIdx = Math.min(STAGES.length, Math.floor(elapsed / 8));
            const done = i < completeIdx;
            return (
              <div key={s} className="stage-row" style={{ marginLeft: 0 }}>
                <div className="stage-header"><div className="stage-title">{done ? "✓" : "○"} {s}</div></div>
              </div>
            );
          })}
          <div style={{ marginTop: 12 }}>
            <button className="btn btn-secondary" onClick={() => { setJobId(""); setJob(null); }}>Cancel</button>
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
          <div className="card" style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 700 }}>{job.repo_url}</div>
                <div style={{ color: "var(--text-muted)", fontSize: 12 }}>{new Date(job.created_at).toLocaleString()}</div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="badge badge-info">Health: {job.health_score ?? report.health_score}</span>
                <span className="badge" style={{ background: "var(--red)", color: "#fff" }}>CRITICAL {counts.CRITICAL || 0}</span>
                <span className="badge" style={{ background: "#f97316", color: "#fff" }}>HIGH {counts.HIGH || 0}</span>
                <span className="badge badge-warning">MEDIUM {counts.MEDIUM || 0}</span>
                <span className="badge badge-info">{job.primary_language || "unknown"}</span>
                <button className="btn btn-sm btn-secondary" onClick={() => { setJobId(""); setJob(null); setReport(null); }}>New Analysis</button>
                <button className="btn btn-sm btn-secondary" onClick={() => {
                  const md = `# Static Analysis Report\n\nRepo: ${job.repo_url}\n\nHealth: ${job.health_score}\n`;
                  const blob = new Blob([md], { type: "text/markdown" });
                  const u = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = u; a.download = `static-report-${job.job_id}.md`; a.click();
                  URL.revokeObjectURL(u);
                }}>Download Report</button>
              </div>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 12 }}>
            <div className="card" style={{ height: "fit-content" }}>
              {[
                ["all", "All Findings"],
                ["security", "Security"],
                ["performance", "Performance"],
                ["architecture", "Architecture"],
                ["test_coverage", "Test Coverage"],
                ["critique", "Critique Log"],
              ].map(([id, label]) => (
                <button key={id} className={`btn btn-sm ${section === id ? "btn-primary" : "btn-secondary"}`} style={{ width: "100%", justifyContent: "space-between", marginBottom: 8 }} onClick={() => setSection(id)}>
                  {label}
                  <span>{id === "all" ? cards.length : cards.filter((c) => c.finding?.agent_id === id).length}</span>
                </button>
              ))}
            </div>
            <div>
              {(section === "all" || ["security", "performance", "test_coverage"].includes(section)) &&
                filteredCards.map((c, i) => <StaticFindingCard key={`${i}-${c.finding?.title}`} card={c} jobId={job.job_id} />)}

              {section === "architecture" && (
                <div className="grid-3">
                  <div className="card">
                    <div className="card-title">Circular Dependencies</div>
                    {(report.architecture_report?.cycles || []).slice(0, 10).map((cycle, i) => (
                      <div key={i} style={{ fontSize: 12, marginBottom: 8 }}>{cycle.join(" -> ")}</div>
                    ))}
                  </div>
                  <div className="card">
                    <div className="card-title">Coupling Scores</div>
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={(report.architecture_report?.coupling_scores || []).slice(0, 10)}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="file_path" hide />
                        <YAxis />
                        <Tooltip />
                        <Bar dataKey="coupling_score" fill="#6366f1" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="card">
                    <div className="card-title">God Classes</div>
                    <div className="table-wrap">
                      <table>
                        <thead><tr><th>File</th><th>Chunks</th><th>Edges</th></tr></thead>
                        <tbody>
                          {(report.architecture_report?.god_classes || []).slice(0, 10).map((g, i) => (
                            <tr key={i}><td>{g.file_path}</td><td>{g.chunk_count}</td><td>{g.edge_count}</td></tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}

              {section === "critique" && (
                <div className="card">
                  <div className="card-title">Critique Log</div>
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>#</th><th>Verdict</th><th>Note</th></tr></thead>
                      <tbody>
                        {(report.critique_log || []).map((r, i) => (
                          <tr key={i}><td>{r.finding_index}</td><td>{r.verdict}</td><td>{r.note}</td></tr>
                        ))}
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
