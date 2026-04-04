import React, { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { uploadAppLog } from "../services/api";

const FORMATS = [
  { value: "auto",    label: "Auto-detect" },
  { value: "json",    label: "JSON lines  (e.g. {\"func\":\"...\",\"elapsed_ms\":42})" },
  { value: "syslog",  label: "Syslog  (RFC 3164 / journald)" },
  { value: "tshark",  label: "tshark / Wireshark text export" },
  { value: "logfmt",  label: "logfmt  (key=value, common in Go / Rust)" },
  { value: "custom",  label: "Custom regex pattern" },
];

export default function AppLogUpload() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);

  const [file, setFile]           = useState(null);
  const [dragging, setDragging]   = useState(false);
  const [appName, setAppName]     = useState("");
  const [logFormat, setLogFormat] = useState("auto");
  const [sourceRepo, setSourceRepo] = useState("");
  const [customPattern, setCustomPattern] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError]         = useState(null);
  const [progress, setProgress]   = useState(""); // status message

  // ── Drag-and-drop handlers ─────────────────────────────────────────────────
  const onDragOver = useCallback((e) => {
    e.preventDefault();
    setDragging(true);
  }, []);

  const onDragLeave = useCallback(() => setDragging(false), []);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  }, []);

  const onFileChange = (e) => {
    if (e.target.files[0]) setFile(e.target.files[0]);
  };

  // ── Submit ─────────────────────────────────────────────────────────────────
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) { setError("Please select or drop a log file."); return; }
    if (!appName.trim()) { setError("Please enter an application name."); return; }
    if (logFormat === "custom" && !customPattern.trim()) {
      setError("Please enter a custom regex pattern."); return;
    }

    setUploading(true);
    setError(null);
    setProgress("Uploading and parsing log file…");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("app_name", appName.trim());
    formData.append("log_format", logFormat);
    formData.append("source_repo", sourceRepo.trim());
    formData.append("custom_pattern", customPattern.trim());

    try {
      const result = await uploadAppLog(formData);
      setProgress(result.message || "Upload complete.");
      navigate(`/app-logs/sessions/${result.session_id}`);
    } catch (err) {
      setError(err.message || "Upload failed.");
      setProgress("");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ maxWidth: 680, margin: "0 auto" }}>
      <div className="page-header">
        <h1>Upload Application Log</h1>
        <p>
          Analyse function-call timings from any program that produces log output —
          nginx, tshark, gunicorn, a Go service, a JVM app, or anything in between.
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        {/* ── Drag-and-drop zone ── */}
        <div
          className="card"
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={() => !file && fileInputRef.current?.click()}
          style={{
            border: `2px dashed ${dragging ? "var(--color-primary, #6366f1)" : "var(--border)"}`,
            background: dragging ? "var(--bg-hover, rgba(99,102,241,.07))" : undefined,
            cursor: file ? "default" : "pointer",
            textAlign: "center",
            padding: "32px 24px",
            transition: "border-color .15s, background .15s",
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".log,.txt,.csv,.json,.pcap,.out,.err,text/*"
            style={{ display: "none" }}
            onChange={onFileChange}
          />
          {file ? (
            <div>
              <div style={{ fontSize: 32, marginBottom: 8 }}>📄</div>
              <strong>{file.name}</strong>
              <div style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 4 }}>
                {(file.size / 1024).toFixed(1)} KB
              </div>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                style={{ marginTop: 12 }}
                onClick={(e) => { e.stopPropagation(); setFile(null); }}
              >
                Remove
              </button>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 40, marginBottom: 8 }}>📂</div>
              <p style={{ margin: 0, fontWeight: 500 }}>
                Drag &amp; drop a log file here
              </p>
              <p style={{ margin: "4px 0 0", color: "var(--text-muted)", fontSize: 13 }}>
                or click to browse · .log .txt .json .out or any plain-text format
              </p>
            </div>
          )}
        </div>

        {/* ── Fields ── */}
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>
              Application name <span style={{ color: "red" }}>*</span>
            </span>
            <input
              className="input"
              type="text"
              placeholder="e.g. nginx, tshark, my-go-service, gunicorn"
              value={appName}
              onChange={(e) => setAppName(e.target.value)}
              required
              style={{
                padding: "8px 12px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "var(--bg-input, var(--bg-card))",
                color: "inherit",
                fontSize: 14,
              }}
            />
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>Log format</span>
            <select
              value={logFormat}
              onChange={(e) => setLogFormat(e.target.value)}
              style={{
                padding: "8px 12px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "var(--bg-input, var(--bg-card))",
                color: "inherit",
                fontSize: 14,
              }}
            >
              {FORMATS.map((f) => (
                <option key={f.value} value={f.value}>{f.label}</option>
              ))}
            </select>
          </label>

          {logFormat === "custom" && (
            <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span style={{ fontWeight: 600, fontSize: 14 }}>
                Custom regex pattern
              </span>
              <input
                className="input"
                type="text"
                placeholder={String.raw`(?P<func>\w+)\s+took\s+(?P<duration>[\d.]+)\s*(?P<unit>ms|s)`}
                value={customPattern}
                onChange={(e) => setCustomPattern(e.target.value)}
                style={{
                  padding: "8px 12px",
                  borderRadius: 6,
                  border: "1px solid var(--border)",
                  background: "var(--bg-input, var(--bg-card))",
                  color: "inherit",
                  fontFamily: "monospace",
                  fontSize: 13,
                }}
              />
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                Named groups: <code>func</code> (required) · <code>duration</code> · <code>unit</code> ·{" "}
                <code>timestamp</code> · <code>event</code> (start|end)
              </span>
            </label>
          )}

          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>
              Source code GitHub URL
              <span style={{ color: "var(--text-muted)", fontWeight: 400 }}> (optional)</span>
            </span>
            <input
              className="input"
              type="url"
              placeholder="https://github.com/owner/repo"
              value={sourceRepo}
              onChange={(e) => setSourceRepo(e.target.value)}
              style={{
                padding: "8px 12px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "var(--bg-input, var(--bg-card))",
                color: "inherit",
                fontSize: 14,
              }}
            />
            <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
              Used to correlate slow functions back to source lines (future feature).
            </span>
          </label>
        </div>

        {/* ── Feedback ── */}
        {error && (
          <div className="error-msg" style={{ marginBottom: 12 }}>{error}</div>
        )}
        {progress && !error && (
          <div style={{ color: "var(--text-muted)", fontSize: 14, marginBottom: 12 }}>
            {progress}
          </div>
        )}

        <button
          type="submit"
          className="btn btn-primary"
          disabled={uploading}
          style={{ width: "100%" }}
        >
          {uploading ? "Uploading & Parsing…" : "Upload and Analyse"}
        </button>
      </form>

      {/* ── Format guide ── */}
      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-title">Supported log formats</div>
        <table style={{ fontSize: 13, width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <th style={{ textAlign: "left", padding: "4px 8px" }}>Format</th>
              <th style={{ textAlign: "left", padding: "4px 8px" }}>Example line</th>
            </tr>
          </thead>
          <tbody>
            {[
              ["JSON", `{"func":"process_packet","elapsed_ms":42,"event":"exit"}`],
              ["syslog", `Mar 19 10:32:01 host app[123]: [TRACE] reassemble_stream() start`],
              ["tshark", `dissect_tcp  elapsed=0.342s`],
              ["logfmt", `time=2024-01-01T10:00:00Z func=handle_request duration=56ms`],
              ["heuristic", `[2024-01-01] parse_frame took 12.3ms`],
            ].map(([fmt, ex]) => (
              <tr key={fmt} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "6px 8px", fontWeight: 600 }}>{fmt}</td>
                <td style={{ padding: "6px 8px", fontFamily: "monospace", color: "var(--text-muted)", wordBreak: "break-all" }}>{ex}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
