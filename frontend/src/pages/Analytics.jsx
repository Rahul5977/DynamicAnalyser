import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, AreaChart, Area,
  BarChart, Bar,
} from "recharts";
import { listRepos, getRepoAnalytics, getRepoInsights } from "../services/api";

function formatMs(ms) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

export default function Analytics() {
  const [repos, setRepos] = useState([]);
  const [selectedRepo, setSelectedRepo] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [insights, setInsights] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listRepos()
      .then((r) => {
        setRepos(r);
        if (r.length > 0) setSelectedRepo(r[0]);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedRepo) return;
    setLoading(true);
    const [owner, name] = selectedRepo.full_name.split("/");
    Promise.all([
      getRepoAnalytics(owner, name).catch(() => null),
      getRepoInsights(owner, name).catch(() => null),
    ])
      .then(([a, i]) => { setAnalytics(a); setInsights(i); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selectedRepo]);

  if (loading && !analytics) return <div className="loading">Loading analytics...</div>;
  if (error) return <div className="error-msg">{error}</div>;

  // Build step evolution as stacked data
  const stepEvolutionByRun = {};
  if (analytics) {
    analytics.step_evolution.forEach((pt) => {
      if (!stepEvolutionByRun[pt.run_number]) {
        stepEvolutionByRun[pt.run_number] = { run: `#${pt.run_number}` };
      }
      stepEvolutionByRun[pt.run_number][pt.step_name] = pt.duration_ms;
    });
  }
  const stackedData = Object.values(stepEvolutionByRun);
  const stepNames = analytics
    ? [...new Set(analytics.step_evolution.map((p) => p.step_name))]
    : [];
  const COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#3b82f6", "#ec4899"];

  // Anti-pattern frequency for bar chart
  const apData = analytics
    ? Object.entries(analytics.anti_pattern_frequency).map(([name, count]) => ({
        name,
        count,
      }))
    : [];

  return (
    <div>
      <div className="page-header">
        <h1>Analytics</h1>
        <p>Performance trends and pattern analysis</p>
      </div>

      {/* Repo selector */}
      {repos.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <select
            className="form-input"
            style={{ width: 300 }}
            value={selectedRepo?.id || ""}
            onChange={(e) => {
              const r = repos.find((r) => r.id === parseInt(e.target.value));
              setSelectedRepo(r);
            }}
          >
            {repos.map((r) => (
              <option key={r.id} value={r.id}>{r.full_name}</option>
            ))}
          </select>
        </div>
      )}

      {analytics && (
        <>
          {/* Duration Trend */}
          <div className="card">
            <div className="card-title">Pipeline Duration Trend</div>
            {analytics.duration_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={analytics.duration_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2e3a" />
                  <XAxis
                    dataKey="run_number"
                    tick={{ fill: "#8b8fa3", fontSize: 12 }}
                    tickFormatter={(v) => `#${v}`}
                  />
                  <YAxis
                    tick={{ fill: "#8b8fa3", fontSize: 12 }}
                    tickFormatter={formatMs}
                  />
                  <Tooltip
                    contentStyle={{ background: "#1a1d27", border: "1px solid #2a2e3a" }}
                    formatter={(v) => formatMs(v)}
                    labelFormatter={(v) => `Run #${v}`}
                  />
                  <ReferenceLine y={15000} stroke="#ef4444" strokeDasharray="5 5" label="Target" />
                  <Line
                    type="monotone"
                    dataKey="total_duration_ms"
                    stroke="#6366f1"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    name="Duration"
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p style={{ color: "var(--text-muted)" }}>Not enough data for trend</p>
            )}
          </div>

          {/* Step Breakdown Evolution */}
          <div className="card">
            <div className="card-title">Step Breakdown Evolution</div>
            {stackedData.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={stackedData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2e3a" />
                  <XAxis dataKey="run" tick={{ fill: "#8b8fa3", fontSize: 12 }} />
                  <YAxis tick={{ fill: "#8b8fa3", fontSize: 12 }} tickFormatter={formatMs} />
                  <Tooltip
                    contentStyle={{ background: "#1a1d27", border: "1px solid #2a2e3a" }}
                    formatter={(v) => formatMs(v)}
                  />
                  {stepNames.map((name, i) => (
                    <Area
                      key={name}
                      type="monotone"
                      dataKey={name}
                      stackId="1"
                      fill={COLORS[i % COLORS.length]}
                      stroke={COLORS[i % COLORS.length]}
                      fillOpacity={0.6}
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p style={{ color: "var(--text-muted)" }}>Not enough data</p>
            )}
          </div>

          {/* Anti-Pattern Frequency */}
          <div className="card">
            <div className="card-title">Anti-Pattern Frequency</div>
            {apData.length > 0 ? (
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={apData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2e3a" />
                  <XAxis type="number" tick={{ fill: "#8b8fa3", fontSize: 12 }} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={180}
                    tick={{ fill: "#8b8fa3", fontSize: 11 }}
                  />
                  <Tooltip
                    contentStyle={{ background: "#1a1d27", border: "1px solid #2a2e3a" }}
                  />
                  <Bar dataKey="count" fill="#f59e0b" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p style={{ color: "var(--text-muted)" }}>No anti-patterns detected yet</p>
            )}
          </div>
        </>
      )}

      {/* Insights Summary */}
      {insights && insights.total_analyses > 0 && (
        <div className="card">
          <div className="card-title">Insights Summary</div>
          <div className="kpi-grid">
            <div className="kpi-card">
              <div className="kpi-label">Total Analyses</div>
              <div className="kpi-value">{insights.total_analyses}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Most Common Bottleneck</div>
              <div className="kpi-value" style={{ fontSize: 16 }}>
                {insights.most_common_bottleneck || "—"}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Avg Saving per Analysis</div>
              <div className="kpi-value">{formatMs(insights.avg_total_saving_ms)}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
