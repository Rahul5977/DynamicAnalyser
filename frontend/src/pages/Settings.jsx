import React, { useState, useEffect } from "react";
import { addRepo, listRepos } from "../services/api";

export default function Settings() {
  const [repoName, setRepoName] = useState("");
  const [repos, setRepos] = useState([]);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listRepos()
      .then(setRepos)
      .catch((e) => setError(e.message));
  }, []);

  const handleAdd = async (e) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    if (!repoName.includes("/")) {
      setError("Enter repo in owner/name format");
      return;
    }
    setLoading(true);
    try {
      await addRepo(repoName);
      setMessage(`Added ${repoName}`);
      setRepoName("");
      const updated = await listRepos();
      setRepos(updated);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
        <p>Manage repositories and integrations</p>
      </div>

      {/* Add Repository */}
      <div className="card">
        <div className="card-title">Connect a Repository</div>
        <form onSubmit={handleAdd}>
          <div className="form-group">
            <label>GitHub Repository (owner/name)</label>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                className="form-input"
                placeholder="octocat/Hello-World"
                value={repoName}
                onChange={(e) => setRepoName(e.target.value)}
                style={{ maxWidth: 400 }}
              />
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? "Adding..." : "Add Repository"}
              </button>
            </div>
          </div>
        </form>
        {message && (
          <p style={{ color: "var(--green)", fontSize: 14 }}>{message}</p>
        )}
        {error && <p className="error-msg">{error}</p>}
      </div>

      {/* Tracked Repos */}
      <div className="card">
        <div className="card-title">Tracked Repositories ({repos.length})</div>
        {repos.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
            No repositories tracked yet.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Repository</th>
                  <th>Default Branch</th>
                  <th>Status</th>
                  <th>Added</th>
                </tr>
              </thead>
              <tbody>
                {repos.map((r) => (
                  <tr key={r.id}>
                    <td>{r.full_name}</td>
                    <td style={{ color: "var(--text-muted)" }}>{r.default_branch}</td>
                    <td>
                      <span className={`badge ${r.is_active ? "badge-success" : "badge-failure"}`}>
                        {r.is_active ? "active" : "inactive"}
                      </span>
                    </td>
                    <td style={{ color: "var(--text-muted)" }}>
                      {new Date(r.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Webhook Configuration */}
      <div className="card">
        <div className="card-title">GitHub Webhook Configuration</div>
        <p style={{ color: "var(--text-muted)", fontSize: 14, marginBottom: 12 }}>
          Set up a webhook to automatically analyse pipeline runs when they complete.
        </p>
        <div style={{ background: "var(--bg)", padding: 16, borderRadius: "var(--radius)", fontSize: 13 }}>
          <p style={{ marginBottom: 8 }}><strong>1. Go to your repository Settings → Webhooks → Add webhook</strong></p>
          <div className="form-group">
            <label>Payload URL</label>
            <input
              className="form-input"
              value={`${window.location.origin}/api/webhook/github`}
              readOnly
              onClick={(e) => e.target.select()}
            />
          </div>
          <div className="form-group">
            <label>Content type</label>
            <input className="form-input" value="application/json" readOnly />
          </div>
          <p style={{ marginBottom: 8 }}><strong>2. Select "Workflow runs" under individual events</strong></p>
          <p><strong>3. Set a webhook secret and configure it in your .env as GITHUB_WEBHOOK_SECRET</strong></p>
        </div>
      </div>
    </div>
  );
}
