import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bot,
  Brain,
  Check,
  CheckCircle,
  Flame,
  GitBranch,
  MessageCircle,
  Shield,
  X,
  Zap,
} from "lucide-react";
import {
  getActiveRegressions,
  getDashboardSummary,
  listRepos,
  listStaticJobs,
} from "../services/api";
import KPICard from "../components/KPICard";
import StatusBadge from "../components/StatusBadge";

function formatMs(ms) {
  if (!ms && ms !== 0) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function formatRunDuration(ms) {
  if (ms === null || ms === undefined) return "—";
  const totalSeconds = Math.round(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function workflowLabel(run) {
  const name = (run.workflow_name || "Workflow").trim();
  const branch = run.head_branch ? ` · ${run.head_branch}` : "";
  return `#${run.run_number} · ${name}${branch}`;
}

function formatDate(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [repos, setRepos] = useState([]);
  const [regressionCount, setRegressionCount] = useState(0);
  const [staticFindingSum, setStaticFindingSum] = useState(0);
  const [health, setHealth] = useState({ api: false, database: false, github: false });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [s, r, regressions, jobs, hRes, ghRes] = await Promise.all([
          getDashboardSummary().catch(() => null),
          listRepos().catch(() => []),
          getActiveRegressions().catch(() => []),
          listStaticJobs().catch(() => []),
          fetch("/api/health").catch(() => null),
          fetch("/api/repos").catch(() => null),
        ]);
        if (cancelled) return;
        setSummary(s);
        setRepos(r || []);
        setRegressionCount((regressions || []).length);
        const completedJobs = (jobs || []).filter((j) => j.status === "completed");
        setStaticFindingSum(completedJobs.reduce((acc, j) => acc + (j.finding_count || 0), 0));
        let apiOk = false;
        let dbOk = false;
        if (hRes && hRes.ok) {
          apiOk = true;
          const hj = await hRes.json().catch(() => ({}));
          dbOk = hj.database === "healthy";
        }
        setHealth({
          api: apiOk,
          database: dbOk,
          github: !!(ghRes && ghRes.ok),
        });
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const recentRuns = (summary?.recent_runs || []).slice(0, 8);
  const heroFindings = Math.max(
    0,
    (summary?.total_analyses || 0) - regressionCount + Math.floor(staticFindingSum / 4)
  );

  if (loading) {
    return (
      <div className="section fade-in">
        <div className="skeleton" style={{ height: 140, marginBottom: 24 }} />
        <div className="kpi-grid">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="skeleton" style={{ height: 96 }} />
          ))}
        </div>
        <div className="skeleton" style={{ height: 280 }} />
      </div>
    );
  }

  if (error) {
    return <div className="error-msg">{error}</div>;
  }

  return (
    <div className="fade-in">
      <section className="card dashboard-hero-card">
        <div>
          <div className="dashboard-hero-title">CodeAnalyser</div>
          <p className="dashboard-hero-sub">
            Enterprise-grade multi-agent analysis for modern codebases
          </p>
          <div className="dashboard-hero-actions">
            <Link to="/analyze" className="btn btn-primary btn-lg">
              <GitBranch size={18} strokeWidth={1.75} />
              Analyze Repository
            </Link>
            <Link to="/static-analysis" className="btn btn-secondary btn-lg">
              <Shield size={18} strokeWidth={1.75} />
              Static Analysis
            </Link>
          </div>
        </div>
        <div className="hero-stats-strip">
          <div className="hero-stat-pill">
            <span className="hero-stat-pill-value">{summary?.total_repos ?? 0}</span>
            <span className="hero-stat-pill-label">Repos tracked</span>
          </div>
          <div className="hero-stat-pill">
            <span className="hero-stat-pill-value">{summary?.total_analyses ?? 0}</span>
            <span className="hero-stat-pill-label">Analyses run</span>
          </div>
          <div className="hero-stat-pill">
            <span className="hero-stat-pill-value">{heroFindings}</span>
            <span className="hero-stat-pill-label">Findings resolved</span>
          </div>
        </div>
      </section>

      <div className="kpi-grid section">
        <KPICard label="Repositories Tracked" value={summary?.total_repos ?? 0} />
        <KPICard label="Total Runs Ingested" value={summary?.total_runs ?? 0} />
        <KPICard label="AI Analyses Done" value={summary?.total_analyses ?? 0} />
        <KPICard
          label="Average Time Saved"
          value={formatMs(summary?.avg_saving_ms)}
          sub="per completed analysis"
        />
        <KPICard
          label="Active Regressions"
          value={regressionCount}
          valueClassName={regressionCount > 0 ? "regression-bad" : "regression-ok"}
        />
      </div>

      <div className="grid-two-65-35">
        <div>
          <div className="card">
            <div className="card-header">
              <div>
                <div className="card-title">Recent Repositories</div>
                <div className="card-subtitle">Tracked GitHub projects</div>
              </div>
            </div>
            {repos.length === 0 ? (
              <div className="empty-state">
                <div className="empty-state-icon">
                  <GitBranch size={24} />
                </div>
                <h3>No repositories yet</h3>
                <p>Analyze or connect a repo from Settings to populate this list.</p>
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Repo</th>
                      <th>Last Run</th>
                      <th>Duration</th>
                      <th>Status</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {repos.slice(0, 8).map((r) => (
                      <tr key={r.id}>
                        <td>
                          <Link to={`/repos/${r.owner}/${r.name}`}>{r.full_name}</Link>
                        </td>
                        <td className="text-muted text-sm">—</td>
                        <td className="text-muted text-sm">—</td>
                        <td>
                          <span className="flex items-center gap-2">
                            <span
                              className={`status-dot ${r.is_active ? "success" : "failure"}`}
                            />
                            {r.is_active ? (
                              <StatusBadge status="success" />
                            ) : (
                              <StatusBadge status="inactive" />
                            )}
                          </span>
                        </td>
                        <td>
                          <Link
                            to={`/repos/${r.owner}/${r.name}`}
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

          <div className="card">
            <div className="card-header">
              <div>
                <div className="card-title">Recent Pipeline Runs</div>
                <div className="card-subtitle">Latest CI/CD ingests</div>
              </div>
            </div>
            {recentRuns.length === 0 ? (
              <div className="empty-state">
                <div className="empty-state-icon">
                  <Zap size={24} />
                </div>
                <h3>No runs yet</h3>
                <p>Ingest workflow runs from the Analyze page to see them here.</p>
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Workflow</th>
                      <th>Status</th>
                      <th>Duration</th>
                      <th>Date</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentRuns.map((run) => {
                      const c = run.conclusion || run.status || "";
                      const dot =
                        c === "success" || c === "completed"
                          ? "success"
                          : c === "failure" || c === "failed"
                            ? "failure"
                            : "running";
                      return (
                        <tr key={run.id}>
                          <td>
                            <Link to={`/runs/${run.id}`}>#{run.run_number}</Link>
                          </td>
                          <td>
                            <div className="text-sm" style={{ fontWeight: 600 }}>
                              {workflowLabel(run)}
                            </div>
                            <div className="text-sm text-muted">Run {run.github_run_id}</div>
                          </td>
                          <td>
                            <span className="flex items-center gap-2">
                              <span className={`status-dot ${dot}`} />
                              <StatusBadge status={c || "pending"} />
                            </span>
                          </td>
                          <td>{formatRunDuration(run.total_duration_ms)}</td>
                          <td className="text-muted text-sm">{formatDate(run.created_at)}</td>
                          <td>
                            <Link to={`/runs/${run.id}`} className="btn btn-sm btn-secondary">
                              View
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
        </div>

        <div>
          <div className="card">
            <div className="card-title">Platform Capabilities</div>
            <div className="card-subtitle" style={{ marginBottom: 16 }}>
              Static, dynamic, and log-native intelligence
            </div>
            <div className="feature-tiles-grid">
              <Link to="/app-logs/upload" className="feature-tile">
                <div className="feature-tile-icon orange">
                  <Flame size={20} />
                </div>
                <div>
                  <div className="feature-tile-label">Flamegraph</div>
                  <div className="feature-tile-desc">Call-tree visualization from logs</div>
                </div>
              </Link>
              <Link to="/analyze" className="feature-tile">
                <div className="feature-tile-icon indigo">
                  <Bot size={20} />
                </div>
                <div>
                  <div className="feature-tile-label">AI Root Cause</div>
                  <div className="feature-tile-desc">CI/CD bottleneck attribution</div>
                </div>
              </Link>
              <Link to="/static-analysis" className="feature-tile">
                <div className="feature-tile-icon teal">
                  <Shield size={20} />
                </div>
                <div>
                  <div className="feature-tile-label">Static SAST</div>
                  <div className="feature-tile-desc">Multi-agent security &amp; architecture</div>
                </div>
              </Link>
              <Link to="/app-logs/upload" className="feature-tile">
                <div className="feature-tile-icon purple">
                  <MessageCircle size={20} />
                </div>
                <div>
                  <div className="feature-tile-label">Chat AI</div>
                  <div className="feature-tile-desc">Ask questions about sessions</div>
                </div>
              </Link>
            </div>
          </div>

          <div className="card">
            <div className="card-title">System Health</div>
            <ul className="health-checklist">
              <li>
                {health.api ? (
                  <Check size={16} className="kpi-trend-up" />
                ) : (
                  <X size={16} className="kpi-trend-down" />
                )}
                API connected
              </li>
              <li>
                {health.database ? (
                  <Check size={16} className="kpi-trend-up" />
                ) : (
                  <X size={16} className="kpi-trend-down" />
                )}
                Database healthy
              </li>
              <li>
                {health.github ? (
                  <Check size={16} className="kpi-trend-up" />
                ) : (
                  <X size={16} className="kpi-trend-down" />
                )}
                GitHub token valid
              </li>
            </ul>
          </div>
        </div>
      </div>

      <section className="section card" id="how-it-works">
        <div className="section-header">
          <h2 className="section-title">How It Works</h2>
        </div>
        <div className="how-it-works-row">
          <div className="how-step">
            <div className="how-step-icon bg-gray">
              <GitBranch size={18} />
            </div>
            <div className="how-step-num">Step 1</div>
            <div className="how-step-title">Connect Repo</div>
            <div className="how-step-desc">Add GitHub projects or upload structured logs.</div>
          </div>
          <div className="how-step">
            <div className="how-step-icon bg-brand">
              <Zap size={18} />
            </div>
            <div className="how-step-num">Step 2</div>
            <div className="how-step-title">Run Pipeline</div>
            <div className="how-step-desc">Ingest runs, index source, score bottlenecks.</div>
          </div>
          <div className="how-step">
            <div className="how-step-icon bg-purple">
              <Brain size={18} />
            </div>
            <div className="how-step-num">Step 3</div>
            <div className="how-step-title">AI Analyses</div>
            <div className="how-step-desc">Specialist models explain root cause and risk.</div>
          </div>
          <div className="how-step">
            <div className="how-step-icon bg-green">
              <CheckCircle size={18} />
            </div>
            <div className="how-step-num">Step 4</div>
            <div className="how-step-title">Get Fixes</div>
            <div className="how-step-desc">Export actionable diffs and health reports.</div>
          </div>
        </div>
      </section>
    </div>
  );
}
