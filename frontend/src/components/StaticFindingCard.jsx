import React, { useMemo, useState } from "react";
import { Boxes, Brain, CheckSquare, MessageSquare, Shield, Sparkles, Star, TestTube, Zap } from "lucide-react";

const AGENT_META = {
  security: { icon: Shield, label: "Security" },
  performance: { icon: Zap, label: "Performance" },
  architecture: { icon: Boxes, label: "Architecture" },
  test_coverage: { icon: TestTube || CheckSquare, label: "Test Coverage" },
  orchestrator: { icon: Brain, label: "Orchestrator" },
  critique: { icon: MessageSquare, label: "Critique" },
  synthesis: { icon: Sparkles || Star, label: "Synthesis" },
};

const severityStyle = (severity) => {
  switch ((severity || "").toUpperCase()) {
    case "CRITICAL":
      return { background: "var(--red)", color: "white" };
    case "HIGH":
      return { background: "#f97316", color: "white" };
    case "MEDIUM":
      return { background: "var(--amber, #f59e0b)", color: "black" };
    case "LOW":
      return { background: "var(--accent)", color: "white" };
    default:
      return { background: "var(--border)", color: "var(--text-muted)" };
  }
};

export default function StaticFindingCard({ card, jobId }) {
  const [tab, setTab] = useState("developer");
  const [showEvidence, setShowEvidence] = useState(false);
  const [showFix, setShowFix] = useState(false);
  const finding = card.finding || {};
  const meta = AGENT_META[finding.agent_id] || { icon: Shield, label: finding.agent_id || "Agent" };
  const AgentIcon = meta.icon;
  const key = `static-feedback:${jobId}:${finding.file_path}:${finding.start_line}:${finding.title}`;
  const feedback = useMemo(() => localStorage.getItem(key) || "", [key]);

  const setFeedback = (v) => {
    localStorage.setItem(key, v);
  };

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <AgentIcon size={15} />
        <strong>{meta.label}</strong>
        <span className="badge" style={severityStyle(finding.severity)}>{finding.severity}</span>
        <span className="badge badge-info">{finding.confidence}</span>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{finding.file_path}:{finding.start_line}</span>
      </div>
      <div style={{ fontSize: 17, fontWeight: 700, marginTop: 8 }}>{finding.title}</div>

      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        {["developer", "manager", "executive"].map((t) => (
          <button key={t} className={`btn btn-sm ${tab === t ? "btn-primary" : "btn-secondary"}`} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      <p style={{ marginTop: 10, color: "var(--text-muted)" }}>
        {tab === "developer" ? card.explanation_technical : tab === "manager" ? card.explanation_manager : card.explanation_executive}
      </p>

      <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
        <button className="btn btn-sm btn-secondary" onClick={() => setShowEvidence((v) => !v)}>{showEvidence ? "Hide Evidence" : "Show Evidence"}</button>
        <button className="btn btn-sm btn-secondary" onClick={() => setShowFix((v) => !v)}>{showFix ? "Hide Fix" : "Show Fix"}</button>
      </div>
      {showEvidence && (
        <pre className="diff-block" style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>{finding.evidence}</pre>
      )}
      {showFix && (
        <pre className="diff-block" style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
          {String(card.fix_snippet || "").split("\n").map((line, i) => (
            <div key={`${i}-${line}`} className={line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-del" : ""}>{line}</div>
          ))}
        </pre>
      )}

      <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span className="badge badge-info">{card.critique_verdict}</span>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{card.critique_note}</span>
      </div>
      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <button className={`btn btn-sm ${feedback === "up" ? "btn-primary" : "btn-secondary"}`} onClick={() => setFeedback("up")}>👍 Helpful</button>
        <button className={`btn btn-sm ${feedback === "down" ? "btn-primary" : "btn-secondary"}`} onClick={() => setFeedback("down")}>👎 Not Helpful</button>
      </div>
    </div>
  );
}
