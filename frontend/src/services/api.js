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
export const getRepoAnalytics = (owner, name, window = 30) =>
  request(`/repos/${owner}/${name}/analytics?window=${window}`);
export const getRepoInsights = (owner, name) =>
  request(`/repos/${owner}/${name}/insights`);
export const getStepStats = (owner, name, stepName) =>
  request(`/repos/${owner}/${name}/step/${encodeURIComponent(stepName)}/stats`);

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
export const getAnalysis = (analysisId) =>
  request(`/analyses/${analysisId}`);
export const submitFeedback = (analysisId, data) =>
  request(`/analyses/${analysisId}/feedback`, {
    method: "POST",
    body: JSON.stringify(data),
  });

// Demo
export const seedDemo = () =>
  request("/demo/seed", { method: "POST" });
