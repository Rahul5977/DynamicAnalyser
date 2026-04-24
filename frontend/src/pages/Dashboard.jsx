import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboardSummary, getFleetSummary, listRepos, listAppSessions } from "../services/api";
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

  const load = () => {
    setLoading(true);
    Promise.all([getDashboardSummary(), listRepos()])
      .then(([s, r]) => { setSummary(s); setRepos(r); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="loading">Loading CI/CD data...</div>;
  if (error) return <div className="error-msg">{error}</div>;

  return (
    <>
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
            No repositories tracked yet. Add one in Settings or use Analyze Repo.
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

function groupByApp(sessions) {
  const map = {};
  for (const s of sessions) {
    if (!map[s.app_name]) {
      map[s.app_name] = { app_name: s.app_name, sessions: [], totalDur: 0, totalCalls: 0 };
    }
    map[s.app_name].sessions.push(s);
    map[s.app_name].totalDur   += s.total_duration_ms || 0;
    map[s.app_name].totalCalls += s.total_calls || 0;
  }
  return Object.values(map).sort((a, b) => {
    const la = a.sessions[0]?.created_at ?? "";
    const lb = b.sessions[0]?.created_at ?? "";
    return lb.localeCompare(la);
  });
}

function AppLogsDashboard() {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = () => {
    setLoading(true);
    listAppSessions()
      .then(setSessions)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="loading">Loading app log sessions...</div>;
  if (error) return <div className="error-msg">{error}</div>;

  const totalCalls = sessions.reduce((s, r) => s + (r.total_calls || 0), 0);
  const totalDur   = sessions.reduce((s, r) => s + (r.total_duration_ms || 0), 0);
  const analysed   = sessions.filter((s) => s.status === "completed").length;

  const appGroups = groupByApp(sessions);

  return (
    <>
      <FleetSummaryWidget />
      <RegressionAlertsSummary />

      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
        <Link to="/app-logs/upload" className="btn btn-primary">
          + Upload Log File
        </Link>
      </div>

      <div className="kpi-grid">
        <KPICard label="Applications" value={appGroups.length} />
        <KPICard label="Log Sessions" value={sessions.length} />
        <KPICard label="Function Calls" value={totalCalls} />
        <KPICard label="Total Captured" value={formatMs(totalDur)} />
        <KPICard label="Analysed" value={analysed} sub="sessions" />
      </div>

      <div className="card">
        <div className="card-title">Applications</div>
        {appGroups.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            No log sessions yet.{" "}
            <Link to="/app-logs/upload">Upload a log file</Link> to get started.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>App name</th>
                  <th>Sessions</th>
                  <th>Avg duration</th>
                  <th>Slowest function</th>
                  <th>Last upload</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {appGroups.map((g) => {
                  const avgDur = g.sessions.length
                    ? Math.round(g.totalDur / g.sessions.length)
                    : 0;
                  // Find the slowest single function call across all sessions in this group
                  let slowestFn = "—";
                  let maxDur = -1;
                  for (const s of g.sessions) {
                    if ((s.total_duration_ms || 0) > maxDur) {
                      maxDur = s.total_duration_ms || 0;
                      // We don't have per-call data here; use app-level duration label
                    }
                  }
                  // Sort sessions newest first to get last upload
                  const sorted = [...g.sessions].sort(
                    (a, b) => new Date(b.created_at) - new Date(a.created_at)
                  );
                  const lastUpload = sorted[0]?.created_at;

                  return (
                    <tr key={g.app_name}>
                      <td>
                        <Link
                          to={`/app-logs/apps/${encodeURIComponent(g.app_name)}`}
                          style={{ fontWeight: 700 }}
                        >
                          {g.app_name}
                        </Link>
                      </td>
                      <td>{g.sessions.length}</td>
                      <td>{formatMs(avgDur)}</td>
                      <td style={{ color: "var(--text-muted)", fontSize: 13 }}>
                        {g.sessions.length > 0 ? formatMs(maxDur) : "—"}
                      </td>
                      <td style={{ color: "var(--text-muted)", fontSize: 13 }}>
                        {lastUpload ? formatDate(lastUpload) : "—"}
                      </td>
                      <td>
                        <Link
                          to={`/app-logs/apps/${encodeURIComponent(g.app_name)}`}
                          className="btn btn-sm btn-secondary"
                        >
                          Sessions
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

function FleetSummaryWidget() {
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    let mounted = true;
    getFleetSummary()
      .then((data) => {
        if (mounted) setSummary(data);
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, []);

  if (!summary) return null;

  return (
    <div
      style={{
        marginBottom: 12,
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: "var(--border-radius-lg)",
        padding: "10px 12px",
        background: "var(--color-background-primary)",
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>Fleet Summary</div>
      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
        {summary.total_app_sessions} sessions · {summary.total_repos} repos · avg{" "}
        {formatMs(summary.fleet_avg_duration_ms)} · common issue:{" "}
        {summary.most_common_anti_pattern || "N/A"}
      </div>
    </div>
  );
}

function RegressionAlertsSummary() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    fetch("/api/app-logs/regressions/active")
      .then(async (r) => {
        if (!r.ok) return [];
        return r.json();
      })
      .then((data) => {
        if (mounted) setAlerts(data || []);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  if (loading) return null;

  if (alerts.length === 0) {
    return (
      <div style={{ marginBottom: 12 }}>
        <span
          style={{
            display: "inline-block",
            padding: "6px 12px",
            borderRadius: 999,
            background: "rgba(34,197,94,.14)",
            color: "#15803d",
            fontWeight: 700,
            fontSize: 13,
          }}
        >
          ✓ No regressions detected
        </span>
      </div>
    );
  }

  const top3 = [...alerts].sort((a, b) => b.ratio - a.ratio).slice(0, 3);
  const appCount = new Set(alerts.map((a) => a.app_name)).size;

  return (
    <div
      style={{
        marginBottom: 14,
        border: "1px solid rgba(239,68,68,.35)",
        borderRadius: 10,
        padding: "10px 12px",
        background: "rgba(239,68,68,.08)",
      }}
    >
      <div style={{ color: "#b91c1c", fontWeight: 700, marginBottom: 6 }}>
        ⚠ {alerts.length} active regressions across {appCount} apps
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {top3.map((a) => (
          <div key={a.id} style={{ fontSize: 13, color: "var(--text-primary)" }}>
            {a.app_name} / <code style={{ fontSize: 12 }}>{a.function_name}</code> / {a.ratio}× slower
          </div>
        ))}
      </div>
      <div style={{ marginTop: 8 }}>
        <Link to="/app-logs/regressions" className="btn btn-sm btn-secondary">View all</Link>
      </div>
    </div>
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
