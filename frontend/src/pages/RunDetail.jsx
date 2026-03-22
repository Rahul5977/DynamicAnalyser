import React, { useEffect, useState, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  getRun, getRunTrace, getLatestAnalysis, analyseRun, submitFeedback,
  getRepoRuns,
} from "../services/api";
import StatusBadge from "../components/StatusBadge";
import Flamegraph from "../components/Flamegraph";
import SuggestionCard from "../components/SuggestionCard";

function formatMs(ms) {
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

export default function RunDetail() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);
  const [trace, setTrace] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [trend, setTrend] = useState([]);
  const [loading, setLoading] = useState(true);
  const [analysing, setAnalysing] = useState(false);
  const [error, setError] = useState(null);
  const bottleneckRef = useRef(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const id = parseInt(runId, 10);

    Promise.all([
      getRun(id),
      getRunTrace(id).catch(() => null),
      getLatestAnalysis(id).catch(() => null),
    ])
      .then(([r, t, a]) => {
        setRun(r);
        setTrace(t);
        setAnalysis(a);
        // Fetch trend data
        if (r.github_run_id) {
          // We need repo info to fetch runs — derive from run data
          // The run doesn't have repo info directly in the schema, so we'll skip trend for now
          // unless we can parse it from context
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [runId]);

  const handleAnalyse = async () => {
    setAnalysing(true);
    try {
      const a = await analyseRun(parseInt(runId, 10), true);
      setAnalysis(a);
    } catch (e) {
      setError(e.message);
    } finally {
      setAnalysing(false);
    }
  };

  const handleFeedback = async (suggestionId, verdict) => {
    if (!analysis) return;
    try {
      await submitFeedback(analysis.id, {
        suggestion_id: suggestionId,
        verdict,
      });
    } catch (e) {
      console.error("Feedback failed:", e);
    }
  };

  if (loading) return <div className="loading">Loading run details...</div>;
  if (error) return <div className="error-msg">{error}</div>;
  if (!run) return <div className="error-msg">Run not found</div>;

  const steps = trace ? trace.steps : run.step_timings || [];
  const stepStats = {};
  if (trace) {
    trace.steps.forEach((s) => {
      stepStats[s.step_name] = { p50_ms: s.duration_ms * 0.8, p95_ms: s.duration_ms * 1.2 };
    });
  }

  return (
    <div>
      {/* Breadcrumbs */}
      <div className="breadcrumbs">
        <Link to="/">Home</Link> <span>/</span>
        <span>Run #{run.run_number}</span>
      </div>

      <div className="page-header">
        <h1>Run #{run.run_number}</h1>
      </div>

      {/* Metadata bar */}
      <div className="kpi-grid" style={{ marginBottom: 24 }}>
        <div className="kpi-card">
          <div className="kpi-label">Status</div>
          <div style={{ marginTop: 4 }}>
            <StatusBadge status={run.conclusion || run.status} />
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total Duration</div>
          <div className="kpi-value">{formatMs(run.total_duration_ms)}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Branch</div>
          <div className="kpi-value" style={{ fontSize: 16 }}>{run.head_branch || "—"}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Workflow</div>
          <div className="kpi-value" style={{ fontSize: 16 }}>{run.workflow_name || "—"}</div>
        </div>
      </div>

      {/* Flamegraph */}
      <div className="card">
        <div className="card-title">Pipeline Flamegraph</div>
        {steps.length > 0 ? (
          <Flamegraph
            steps={steps}
            targetMs={15000}
            stepStats={stepStats}
            onStepClick={() => {
              bottleneckRef.current?.scrollIntoView({ behavior: "smooth" });
            }}
          />
        ) : (
          <p style={{ color: "var(--text-muted)" }}>No step data available</p>
        )}
      </div>

      {/* Trace match info */}
      {trace && (
        <div className="card">
          <div className="card-title">Trace Correlation</div>
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            Matched {trace.matched_steps} of {trace.total_steps} steps to source code (
            {Math.round(trace.match_rate * 100)}% match rate)
          </p>
        </div>
      )}

      {/* AI Analysis Panel */}
      <div className="card" ref={bottleneckRef}>
        <div
          className="card-title"
          style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
        >
          <span>AI Analysis</span>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleAnalyse}
            disabled={analysing}
          >
            {analysing ? "Analysing..." : analysis ? "Re-analyse" : "Run Analysis"}
          </button>
        </div>

        {analysis ? (
          <div>
            {/* Root cause */}
            <div style={{ marginBottom: 16 }}>
              <h4 style={{ fontSize: 14, color: "var(--text-muted)", marginBottom: 4 }}>
                Root Cause
              </h4>
              <p style={{ fontSize: 14 }}>{analysis.root_cause}</p>
            </div>

            {/* Anti-patterns */}
            {analysis.anti_patterns.length > 0 && (
              <div style={{ marginBottom: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {analysis.anti_patterns.map((ap) => (
                  <span key={ap} className="badge badge-warning">{ap}</span>
                ))}
              </div>
            )}

            {/* Estimated saving */}
            {analysis.estimated_total_saving_ms && (
              <p style={{ color: "var(--green)", fontWeight: 600, marginBottom: 16 }}>
                Estimated total saving: {formatMs(analysis.estimated_total_saving_ms)}
              </p>
            )}

            {/* Suggestions */}
            <h4 style={{ fontSize: 14, color: "var(--text-muted)", marginBottom: 12 }}>
              Suggestions ({analysis.suggestions.length})
            </h4>
            {analysis.suggestions
              .sort((a, b) => a.rank - b.rank)
              .map((s) => (
                <SuggestionCard
                  key={s.id}
                  suggestion={s}
                  onFeedback={handleFeedback}
                />
              ))}
          </div>
        ) : (
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            No analysis yet. Click "Run Analysis" to generate AI-powered insights.
          </p>
        )}
      </div>
    </div>
  );
}
