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

      {/* App Log Format Guide */}
      <div className="card">
        <div className="card-title">Supported Log Formats</div>
        <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 12 }}>
          Upload any of these log types on the{" "}
          <a href="/app-logs/upload">Upload App Log</a> page.
          Auto-detect mode works for all formats shown here.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Format</th>
                <th>Example line</th>
                <th style={{ whiteSpace: "nowrap" }}>Auto-detected?</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["JSON lines",      `{"func":"process_packet","elapsed_ms":42,"event":"exit"}`,              true],
                ["Spring Boot",     `2024-03-19 10:32:01.456 INFO [main] c.e.Svc - fetchUsers() in 1234ms`, true],
                ["Ruby on Rails",   `Completed 200 OK in 1234ms (Views: 12ms | ActiveRecord: 890ms)`,       true],
                ["Syslog (RFC 3164)", `Mar 19 10:32:01 host app[123]: [TRACE] reassemble_stream() start`,   true],
                ["logfmt (Go/Rust)", `time=2024-01-01T10:00:00Z func=handle_request duration=56ms`,         true],
                ["tshark / Wireshark", `dissect_tcp  elapsed=0.342s`,                                       true],
                ["ENTER / EXIT pairs", `ENTER processPayment  …  EXIT processPayment (2345ms)`,             true],
                ["Heuristic fallback", `[2024-01-01] parse_frame took 12.3ms`,                              true],
                ["Custom regex",    `Named groups: func, duration, unit, timestamp, event`,                 false],
              ].map(([fmt, ex, auto]) => (
                <tr key={fmt}>
                  <td style={{ fontWeight: 600, whiteSpace: "nowrap", padding: "6px 8px" }}>{fmt}</td>
                  <td style={{
                    fontFamily: "monospace",
                    fontSize: 12,
                    color: "var(--text-muted)",
                    wordBreak: "break-all",
                    padding: "6px 8px",
                  }}>{ex}</td>
                  <td style={{ textAlign: "center", padding: "6px 8px" }}>
                    <span className={`badge ${auto ? "badge-success" : ""}`}
                      style={auto ? {} : { background: "var(--bg)", color: "var(--text-muted)", border: "1px solid var(--border)" }}>
                      {auto ? "Yes" : "Manual"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
