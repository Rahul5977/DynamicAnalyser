import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboardSummary, listRepos, seedDemo, listAppSessions } from "../services/api";
import KPICard from "../components/KPICard";
import StatusBadge from "../components/StatusBadge";

function formatMs(ms) {
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function formatDate(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// ── CI/CD section ─────────────────────────────────────────────────────────────

function CICDDashboard() {
  const [summary, setSummary] = useState(null);
  const [repos, setRepos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [seeding, setSeeding] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([getDashboardSummary(), listRepos()])
      .then(([s, r]) => { setSummary(s); setRepos(r); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleSeed = async () => {
    setSeeding(true);
    try { await seedDemo(); load(); }
    catch (e) { setError(e.message); }
    finally { setSeeding(false); }
  };

  if (loading) return <div className="loading">Loading CI/CD data...</div>;
  if (error) return <div className="error-msg">{error}</div>;

  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
        <button className="btn btn-secondary" onClick={handleSeed} disabled={seeding}>
          {seeding ? "Seeding..." : "Load Demo Data"}
        </button>
      </div>

      {summary && (
        <div className="kpi-grid">
          <KPICard label="Repos Tracked" value={summary.total_repos} />
          <KPICard label="Total Runs" value={summary.total_runs} />
          <KPICard label="Analyses Done" value={summary.total_analyses} />
          <KPICard label="Avg Duration" value={formatMs(summary.avg_duration_ms)} />
          <KPICard label="Avg Saving" value={formatMs(summary.avg_saving_ms)} sub="per analysis" />
        </div>
      )}

      <div className="card">
        <div className="card-title">Tracked Repositories</div>
        {repos.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            No repositories tracked yet. Use "Load Demo Data" or add one in Settings.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Repository</th>
                  <th>Branch</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {repos.map((r) => (
                  <tr key={r.id}>
                    <td><Link to={`/repos/${r.owner}/${r.name}`}>{r.full_name}</Link></td>
                    <td style={{ color: "var(--text-muted)" }}>{r.default_branch}</td>
                    <td>
                      {r.is_active
                        ? <StatusBadge status="success" />
                        : <StatusBadge status="inactive" />}
                    </td>
                    <td>
                      <Link to={`/repos/${r.owner}/${r.name}`} className="btn btn-sm btn-secondary">
                        View Runs
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {summary && summary.recent_runs.length > 0 && (
        <div className="card">
          <div className="card-title">Recent Activity</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Workflow</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {summary.recent_runs.map((r) => (
                  <tr key={r.id}>
                    <td><Link to={`/runs/${r.id}`}>#{r.run_number}</Link></td>
                    <td>{r.workflow_name || "—"}</td>
                    <td><StatusBadge status={r.conclusion || r.status} /></td>
                    <td>{formatMs(r.total_duration_ms)}</td>
                    <td style={{ color: "var(--text-muted)" }}>{formatDate(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

// ── App Logs section ──────────────────────────────────────────────────────────

const STATUS_COLOR = {
  completed: "var(--color-success, #22c55e)",
  failed: "var(--color-error, #ef4444)",
  pending: "var(--text-muted)",
};

function AppLogsDashboard() {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listAppSessions()
      .then(setSessions)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">Loading app log sessions...</div>;
  if (error) return <div className="error-msg">{error}</div>;

  const totalCalls = sessions.reduce((s, r) => s + (r.total_calls || 0), 0);
  const totalDur   = sessions.reduce((s, r) => s + (r.total_duration_ms || 0), 0);

  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
        <Link to="/app-logs/upload" className="btn btn-primary">
          + Upload Log File
        </Link>
      </div>

      <div className="kpi-grid">
        <KPICard label="Log Sessions" value={sessions.length} />
        <KPICard label="Function Calls" value={totalCalls} />
        <KPICard label="Total Captured" value={formatMs(totalDur)} />
        <KPICard
          label="Analysed"
          value={sessions.filter((s) => s.status === "completed").length}
          sub="sessions"
        />
      </div>

      <div className="card">
        <div className="card-title">Log Sessions</div>
        {sessions.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            No log sessions yet.{" "}
            <Link to="/app-logs/upload">Upload a log file</Link> to get started.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>App</th>
                  <th>Format</th>
                  <th>Calls</th>
                  <th>Total Time</th>
                  <th>Status</th>
                  <th>Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id}>
                    <td><strong>{s.app_name}</strong></td>
                    <td style={{ color: "var(--text-muted)", fontSize: 13 }}>{s.log_format}</td>
                    <td>{s.total_calls ?? "—"}</td>
                    <td>{formatMs(s.total_duration_ms)}</td>
                    <td>
                      <span style={{
                        color: STATUS_COLOR[s.status] || "var(--text-muted)",
                        fontWeight: 600,
                        fontSize: 13,
                        textTransform: "capitalize",
                      }}>
                        {s.status}
                      </span>
                    </td>
                    <td style={{ color: "var(--text-muted)", fontSize: 13 }}>
                      {formatDate(s.created_at)}
                    </td>
                    <td>
                      <Link
                        to={`/app-logs/sessions/${s.id}`}
                        className="btn btn-sm btn-secondary"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

// ── Root Dashboard with mode toggle ──────────────────────────────────────────

export default function Dashboard() {
  const [mode, setMode] = useState("cicd"); // "cicd" | "applogs"

  return (
    <div>
      <div
        className="page-header"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
      >
        <div>
          <h1>Dashboard</h1>
          <p>
            {mode === "cicd"
              ? "CI/CD Pipeline Performance Overview"
              : "Application Log Analysis Overview"}
          </p>
        </div>

        {/* Mode toggle */}
        <div style={{ display: "flex", gap: 4, background: "var(--bg-card)", borderRadius: 8, padding: 4, border: "1px solid var(--border)" }}>
          <button
            className={`btn btn-sm ${mode === "cicd" ? "btn-primary" : "btn-secondary"}`}
            style={{ borderRadius: 6 }}
            onClick={() => setMode("cicd")}
          >
            CI/CD Pipeline
          </button>
          <button
            className={`btn btn-sm ${mode === "applogs" ? "btn-primary" : "btn-secondary"}`}
            style={{ borderRadius: 6 }}
            onClick={() => setMode("applogs")}
          >
            Application Logs
          </button>
        </div>
      </div>

      {mode === "cicd" ? <CICDDashboard /> : <AppLogsDashboard />}
    </div>
  );
}
