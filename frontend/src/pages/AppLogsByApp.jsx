import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { listAppSessions } from "../services/api";

function formatMs(ms) {
  if (!ms && ms !== 0) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function formatDate(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

const STATUS_COLOR = {
  completed: "var(--color-success, #22c55e)",
  failed: "var(--color-error, #ef4444)",
  pending: "var(--text-muted)",
};

export default function AppLogsByApp() {
  const { appName } = useParams();
  const decoded = decodeURIComponent(appName);

  const [sessions, setSessions] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  useEffect(() => {
    listAppSessions()
      .then((all) => setSessions(all.filter((s) => s.app_name === decoded)))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [decoded]);

  if (loading) return <div className="loading">Loading sessions…</div>;
  if (error)   return <div className="error-msg">{error}</div>;

  const totalDur   = sessions.reduce((a, s) => a + (s.total_duration_ms || 0), 0);
  const totalCalls = sessions.reduce((a, s) => a + (s.total_calls || 0), 0);
  const avgDur     = sessions.length ? Math.round(totalDur / sessions.length) : 0;

  // Sort newest first
  const sorted = [...sessions].sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at)
  );

  return (
    <div>
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <Link to="/" style={{ color: "var(--text-muted)", fontSize: 13 }}>Dashboard</Link>
          <span style={{ color: "var(--text-muted)" }}>/</span>
          <span style={{ fontWeight: 700 }}>{decoded}</span>
        </div>
        <h1 style={{ marginTop: 8 }}>{decoded}</h1>
        <p>All log analysis sessions for this application</p>
      </div>

      {/* KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card card">
          <div className="kpi-value">{sessions.length}</div>
          <div className="kpi-label">Sessions</div>
        </div>
        <div className="kpi-card card">
          <div className="kpi-value">{totalCalls}</div>
          <div className="kpi-label">Function calls</div>
        </div>
        <div className="kpi-card card">
          <div className="kpi-value">{formatMs(avgDur)}</div>
          <div className="kpi-label">Avg session duration</div>
        </div>
        <div className="kpi-card card">
          <div className="kpi-value">
            {sessions.filter((s) => s.status === "completed").length}
          </div>
          <div className="kpi-label">Completed</div>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <Link to="/app-logs/upload" className="btn btn-primary">
          + Upload New Session
        </Link>
      </div>

      <div className="card">
        <div className="card-title">Sessions</div>
        {sorted.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            No sessions for <strong>{decoded}</strong> yet.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Format</th>
                  <th>Calls</th>
                  <th>Total time</th>
                  <th>Status</th>
                  <th>Uploaded</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((s, i) => (
                  <tr key={s.id}>
                    <td style={{ color: "var(--text-muted)", fontSize: 13 }}>
                      #{sorted.length - i}
                    </td>
                    <td style={{ color: "var(--text-muted)", fontSize: 13 }}>
                      {s.log_format}
                    </td>
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
    </div>
  );
}
