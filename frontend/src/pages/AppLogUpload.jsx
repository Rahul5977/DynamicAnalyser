import React, { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { uploadAppLog, detectAppLogFormat } from "../services/api";

const FORMATS = [
  { value: "auto",       label: "Auto-detect" },
  { value: "json",       label: "JSON lines  (e.g. {\"func\":\"…\",\"elapsed_ms\":42})" },
  { value: "spring",     label: "Spring Boot  (2024-03-19 10:32:01 INFO [main] …)" },
  { value: "rails",      label: "Ruby on Rails  (Completed 200 OK in 1234ms)" },
  { value: "syslog",     label: "Syslog  (RFC 3164 / journald)" },
  { value: "logfmt",     label: "logfmt  (key=value, common in Go / Rust)" },
  { value: "tshark",     label: "tshark / Wireshark text export" },
  { value: "enter_exit", label: "Paired ENTER / EXIT tracing  (generic)" },
  { value: "custom",     label: "Custom regex pattern" },
];

const FORMAT_LABELS = Object.fromEntries(FORMATS.map((f) => [f.value, f.label.split("  ")[0]]));

function formatMs(ms) {
  if (!ms && ms !== 0) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

// ── Detect-format preview panel ───────────────────────────────────────────────

function DetectPreview({ detection, onOverride, override }) {
  if (!detection) return null;
  const { format, confidence, sample_records } = detection;
  const displayFmt = override || format;
  const confPct = Math.round(confidence * 100);

  return (
    <div className="card" style={{ borderLeft: `3px solid ${confPct >= 60 ? "#22c55e" : confPct >= 35 ? "#f59e0b" : "#ef4444"}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15 }}>
            Detected format: {FORMAT_LABELS[format] || format}
            <span style={{
              marginLeft: 10,
              fontSize: 12,
              fontWeight: 600,
              color: confPct >= 60 ? "#22c55e" : confPct >= 35 ? "#f59e0b" : "#ef4444",
            }}>
              {confPct}% confidence
            </span>
          </div>
          {sample_records.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>
                Preview — first {sample_records.length} records found:
              </div>
              <table style={{ fontSize: 13, borderCollapse: "collapse", width: "100%" }}>
                <tbody>
                  {sample_records.map((r, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td style={{ padding: "3px 12px 3px 0", fontFamily: "monospace", fontWeight: 600 }}>
                        {r.func_name}
                      </td>
                      <td style={{
                        padding: "3px 0",
                        color: r.duration_ms > 5000 ? "#ef4444" : r.duration_ms > 1000 ? "#f59e0b" : "#22c55e",
                        fontWeight: 600,
                        whiteSpace: "nowrap",
                      }}>
                        → {formatMs(r.duration_ms)}
                        {r.duration_ms > 5000 && (
                          <span style={{ marginLeft: 6, fontSize: 11 }}>← likely bottleneck</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {sample_records.length === 0 && (
            <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 6 }}>
              No timing records found in the preview sample.
              The parser may still extract data from the full file.
            </p>
          )}
        </div>
      </div>

      {/* Override dropdown */}
      <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
          Format looks wrong?
        </span>
        <select
          value={override || ""}
          onChange={(e) => onOverride(e.target.value || null)}
          style={{
            padding: "4px 10px",
            borderRadius: 6,
            border: "1px solid var(--border)",
            background: "var(--bg-input, var(--bg-card))",
            color: "inherit",
            fontSize: 13,
          }}
        >
          <option value="">Use auto-detected ({FORMAT_LABELS[format] || format})</option>
          {FORMATS.filter((f) => f.value !== "auto").map((f) => (
            <option key={f.value} value={f.value}>{f.label.split("  ")[0]}</option>
          ))}
        </select>
      </div>
    </div>
  );
}

// ── Main upload page ──────────────────────────────────────────────────────────

export default function AppLogUpload() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);

  const [file, setFile]               = useState(null);
  const [dragging, setDragging]       = useState(false);
  const [appName, setAppName]         = useState("");
  const [logFormat, setLogFormat]     = useState("auto");
  const [sourceRepo, setSourceRepo]   = useState("");
  const [customPattern, setCustomPattern] = useState("");
  const [uploading, setUploading]     = useState(false);
  const [error, setError]             = useState(null);
  const [progress, setProgress]       = useState("");

  // Phase 3: detect-format state
  const [detection, setDetection]     = useState(null);   // DetectFormatResponse
  const [detecting, setDetecting]     = useState(false);
  const [formatOverride, setFormatOverride] = useState(null);

  // ── File selection ────────────────────────────────────────────────────────

  const handleFile = useCallback(async (selected) => {
    setFile(selected);
    setDetection(null);
    setFormatOverride(null);
    setError(null);

    // Read first 80 lines and call detect-format
    if (!selected) return;
    setDetecting(true);
    try {
      const text = await selected.text();
      const lines = text.split("\n").slice(0, 80);
      const result = await detectAppLogFormat(lines, appName, customPattern);
      setDetection(result);
    } catch (e) {
      // Detection failure is non-fatal — user can still upload
      console.warn("Format detection failed:", e.message);
    } finally {
      setDetecting(false);
    }
  }, [appName, customPattern]);

  const onDragOver = (e) => { e.preventDefault(); setDragging(true); };
  const onDragLeave = () => setDragging(false);
  const onDrop = useCallback((e) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, [handleFile]);
  const onFileChange = (e) => { if (e.target.files[0]) handleFile(e.target.files[0]); };

  // ── Submit ────────────────────────────────────────────────────────────────

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file)          { setError("Please select or drop a log file.");         return; }
    if (!appName.trim()){ setError("Please enter an application name.");          return; }
    if (logFormat === "custom" && !customPattern.trim()) {
      setError("Please enter a custom regex pattern."); return;
    }

    const resolvedFormat = formatOverride || (logFormat !== "auto" ? logFormat : detection?.format || "auto");

    setUploading(true); setError(null);
    setProgress("Uploading and parsing log file…");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("app_name", appName.trim());
    formData.append("log_format", resolvedFormat);
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
    <div style={{ maxWidth: 700, margin: "0 auto" }}>
      <div className="page-header">
        <h1>Upload Application Log</h1>
        <p>
          Analyse function-call timings from any program — nginx, tshark, gunicorn,
          Spring Boot, Rails, a Go service, or anything that produces log output.
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
            border: `2px dashed ${dragging ? "var(--color-primary,#6366f1)" : "var(--border)"}`,
            background: dragging ? "rgba(99,102,241,.07)" : undefined,
            cursor: file ? "default" : "pointer",
            textAlign: "center",
            padding: "32px 24px",
            transition: "border-color .15s",
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".log,.txt,.csv,.json,.out,.err,text/*"
            style={{ display: "none" }}
            onChange={onFileChange}
          />
          {file ? (
            <div>
              <div style={{ fontSize: 32, marginBottom: 8 }}>📄</div>
              <strong>{file.name}</strong>
              <div style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 4 }}>
                {(file.size / 1024).toFixed(1)} KB
                {detecting && <span style={{ marginLeft: 8 }}>· detecting format…</span>}
              </div>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                style={{ marginTop: 12 }}
                onClick={(e) => { e.stopPropagation(); setFile(null); setDetection(null); }}
              >
                Remove
              </button>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 40, marginBottom: 8 }}>📂</div>
              <p style={{ margin: 0, fontWeight: 500 }}>Drag &amp; drop a log file here</p>
              <p style={{ margin: "4px 0 0", color: "var(--text-muted)", fontSize: 13 }}>
                or click to browse · .log .txt .json .out or any plain-text format
              </p>
            </div>
          )}
        </div>

        {/* ── Phase 3: detect preview ── */}
        <DetectPreview
          detection={detection}
          override={formatOverride}
          onOverride={setFormatOverride}
        />

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
              style={inputStyle}
            />
          </label>

          {/* Only show format picker if user wants to override AND no detect preview yet */}
          {!detection && (
            <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span style={{ fontWeight: 600, fontSize: 14 }}>Log format</span>
              <select value={logFormat} onChange={(e) => setLogFormat(e.target.value)} style={inputStyle}>
                {FORMATS.map((f) => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
            </label>
          )}

          {(logFormat === "custom" || formatOverride === "custom") && (
            <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span style={{ fontWeight: 600, fontSize: 14 }}>Custom regex pattern</span>
              <input
                className="input"
                type="text"
                placeholder={String.raw`(?P<func>\w+)\s+took\s+(?P<duration>[\d.]+)\s*(?P<unit>ms|s)`}
                value={customPattern}
                onChange={(e) => setCustomPattern(e.target.value)}
                style={{ ...inputStyle, fontFamily: "monospace", fontSize: 13 }}
              />
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                Named groups: <code>func</code> · <code>duration</code> · <code>unit</code> ·{" "}
                <code>timestamp</code> · <code>event</code> (start|end)
              </span>
            </label>
          )}

          {/* Phase 4: source repo */}
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
              Source code
              <span style={{ color: "var(--text-muted)", fontWeight: 400 }}> (optional)</span>
            </div>
            <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "0 0 8px" }}>
              Without source: the system finds bottlenecks and gives general advice.<br />
              With source: it shows the exact line and suggests a code diff.
            </p>
            <input
              className="input"
              type="url"
              placeholder="https://github.com/owner/repo"
              value={sourceRepo}
              onChange={(e) => setSourceRepo(e.target.value)}
              style={inputStyle}
            />
          </div>
        </div>

        {error   && <div className="error-msg" style={{ marginBottom: 12 }}>{error}</div>}
        {progress && !error && (
          <div style={{ color: "var(--text-muted)", fontSize: 14, marginBottom: 12 }}>{progress}</div>
        )}

        <button type="submit" className="btn btn-primary" disabled={uploading} style={{ width: "100%" }}>
          {uploading ? "Uploading & Parsing…" : "Upload and Analyse"}
        </button>
      </form>

      {/* ── Format reference ── */}
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
              ["JSON",        `{"func":"process_packet","elapsed_ms":42,"event":"exit"}`],
              ["Spring Boot", `2024-03-19 10:32:01.456 INFO [main] c.e.Svc - fetchUsers() in 1234ms`],
              ["Rails",       `Completed 200 OK in 1234ms (Views: 12ms | ActiveRecord: 890ms)`],
              ["syslog",      `Mar 19 10:32:01 host app[123]: [TRACE] reassemble_stream() start`],
              ["logfmt",      `time=2024-01-01T10:00:00Z func=handle_request duration=56ms`],
              ["tshark",      `dissect_tcp  elapsed=0.342s`],
              ["ENTER/EXIT",  `ENTER processPayment  …  EXIT processPayment (2345ms)`],
              ["heuristic",   `[2024-01-01] parse_frame took 12.3ms`],
            ].map(([fmt, ex]) => (
              <tr key={fmt} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "6px 8px", fontWeight: 600, whiteSpace: "nowrap" }}>{fmt}</td>
                <td style={{
                  padding: "6px 8px",
                  fontFamily: "monospace",
                  color: "var(--text-muted)",
                  wordBreak: "break-all",
                  fontSize: 12,
                }}>
                  {ex}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const inputStyle = {
  padding: "8px 12px",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--bg-input, var(--bg-card))",
  color: "inherit",
  fontSize: 14,
  width: "100%",
  boxSizing: "border-box",
};
