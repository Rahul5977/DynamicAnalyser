const BASE = "/api";

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || err.detail || res.statusText);
  }
  return res.json();
}

// Dashboard
export const getDashboardSummary = () => request("/dashboard/summary");

// Repos
export const listRepos = () => request("/repos");
export const addRepo = (full_name) =>
  request("/repos", {
    method: "POST",
    body: JSON.stringify({ full_name }),
  });
export const getRepoRuns = (owner, name, page = 1) =>
  request(`/repos/${owner}/${name}/runs?page=${page}`);
export const getRepoBottlenecks = (owner, name, topN = 3) =>
  request(`/repos/${owner}/${name}/bottlenecks?top_n=${topN}`);

// Runs
export const getRun = (runId) => request(`/runs/${runId}`);
export const getRunTrace = (runId) => request(`/runs/${runId}/trace`);
export const getLatestAnalysis = (runId) =>
  request(`/runs/${runId}/analysis/latest`);

export const listRunAnalyses = (runId) => request(`/runs/${runId}/analyses`);

export const getAnalysisById = (analysisId) => request(`/analyses/${analysisId}`);

export async function deleteAnalysis(analysisId) {
  const res = await fetch(`${BASE}/analyses/${analysisId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(
      typeof err.detail === "string" ? err.detail : err.error || res.statusText
    );
  }
}

// Analysis
export const analyseRun = (runId, force = false) =>
  request(`/runs/${runId}/analyse`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
export const submitFeedback = (analysisId, data) =>
  request(`/analyses/${analysisId}/feedback`, {
    method: "POST",
    body: JSON.stringify(data),
  });

// Ingest a specific GitHub Actions run
export const ingestRun = (githubRunId, repoFullName) =>
  request(`/runs/${githubRunId}/ingest?repo=${encodeURIComponent(repoFullName)}`, {
    method: "POST",
  });

// Get recent GitHub run IDs for a repo (for ingestion)
export const getGitHubRuns = (owner, name, limit = 5) =>
  request(`/repos/${owner}/${name}/github-runs?limit=${limit}`);

// Index a repo's source code
export const indexRepo = (owner, name) =>
  request(`/repos/${owner}/${name}/index`, { method: "POST" });

// ── App Log Analysis ──────────────────────────────────────────────────────────

function formatApiError(errBody, fallback) {
  const d = errBody?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d))
    return d.map((x) => (typeof x === "object" && x.msg ? x.msg : JSON.stringify(x))).join("; ");
  if (d && typeof d === "object" && typeof d.message === "string") return d.message;
  return errBody?.error || fallback || "Request failed";
}

export const uploadAppLog = (formData) =>
  fetch(`${BASE}/app-logs/upload`, { method: "POST", body: formData }).then(async (r) => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: r.statusText }));
      throw new Error(formatApiError(err, r.statusText));
    }
    return r.json();
  });

export const listAppSessions = () => request("/app-logs/sessions");

export const getAppSession = (id) => request(`/app-logs/sessions/${id}`);

// Phase 3 – detect format from first N lines (called before upload)
export const detectAppLogFormat = (lines, appName = "", customPattern = "") =>
  request("/app-logs/detect-format", {
    method: "POST",
    body: JSON.stringify({ lines, app_name: appName, custom_pattern: customPattern }),
  });

// Phase 4 – source correlation
// Second argument: GitHub URL string, or `{ github_url, local_repo_path?, commit_sha? }`
export const indexSourceForSession = (id, githubUrlOrOpts = "") => {
  const opts =
    typeof githubUrlOrOpts === "string"
      ? { github_url: githubUrlOrOpts }
      : { ...githubUrlOrOpts };
  const github_url = opts.github_url ?? opts.githubUrl ?? "";
  const body = { github_url };
  const local = opts.local_repo_path ?? opts.localRepoPath;
  if (local && String(local).trim()) body.local_repo_path = String(local).trim();
  const sha = opts.commit_sha ?? opts.commitSha;
  if (sha && String(sha).trim()) body.commit_sha = String(sha).trim();
  return request(`/app-logs/sessions/${id}/index-source`, {
    method: "POST",
    body: JSON.stringify(body),
  });
};

export const getAppTrace = (id) => request(`/app-logs/sessions/${id}/trace`);

// Phase 5 – AI analysis (returns full AnalysisResponse like CI/CD)
// targetFunctions: string[] | null — if provided, scopes the analysis to those functions
export const analyseAppSession = (id, force = false, targetFunctions = null) =>
  request(`/app-logs/sessions/${id}/analyse?force=${force}`, {
    method: "POST",
    body: JSON.stringify(targetFunctions ? { target_functions: targetFunctions } : {}),
  });

export const getAppSessionAnalysis = (id) =>
  request(`/app-logs/sessions/${id}/analysis`);

export const listAppSessionAnalyses = (id) =>
  request(`/app-logs/sessions/${id}/analyses`);

// ── Static analysis (multi-domain AST + Claude) ───────────────────────────────

export const startStaticAnalysis = (payload) =>
  request("/static-analysis/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const listStaticReports = (limit = 30) =>
  request(`/static-analysis/reports?limit=${limit}`);

export const getStaticReport = (reportId) =>
  request(`/static-analysis/reports/${reportId}`);

export const getDebtTrend = (sessionId) =>
  request(`/app-logs/sessions/${sessionId}/debt-trend`);

export const getSessionRegressions = (sessionId) =>
  request(`/app-logs/sessions/${sessionId}/regressions`);

export const resolveRegressionAlert = (alertId) =>
  request(`/app-logs/regressions/${alertId}/resolve`, { method: "POST" });

export const getActiveRegressions = (appName = null) =>
  request(
    appName
      ? `/app-logs/regressions/active?app_name=${encodeURIComponent(appName)}`
      : "/app-logs/regressions/active"
  );

export const submitAppFeedback = (sessionId, suggestionId, verdict) =>
  request(`/app-logs/sessions/${sessionId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ suggestion_id: suggestionId, verdict, comment: null }),
  });

export const getPatternConfidence = (appName) =>
  request(`/app-logs/apps/${encodeURIComponent(appName)}/pattern-confidence`);

export const sendChatMessage = (sessionId, message, history) =>
  request(`/app-logs/sessions/${sessionId}/chat`, {
    method: "POST",
    body: JSON.stringify({ message, history }),
  });

export const getChatHistory = (sessionId) =>
  request(`/app-logs/sessions/${sessionId}/chat/history`);

export const getAppBenchmark = (appName) =>
  request(`/benchmarks/app-sessions?app_name=${encodeURIComponent(appName)}`);

export const getFleetSummary = () => request("/benchmarks/fleet-summary");
