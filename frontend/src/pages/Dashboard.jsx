import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDashboardSummary, listRepos, seedDemo } from "../services/api";
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

export default function Dashboard() {
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
    try {
      await seedDemo();
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSeeding(false);
    }
  };

  if (loading) return <div className="loading">Loading dashboard...</div>;
  if (error) return <div className="error-msg">{error}</div>;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1>Dashboard</h1>
          <p>CI/CD Pipeline Performance Overview</p>
        </div>
        <button className="btn btn-secondary" onClick={handleSeed} disabled={seeding}>
          {seeding ? "Seeding..." : "Load Demo Data"}
        </button>
      </div>

      {summary && (
        <div className="kpi-grid">
          <KPICard label="Repos Tracked" value={summary.total_repos} />
          <KPICard label="Total Runs" value={summary.total_runs} />
          <KPICard label="Analyses Done" value={summary.total_analyses} />
          <KPICard
            label="Avg Duration"
            value={formatMs(summary.avg_duration_ms)}
          />
          <KPICard
            label="Avg Saving"
            value={formatMs(summary.avg_saving_ms)}
            sub="per analysis"
          />
        </div>
      )}

      {/* Repository Table */}
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
                    <td>
                      <Link to={`/repos/${r.owner}/${r.name}`}>
                        {r.full_name}
                      </Link>
                    </td>
                    <td style={{ color: "var(--text-muted)" }}>{r.default_branch}</td>
                    <td>
                      {r.is_active ? (
                        <StatusBadge status="success" />
                      ) : (
                        <StatusBadge status="inactive" />
                      )}
                    </td>
                    <td>
                      <Link
                        to={`/repos/${r.owner}/${r.name}`}
                        className="btn btn-sm btn-secondary"
                      >
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

      {/* Recent Activity */}
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
                    <td>
                      <Link to={`/runs/${r.id}`}>#{r.run_number}</Link>
                    </td>
                    <td>{r.workflow_name || "—"}</td>
                    <td>
                      <StatusBadge status={r.conclusion || r.status} />
                    </td>
                    <td>{formatMs(r.total_duration_ms)}</td>
                    <td style={{ color: "var(--text-muted)" }}>
                      {formatDate(r.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
