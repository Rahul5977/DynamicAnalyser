import React, { useEffect, useState, useRef, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import {
  getRun,
  getRunTrace,
  getLatestAnalysis,
  analyseRun,
  submitFeedback,
  listRunAnalyses,
  getAnalysisById,
  deleteAnalysis,
} from "../services/api";
import StatusBadge from "../components/StatusBadge";
import Flamegraph from "../components/Flamegraph";
import SuggestionCard from "../components/SuggestionCard";

function formatMs(ms) {
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function RunDetail() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);
  const [trace, setTrace] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [analysing, setAnalysing] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [error, setError] = useState(null);
  const bottleneckRef = useRef(null);

  const rid = parseInt(runId, 10);

  const refreshReportsAndAnalysis = useCallback(async () => {
    const items = await listRunAnalyses(rid).catch(() => []);
    setReports(items);
    const completed = items.find((x) => x.status === "completed");
    const pick = completed || items[0];
    if (pick) {
      try {
        setAnalysis(await getAnalysisById(pick.id));
      } catch {
        setAnalysis(null);
      }
    } else {
      setAnalysis(null);
    }
  }, [rid]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      getRun(rid),
      getRunTrace(rid).catch(() => null),
      listRunAnalyses(rid).catch(() => []),
    ])
      .then(async ([r, t, items]) => {
        setRun(r);
        setTrace(t);
        setReports(items);
        const completed = items.find((x) => x.status === "completed");
        const pick = completed || items[0];
        if (pick) {
          try {
            setAnalysis(await getAnalysisById(pick.id));
          } catch {
            setAnalysis(null);
          }
        } else {
          try {
            const a = await getLatestAnalysis(rid);
            setAnalysis(a);
          } catch {
            setAnalysis(null);
          }
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [runId, rid]);

  const handleAnalyse = async () => {
    setAnalysing(true);
    try {
      const a = await analyseRun(rid, true);
      setAnalysis(a);
      await refreshReportsAndAnalysis();
    } catch (e) {
      setError(e.message);
    } finally {
      setAnalysing(false);
    }
  };

  const handleDeleteReport = async (analysisId) => {
    if (!window.confirm("Delete this analysis report permanently? This cannot be undone.")) {
      return;
    }
    setDeletingId(analysisId);
    setError(null);
    try {
      await deleteAnalysis(analysisId);
      await refreshReportsAndAnalysis();
    } catch (e) {
      setError(e.message);
    } finally {
      setDeletingId(null);
    }
  };

  const handleLoadReport = async (analysisId) => {
    try {
      const a = await getAnalysisById(analysisId);
      setAnalysis(a);
    } catch (e) {
      setError(e.message);
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
  if (error && !run) return <div className="error-msg">{error}</div>;
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
      <div className="breadcrumbs">
        <Link to="/">Home</Link> <span>/</span>
        <span>Run #{run.run_number}</span>
      </div>

      <div className="page-header">
        <h1>Run #{run.run_number}</h1>
      </div>

      {error && <div className="error-msg" style={{ marginBottom: 16 }}>{error}</div>}

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
          <p className="text-muted">No step data available</p>
        )}
      </div>

      {trace && (
        <div className="card">
          <div className="card-title">Trace Correlation</div>
          <p className="text-muted" style={{ fontSize: 14 }}>
            Matched {trace.matched_steps} of {trace.total_steps} steps to source code (
            {Math.round(trace.match_rate * 100)}% match rate)
          </p>
        </div>
      )}

      <div className="card" ref={bottleneckRef}>
        <div
          className="card-header"
          style={{ marginBottom: 12, flexWrap: "wrap", gap: 12 }}
        >
          <div className="card-title" style={{ margin: 0 }}>AI Analysis</div>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleAnalyse}
            disabled={analysing}
          >
            {analysing ? "Analysing..." : analysis ? "Re-analyse" : "Run Analysis"}
          </button>
        </div>

        {reports.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div className="card-subtitle" style={{ marginBottom: 8 }}>
              Saved reports ({reports.length})
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Created</th>
                    <th>Status</th>
                    <th>Model</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((row) => (
                    <tr key={row.id}>
                      <td className="text-sm">{formatDate(row.created_at)}</td>
                      <td>
                        <StatusBadge status={row.status} />
                      </td>
                      <td className="text-sm text-muted">{row.llm_model || "—"}</td>
                      <td>
                        <div className="flex gap-2 flex-wrap">
                          <button
                            type="button"
                            className="btn btn-sm btn-secondary"
                            onClick={() => handleLoadReport(row.id)}
                          >
                            View
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm btn-danger"
                            disabled={deletingId === row.id}
                            onClick={() => handleDeleteReport(row.id)}
                          >
                            {deletingId === row.id ? "Deleting…" : "Delete"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {analysis ? (
          <div>
            <div style={{ marginBottom: 16 }}>
              <h4 className="kpi-label" style={{ marginBottom: 4 }}>
                Root Cause
              </h4>
              <p style={{ fontSize: 14 }}>{analysis.root_cause}</p>
            </div>

            {(analysis.anti_patterns?.length ?? 0) > 0 && (
              <div style={{ marginBottom: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {analysis.anti_patterns.map((ap) => (
                  <span key={ap} className="badge badge-warning">{ap}</span>
                ))}
              </div>
            )}

            {analysis.estimated_total_saving_ms ? (
              <p className="kpi-trend-up" style={{ fontWeight: 600, marginBottom: 16, fontSize: 14 }}>
                Estimated total saving: {formatMs(analysis.estimated_total_saving_ms)}
              </p>
            ) : null}

            <h4 className="kpi-label" style={{ marginBottom: 12 }}>
              Suggestions ({analysis.suggestions?.length ?? 0})
            </h4>
            {(analysis.suggestions || [])
              .slice()
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
          <p className="text-muted" style={{ fontSize: 14 }}>
            No analysis yet. Click &quot;Run Analysis&quot; to generate AI-powered insights.
          </p>
        )}
      </div>
    </div>
  );
}
