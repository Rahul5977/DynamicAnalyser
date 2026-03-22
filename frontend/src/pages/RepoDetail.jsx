import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getRepoRuns, getRepoBottlenecks } from "../services/api";
import StatusBadge, { TrendIndicator } from "../components/StatusBadge";

function formatMs(ms) {
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function formatDate(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export default function RepoDetail() {
  const { owner, name } = useParams();
  const [runs, setRuns] = useState(null);
  const [bottlenecks, setBottlenecks] = useState(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getRepoRuns(owner, name, page),
      getRepoBottlenecks(owner, name).catch(() => null),
    ])
      .then(([r, b]) => { setRuns(r); setBottlenecks(b); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [owner, name, page]);

  if (loading) return <div className="loading">Loading repository...</div>;
  if (error) return <div className="error-msg">{error}</div>;

  return (
    <div>
      <div className="breadcrumbs">
        <Link to="/">Home</Link> <span>/</span>
        <span>{owner}/{name}</span>
      </div>

      <div className="page-header">
        <h1>{owner}/{name}</h1>
        <p>Pipeline runs and bottleneck analysis</p>
      </div>

      {/* Bottleneck Summary */}
      {bottlenecks && bottlenecks.bottlenecks.length > 0 && (
        <div className="card">
          <div className="card-title">Top Bottlenecks</div>
          <div className="grid-3">
            {bottlenecks.bottlenecks.map((b) => (
              <div key={b.rank} className="kpi-card">
                <div className="kpi-label">#{b.rank} {b.step_name}</div>
                <div className="kpi-value">{formatMs(b.p95_ms)}</div>
                <div className="kpi-sub">
                  p95 &middot; {Math.round(b.pct_of_total * 100)}% of total &middot;{" "}
                  <TrendIndicator direction={b.trend_direction} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Runs Table */}
      {runs && (
        <div className="card">
          <div className="card-title">
            Pipeline Runs ({runs.total} total)
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Workflow</th>
                  <th>Branch</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {runs.runs.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/runs/${r.id}`}>#{r.run_number}</Link>
                    </td>
                    <td>{r.workflow_name || "—"}</td>
                    <td style={{ color: "var(--text-muted)" }}>{r.head_branch || "—"}</td>
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
          {/* Pagination */}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              className="btn btn-sm btn-secondary"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </button>
            <span style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: "28px" }}>
              Page {page}
            </span>
            <button
              className="btn btn-sm btn-secondary"
              disabled={runs.runs.length < runs.page_size}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
