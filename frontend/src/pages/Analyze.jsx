import React, { useState, useRef, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle, XCircle, Loader, Circle, ChevronDown, ChevronRight,
  Download, Play, GitBranch, Zap, Brain, BarChart2, Code, Search,
} from "lucide-react";
import {
  addRepo, getGitHubRuns, ingestRun, indexRepo,
  getRepoBottlenecks, analyseRun,
} from "../services/api";

// ─── helpers ────────────────────────────────────────────────────────────────

function formatMs(ms) {
  if (!ms && ms !== 0) return "—";
  if (ms >= 60000) return `${(ms / 60000).toFixed(1)}m`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function parseRepoInput(raw) {
  const s = raw.trim();
  // Handle full URL like https://github.com/owner/name
  const match = s.match(/github\.com\/([^/]+\/[^/]+)/);
  if (match) return match[1].replace(/\.git$/, "");
  // Already owner/name
  if (s.includes("/")) return s.replace(/\.git$/, "");
  return s;
}

// ─── StageRow ───────────────────────────────────────────────────────────────

function StageRow({ stage, icon: Icon }) {
  const [expanded, setExpanded] = useState(false);

  const statusIcon = () => {
    if (stage.status === "running")
      return <Loader className="spin-icon" size={18} style={{ color: "var(--accent)" }} />;
    if (stage.status === "success")
      return <CheckCircle size={18} style={{ color: "var(--green)" }} />;
    if (stage.status === "error")
      return <XCircle size={18} style={{ color: "var(--red)" }} />;
    return <Circle size={18} style={{ color: "var(--text-muted)", opacity: 0.4 }} />;
  };

  const borderColor =
    stage.status === "success" ? "var(--green)" :
    stage.status === "error"   ? "var(--red)" :
    stage.status === "running" ? "var(--accent)" :
    "var(--border)";

  return (
    <div className="stage-row" style={{ borderLeftColor: borderColor }}>
      <div
        className="stage-header"
        onClick={() => stage.logs.length > 0 && setExpanded(!expanded)}
        style={{ cursor: stage.logs.length > 0 ? "pointer" : "default" }}
      >
        <div className="stage-header-left">
          {statusIcon()}
          <Icon size={16} style={{ color: "var(--text-muted)" }} />
          <span className="stage-title">{stage.title}</span>
        </div>
        <div className="stage-header-right">
          {stage.summary && (
            <span className="stage-summary">{stage.summary}</span>
          )}
          {stage.logs.length > 0 && (
            expanded
              ? <ChevronDown size={14} style={{ color: "var(--text-muted)" }} />
              : <ChevronRight size={14} style={{ color: "var(--text-muted)" }} />
          )}
        </div>
      </div>

      {expanded && stage.logs.length > 0 && (
        <div className="stage-logs">
          {stage.logs.map((log, i) => (
            <div key={i} className={`log-line log-${log.type || "info"}`}>
              <span className="log-time">{log.time}</span>
              <span className="log-msg">{log.msg}</span>
            </div>
          ))}
        </div>
      )}

      {/* Inline result panel for specific stages */}
      {expanded && stage.result && stage.id === "bottlenecks" && (
        <BottleneckResult data={stage.result} />
      )}
      {expanded && stage.result && stage.id === "analysis" && (
        <AnalysisResult data={stage.result} />
      )}
      {expanded && stage.result && stage.id === "ingest" && (
        <IngestResult data={stage.result} />
      )}
      {expanded && stage.result && stage.id === "index" && (
        <IndexResult data={stage.result} />
      )}
    </div>
  );
}

// ─── Result panels ───────────────────────────────────────────────────────────

function IngestResult({ data }) {
  // data is an array of merged objects: { ...IngestionResult, ...githubRunInfo }
  return (
    <div className="result-panel">
      <table style={{ width: "100%", fontSize: 13 }}>
        <thead>
          <tr>
            <th>Run #</th>
            <th>Workflow</th>
            <th>Branch</th>
            <th>Steps</th>
            <th>Duration</th>
            <th>Slowest Step</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i}>
              <td>
                <Link to={`/runs/${r.run_id}`}>Run #{r.run_number || r.github_run_id}</Link>
              </td>
              <td style={{ color: "var(--text-muted)" }}>{r.workflow_name || "—"}</td>
              <td style={{ color: "var(--text-muted)" }}>{r.head_branch || "—"}</td>
              <td>{r.steps_parsed}</td>
              <td>{formatMs(r.total_duration_ms)}</td>
              <td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-muted)" }}>
                {r.slowest_step ? `${r.slowest_step} (${formatMs(r.slowest_step_ms)})` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function IndexResult({ data }) {
  return (
    <div className="result-panel">
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 13 }}>
        <div><span style={{ color: "var(--text-muted)" }}>Commit SHA: </span>{data.commit_sha?.slice(0, 12)}</div>
        <div><span style={{ color: "var(--text-muted)" }}>Functions: </span><strong>{data.total_functions}</strong></div>
        <div><span style={{ color: "var(--text-muted)" }}>Log calls: </span><strong>{data.total_log_calls}</strong></div>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Languages: </span>
          {data.language_breakdown && Object.entries(data.language_breakdown).map(([lang, count]) => (
            <span key={lang} className="badge badge-info" style={{ marginLeft: 4 }}>{lang}: {count}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function BottleneckResult({ data }) {
  return (
    <div className="result-panel">
      <table style={{ width: "100%", fontSize: 13 }}>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Step</th>
            <th>Score</th>
            <th>Mean</th>
            <th>P95</th>
            <th>% Total</th>
            <th>Trend</th>
          </tr>
        </thead>
        <tbody>
          {data.bottlenecks.map((b) => (
            <tr key={b.rank}>
              <td>#{b.rank}</td>
              <td style={{ maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{b.step_name}</td>
              <td>{b.composite_score?.toFixed(3)}</td>
              <td>{formatMs(b.mean_ms)}</td>
              <td>{formatMs(b.p95_ms)}</td>
              <td>{(b.pct_of_total * 100).toFixed(1)}%</td>
              <td>
                <span className={`badge badge-${b.trend_direction === "increasing" ? "failure" : b.trend_direction === "decreasing" ? "success" : "info"}`}>
                  {b.trend_direction}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)" }}>
        Analyzed {data.total_runs_analyzed} runs · window {data.analysis_window}
      </div>
    </div>
  );
}

function AnalysisResult({ data }) {
  const [expandedSugg, setExpandedSugg] = useState(null);
  return (
    <div className="result-panel">
      {data.root_cause && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 4 }}>Root Cause</div>
          <p style={{ fontSize: 13, lineHeight: 1.6 }}>{data.root_cause}</p>
        </div>
      )}
      {data.anti_patterns?.length > 0 && (
        <div style={{ marginBottom: 12, display: "flex", gap: 6, flexWrap: "wrap" }}>
          {data.anti_patterns.map((ap) => (
            <span key={ap} className="badge badge-warning">{ap}</span>
          ))}
        </div>
      )}
      {data.estimated_total_saving_ms && (
        <div style={{ color: "var(--green)", fontWeight: 600, marginBottom: 12, fontSize: 14 }}>
          Estimated total saving: {formatMs(data.estimated_total_saving_ms)}
        </div>
      )}
      <div style={{ fontSize: 12, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8 }}>
        Suggestions ({data.suggestions?.length || 0})
      </div>
      {data.suggestions?.sort((a, b) => a.rank - b.rank).map((s) => (
        <div key={s.id} className="suggestion-card" style={{ marginBottom: 12 }}>
          <div
            style={{ display: "flex", justifyContent: "space-between", cursor: "pointer", alignItems: "flex-start" }}
            onClick={() => setExpandedSugg(expandedSugg === s.id ? null : s.id)}
          >
            <div>
              <h4 style={{ fontSize: 14, marginBottom: 2 }}>#{s.rank} {s.title}</h4>
              <p style={{ fontSize: 12, color: "var(--text-muted)" }}>{s.description}</p>
            </div>
            <div style={{ display: "flex", gap: 8, flexShrink: 0, marginLeft: 12 }}>
              <span className="badge badge-success">{formatMs(s.estimated_saving_ms)} saved</span>
              <span className={`badge badge-${s.effort === "low" ? "low" : s.effort === "medium" ? "medium" : "high"}`}>{s.effort}</span>
            </div>
          </div>
          {expandedSugg === s.id && (
            <div style={{ marginTop: 8 }}>
              {s.target_file && (
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>
                  File: <code style={{ color: "var(--accent)" }}>{s.target_file}</code>
                  {s.target_function && <> · Function: <code style={{ color: "var(--accent)" }}>{s.target_function}</code></>}
                </div>
              )}
              {s.diff_hint && (
                <div className="diff-block" style={{ marginTop: 6 }}>
                  {s.diff_hint.split("\n").map((line, i) => (
                    <div
                      key={i}
                      className={line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-del" : ""}
                    >{line}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Report generator ────────────────────────────────────────────────────────

function generateReport(repoName, stages, results) {
  const now = new Date().toLocaleString();
  const lines = [
    `# DynamicAnalyzer Report — ${repoName}`,
    ``,
    `**Generated:** ${now}`,
    `**Repository:** \`${repoName}\``,
    ``,
    `---`,
    ``,
    `## Pipeline Execution Summary`,
    ``,
  ];

  stages.forEach((s) => {
    const icon = s.status === "success" ? "✅" : s.status === "error" ? "❌" : "⏭️";
    lines.push(`${icon} **${s.title}** — ${s.summary || s.status}`);
  });

  lines.push(``, `---`, ``);

  // Ingested runs
  if (results.ingestedRuns?.length > 0) {
    lines.push(`## Ingested Runs`, ``);
    lines.push(`| Run # | Workflow | Branch | Steps | Duration | Slowest Step |`);
    lines.push(`|-------|----------|--------|-------|----------|--------------|`);
    results.ingestedRuns.forEach((r) => {
      lines.push(`| #${r.run_number || r.github_run_id} | ${r.workflow_name || "—"} | ${r.head_branch || "—"} | ${r.steps_parsed} | ${formatMs(r.total_duration_ms)} | ${r.slowest_step || "—"} (${formatMs(r.slowest_step_ms)}) |`);
    });
    lines.push(``);
  }

  // Code index
  if (results.codeIndex) {
    lines.push(`## Code Index`, ``);
    const ci = results.codeIndex;
    lines.push(`| Metric | Value |`);
    lines.push(`|--------|-------|`);
    lines.push(`| Commit SHA | \`${ci.commit_sha?.slice(0, 12)}\` |`);
    lines.push(`| Functions | ${ci.total_functions} |`);
    lines.push(`| Log calls | ${ci.total_log_calls} |`);
    if (ci.language_breakdown) {
      Object.entries(ci.language_breakdown).forEach(([lang, count]) => {
        lines.push(`| ${lang} files | ${count} |`);
      });
    }
    lines.push(``);
  }

  // Bottlenecks
  if (results.bottlenecks?.bottlenecks?.length > 0) {
    lines.push(`## Bottleneck Analysis`, ``);
    lines.push(`Analyzed **${results.bottlenecks.total_runs_analyzed}** runs.`, ``);
    lines.push(`| Rank | Step | Score | Mean | P95 | % Total | Trend |`);
    lines.push(`|------|------|-------|------|-----|---------|-------|`);
    results.bottlenecks.bottlenecks.forEach((b) => {
      lines.push(`| #${b.rank} | ${b.step_name} | ${b.composite_score?.toFixed(3)} | ${formatMs(b.mean_ms)} | ${formatMs(b.p95_ms)} | ${(b.pct_of_total * 100).toFixed(1)}% | ${b.trend_direction} |`);
    });
    lines.push(``);
  }

  // AI Analysis
  if (results.analysis) {
    const a = results.analysis;
    lines.push(`## AI Analysis`, ``);
    if (a.root_cause) lines.push(`### Root Cause`, ``, a.root_cause, ``);
    if (a.anti_patterns?.length > 0) {
      lines.push(`### Detected Anti-Patterns`, ``);
      a.anti_patterns.forEach((ap) => lines.push(`- ${ap}`));
      lines.push(``);
    }
    if (a.estimated_total_saving_ms) {
      lines.push(`**Estimated total saving:** ${formatMs(a.estimated_total_saving_ms)}`, ``);
    }
    if (a.suggestions?.length > 0) {
      lines.push(`### Suggestions`, ``);
      lines.push(`| # | Title | Saving | Effort | Confidence |`);
      lines.push(`|---|-------|--------|--------|------------|`);
      a.suggestions.sort((x, y) => x.rank - y.rank).forEach((s) => {
        lines.push(`| ${s.rank} | ${s.title} | ${formatMs(s.estimated_saving_ms)} | ${s.effort} | ${s.confidence_score?.toFixed(2)} |`);
      });
      lines.push(``);
    }
  }

  lines.push(`---`, ``, `*Report generated by DynamicAnalyzer*`);
  return lines.join("\n");
}

// ─── Main Analyze page ───────────────────────────────────────────────────────

const STAGE_DEFS = [
  { id: "repo",        title: "Add Repository",     icon: GitBranch },
  { id: "fetch",       title: "Fetch GitHub Runs",   icon: Search },
  { id: "ingest",      title: "Ingest Runs",         icon: Zap },
  { id: "index",       title: "Build Code Index",    icon: Code },
  { id: "bottlenecks", title: "Compute Bottlenecks", icon: BarChart2 },
  { id: "analysis",    title: "AI Analysis",         icon: Brain },
];

function makeStages() {
  return STAGE_DEFS.map((d) => ({
    ...d,
    status: "pending",
    logs: [],
    summary: null,
    result: null,
  }));
}

export default function Analyze() {
  const [repoInput, setRepoInput] = useState("OpenLake/canonforces");
  const [stages, setStages] = useState(makeStages());
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [results, setResults] = useState({});
  const logsEndRef = useRef(null);

  // ── stage helpers ──────────────────────────────────────────────────────────

  const updateStage = useCallback((id, patch) => {
    setStages((prev) =>
      prev.map((s) => (s.id === id ? { ...s, ...patch } : s))
    );
  }, []);

  const addLog = useCallback((id, msg, type = "info") => {
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setStages((prev) =>
      prev.map((s) =>
        s.id === id ? { ...s, logs: [...s.logs, { time, msg, type }] } : s
      )
    );
  }, []);

  // ── auto-expand running stage ──────────────────────────────────────────────

  // ── run pipeline ─────────────────────────────────────────────────────────

  const runPipeline = async () => {
    const repoFull = parseRepoInput(repoInput);
    if (!repoFull || !repoFull.includes("/")) {
      alert("Enter a valid GitHub repo (owner/name) or URL");
      return;
    }
    const [owner, name] = repoFull.split("/");

    setStages(makeStages());
    setResults({});
    setDone(false);
    setRunning(true);

    const local = {}; // accumulate results across stages for report

    try {
      // ── Stage 1: Add repo ────────────────────────────────────────────────
      updateStage("repo", { status: "running" });
      addLog("repo", `Tracking repository ${repoFull}…`);
      try {
        const repo = await addRepo(repoFull);
        addLog("repo", `✓ Repository ID ${repo.id} — ${repo.full_name}`, "success");
        addLog("repo", `Default branch: ${repo.default_branch}`);
        updateStage("repo", {
          status: "success",
          summary: repo.full_name,
          result: repo,
        });
        local.repo = repo;
      } catch (e) {
        addLog("repo", `✗ ${e.message}`, "error");
        updateStage("repo", { status: "error", summary: e.message });
        throw e;
      }

      // ── Stage 2: Fetch GitHub runs ────────────────────────────────────────
      updateStage("fetch", { status: "running" });
      addLog("fetch", `Fetching recent completed workflow runs for ${repoFull}…`);
      let githubRuns = [];
      try {
        githubRuns = await getGitHubRuns(owner, name, 5);
        if (githubRuns.length === 0) {
          addLog("fetch", "⚠ No completed runs found — trying with broader filter", "warn");
          githubRuns = await getGitHubRuns(owner, name, 10);
        }
        githubRuns.forEach((r) => {
          addLog("fetch", `  • Run #${r.run_number} (ID ${r.run_id}) — ${r.workflow_name} [${r.conclusion}] on ${r.head_branch}`);
        });
        addLog("fetch", `✓ Found ${githubRuns.length} run(s)`, "success");
        updateStage("fetch", {
          status: "success",
          summary: `${githubRuns.length} runs found`,
          result: githubRuns,
        });
        local.githubRuns = githubRuns;
      } catch (e) {
        addLog("fetch", `✗ ${e.message}`, "error");
        updateStage("fetch", { status: "error", summary: e.message });
        throw e;
      }

      // ── Stage 3: Ingest runs ─────────────────────────────────────────────
      updateStage("ingest", { status: "running" });
      addLog("ingest", `Ingesting ${githubRuns.length} run(s) from GitHub Actions logs…`);
      const ingestedRuns = [];
      for (let i = 0; i < githubRuns.length; i++) {
        const gr = githubRuns[i];
        addLog("ingest", `[${i + 1}/${githubRuns.length}] Ingesting run #${gr.run_number} (GitHub ID ${gr.run_id}) — ${gr.workflow_name}…`);
        updateStage("ingest", { summary: `${i + 1}/${githubRuns.length} runs` });
        try {
          const result = await ingestRun(gr.run_id, repoFull);
          // Merge GitHub metadata into ingestion result for display
          const merged = {
            ...result,
            run_number: gr.run_number,
            workflow_name: gr.workflow_name,
            head_branch: gr.head_branch,
            conclusion: gr.conclusion,
          };
          addLog("ingest", `  ✓ Run #${gr.run_number}: ${result.steps_parsed} steps · ${formatMs(result.total_duration_ms)} · slowest: ${result.slowest_step}`, "success");
          ingestedRuns.push(merged);
        } catch (e) {
          addLog("ingest", `  ⚠ Run #${gr.run_number} skipped: ${e.message}`, "warn");
        }
      }
      if (ingestedRuns.length === 0) {
        addLog("ingest", "✗ No runs ingested successfully", "error");
        updateStage("ingest", { status: "error", summary: "0 runs ingested" });
        throw new Error("No runs could be ingested");
      }
      const totalSteps = ingestedRuns.reduce((s, r) => s + r.steps_parsed, 0);
      addLog("ingest", `✓ ${ingestedRuns.length} run(s) ingested · ${totalSteps} total steps`, "success");
      updateStage("ingest", {
        status: "success",
        summary: `${ingestedRuns.length} runs · ${totalSteps} steps`,
        result: ingestedRuns,
      });
      local.ingestedRuns = ingestedRuns;

      // ── Stage 4: Code index ──────────────────────────────────────────────
      updateStage("index", { status: "running" });
      addLog("index", `Building AST code index for ${repoFull}…`);
      addLog("index", "Fetching source files from GitHub (this may take a few minutes for large repos)…");
      try {
        const ci = await indexRepo(owner, name);
        const breakdown = ci.language_breakdown
          ? Object.entries(ci.language_breakdown).map(([l, c]) => `${l}:${c}`).join(", ")
          : "—";
        addLog("index", `✓ Indexed ${ci.total_functions} functions · ${ci.total_log_calls} log calls`, "success");
        addLog("index", `  Commit: ${ci.commit_sha?.slice(0, 12)} · Languages: ${breakdown}`);
        updateStage("index", {
          status: "success",
          summary: `${ci.total_functions} functions · ${ci.total_log_calls} log calls`,
          result: ci,
        });
        local.codeIndex = ci;
      } catch (e) {
        addLog("index", `⚠ Code indexing failed: ${e.message} — continuing`, "warn");
        updateStage("index", { status: "error", summary: `Failed: ${e.message}`, result: null });
        local.codeIndex = null;
        // Don't throw — bottlenecks and analysis can still proceed
      }

      // ── Stage 5: Bottlenecks ─────────────────────────────────────────────
      updateStage("bottlenecks", { status: "running" });
      addLog("bottlenecks", `Computing bottleneck rankings across ${ingestedRuns.length} run(s)…`);
      try {
        const bn = await getRepoBottlenecks(owner, name, 5);
        bn.bottlenecks.forEach((b) => {
          addLog("bottlenecks",
            `  #${b.rank} ${b.step_name}: score=${b.composite_score?.toFixed(3)} mean=${formatMs(b.mean_ms)} trend=${b.trend_direction}`
          );
        });
        addLog("bottlenecks", `✓ Top ${bn.bottlenecks.length} bottlenecks identified · ${bn.total_runs_analyzed} runs analyzed`, "success");
        updateStage("bottlenecks", {
          status: "success",
          summary: `${bn.bottlenecks.length} bottlenecks · ${bn.total_runs_analyzed} runs`,
          result: bn,
        });
        local.bottlenecks = bn;
      } catch (e) {
        addLog("bottlenecks", `✗ ${e.message}`, "error");
        updateStage("bottlenecks", { status: "error", summary: e.message });
        throw e;
      }

      // ── Stage 6: AI analysis ─────────────────────────────────────────────
      updateStage("analysis", { status: "running" });
      const targetRun = ingestedRuns[0]; // most recently ingested (latest run)
      addLog("analysis", `Running AI analysis on run #${targetRun.run_number} (DB id ${targetRun.run_id})…`);
      addLog("analysis", "Assembling context: bottleneck data, trace correlation, source code snippets…");
      addLog("analysis", "Calling claude-sonnet-4-6 — may take 15–30 seconds…");
      try {
        const analysis = await analyseRun(targetRun.run_id, true);
        addLog("analysis", `✓ Analysis complete — model: ${analysis.llm_model || "claude-sonnet-4-6"}`, "success");
        if (analysis.primary_bottleneck) {
          addLog("analysis", `  Primary bottleneck: ${analysis.primary_bottleneck}`);
        }
        if (analysis.estimated_total_saving_ms) {
          addLog("analysis", `  Estimated saving: ${formatMs(analysis.estimated_total_saving_ms)}`);
        }
        addLog("analysis", `  Suggestions: ${analysis.suggestions?.length || 0}`);
        updateStage("analysis", {
          status: "success",
          summary: `${analysis.suggestions?.length || 0} suggestions · ${formatMs(analysis.estimated_total_saving_ms)} saving`,
          result: analysis,
        });
        local.analysis = analysis;
      } catch (e) {
        addLog("analysis", `✗ ${e.message}`, "error");
        updateStage("analysis", { status: "error", summary: e.message });
        // Don't throw — report can still be downloaded with partial data
      }

      setResults(local);
      setDone(true);
    } catch (err) {
      // Pipeline aborted at a critical stage
      console.error("Pipeline error:", err);
    } finally {
      setRunning(false);
    }
  };

  // ── download report ────────────────────────────────────────────────────────

  const downloadReport = () => {
    const repoFull = parseRepoInput(repoInput);
    const md = generateReport(repoFull, stages, results);
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `dynamicanalyzer-${repoFull.replace("/", "-")}-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── render ─────────────────────────────────────────────────────────────────

  const successCount = stages.filter((s) => s.status === "success").length;
  const hasAnyResults = stages.some((s) => s.status !== "pending");

  return (
    <div>
      <div className="page-header">
        <h1>Analyze Repository</h1>
        <p>Run the full DynamicAnalyzer pipeline: ingest → index → bottlenecks → AI analysis</p>
      </div>

      {/* Input form */}
      <div className="card">
        <div className="card-title">Target Repository</div>
        <div style={{ display: "flex", gap: 12 }}>
          <input
            className="form-input"
            placeholder="owner/repo or https://github.com/owner/repo"
            value={repoInput}
            onChange={(e) => setRepoInput(e.target.value)}
            disabled={running}
            onKeyDown={(e) => e.key === "Enter" && !running && runPipeline()}
            style={{ flex: 1 }}
          />
          <button
            className="btn btn-primary"
            onClick={runPipeline}
            disabled={running || !repoInput.trim()}
            style={{ whiteSpace: "nowrap" }}
          >
            {running ? (
              <><Loader size={16} className="spin-icon" /> Running…</>
            ) : (
              <><Play size={16} /> Run Analysis</>
            )}
          </button>
        </div>
        {running && (
          <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-muted)" }}>
            <Loader size={14} className="spin-icon" />
            Pipeline running — {successCount}/{stages.length} stages complete
          </div>
        )}
      </div>

      {/* Pipeline stages */}
      {hasAnyResults && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div className="card-title" style={{ margin: 0 }}>Pipeline Progress</div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              {done && (
                <span className="badge badge-success">
                  <CheckCircle size={12} style={{ display: "inline", marginRight: 4 }} />
                  Complete
                </span>
              )}
              {(done || stages.some((s) => s.status === "success")) && (
                <button className="btn btn-secondary btn-sm" onClick={downloadReport}>
                  <Download size={14} /> Download Report
                </button>
              )}
            </div>
          </div>
          <div style={{ padding: "8px 0" }}>
            {stages.map((stage) => (
              <StageRow
                key={stage.id}
                stage={stage}
                icon={stage.icon}
              />
            ))}
          </div>
        </div>
      )}

      {/* Done summary */}
      {done && results.analysis && (
        <div className="card" style={{ borderLeft: "3px solid var(--green)" }}>
          <div className="card-title" style={{ color: "var(--green)" }}>
            ✓ Analysis Complete
          </div>
          <div className="kpi-grid" style={{ marginBottom: 0 }}>
            {results.ingestedRuns && (
              <div className="kpi-card">
                <div className="kpi-label">Runs Ingested</div>
                <div className="kpi-value">{results.ingestedRuns.length}</div>
              </div>
            )}
            {results.codeIndex && (
              <div className="kpi-card">
                <div className="kpi-label">Functions Indexed</div>
                <div className="kpi-value">{results.codeIndex.total_functions}</div>
              </div>
            )}
            {results.bottlenecks && (
              <div className="kpi-card">
                <div className="kpi-label">Bottlenecks Found</div>
                <div className="kpi-value">{results.bottlenecks.bottlenecks.length}</div>
              </div>
            )}
            {results.analysis && (
              <div className="kpi-card">
                <div className="kpi-label">Estimated Saving</div>
                <div className="kpi-value" style={{ color: "var(--green)" }}>
                  {formatMs(results.analysis.estimated_total_saving_ms)}
                </div>
              </div>
            )}
          </div>
          <div style={{ marginTop: 16, display: "flex", gap: 10 }}>
            {results.repo && (
              <Link
                to={`/repos/${results.repo.owner}/${results.repo.name}`}
                className="btn btn-secondary btn-sm"
              >
                <GitBranch size={14} /> View Repo Runs
              </Link>
            )}
            {results.ingestedRuns?.[0] && (
              <Link
                to={`/runs/${results.ingestedRuns[0].run_id}`}
                className="btn btn-primary btn-sm"
              >
                <BarChart2 size={14} /> View Run Detail
              </Link>
            )}
            <button className="btn btn-secondary btn-sm" onClick={downloadReport}>
              <Download size={14} /> Download Report
            </button>
          </div>
        </div>
      )}

      <div ref={logsEndRef} />
    </div>
  );
}
