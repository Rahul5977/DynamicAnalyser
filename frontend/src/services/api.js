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

export const uploadAppLog = (formData) =>
  fetch(`${BASE}/app-logs/upload`, { method: "POST", body: formData }).then(
    async (r) => {
      if (!r.ok) {
        const err = await r.json().catch(() => ({ error: r.statusText }));
        throw new Error(err.detail || err.error || r.statusText);
      }
      return r.json();
    }
  );

export const listAppSessions = () => request("/app-logs/sessions");

export const getAppSession = (id) => request(`/app-logs/sessions/${id}`);

// Phase 3 – detect format from first N lines (called before upload)
export const detectAppLogFormat = (lines, appName = "", customPattern = "") =>
  request("/app-logs/detect-format", {
    method: "POST",
    body: JSON.stringify({ lines, app_name: appName, custom_pattern: customPattern }),
  });

// Phase 4 – source correlation
export const indexSourceForSession = (id, githubUrl = "") =>
  request(`/app-logs/sessions/${id}/index-source`, {
    method: "POST",
    body: JSON.stringify({ github_url: githubUrl }),
  });

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
