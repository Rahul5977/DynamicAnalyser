import React, { useEffect, useState } from "react";
import { Boxes, Brain, MessageSquare, Shield, Sparkles, TestTube, Zap } from "lucide-react";
import StatusBadge from "./StatusBadge";

const AGENT_META = {
  security: { icon: Shield, label: "Security Agent", sq: "security" },
  performance: { icon: Zap, label: "Performance Agent", sq: "performance" },
  architecture: { icon: Boxes, label: "Architecture Agent", sq: "architecture" },
  test_coverage: { icon: TestTube, label: "Test Coverage", sq: "test_coverage" },
  orchestrator: { icon: Brain, label: "Orchestrator", sq: "orchestrator" },
  critique: { icon: MessageSquare, label: "Critique", sq: "critique" },
  synthesis: { icon: Sparkles, label: "Synthesis", sq: "synthesis" },
};

const KNOWN_SEV = new Set(["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]);

function severityBadgeStatus(sev) {
  const u = (sev || "").toUpperCase();
  return KNOWN_SEV.has(u) ? u : "INFO";
}

export default function StaticFindingCard({ card, jobId }) {
  const [tab, setTab] = useState("developer");
  const [showEvidence, setShowEvidence] = useState(false);
  const [showFix, setShowFix] = useState(false);
  const [descExpanded, setDescExpanded] = useState(false);

  const finding = card.finding || {};
  const meta = AGENT_META[finding.agent_id] || {
    icon: Shield,
    label: finding.agent_id || "Agent",
    sq: "default",
  };
  const AgentIcon = meta.icon;
  const sevStatus = severityBadgeStatus(finding.severity);
  const key = `static-feedback:${jobId}:${finding.file_path}:${finding.start_line}:${finding.title}`;
  const [feedback, setFeedbackState] = useState("");
  useEffect(() => {
    setFeedbackState(localStorage.getItem(key) || "");
  }, [key]);

  const setFeedback = (v) => {
    localStorage.setItem(key, v);
    setFeedbackState(v);
  };

  const body =
    tab === "developer"
      ? card.explanation_technical
      : tab === "manager"
        ? card.explanation_manager
        : card.explanation_executive;

  const verdict = (card.critique_verdict || "").toUpperCase();
  const verdictStatus =
    verdict === "CONFIRMED" || verdict === "PLAUSIBLE" || verdict === "DISPUTED" ? verdict : "PLAUSIBLE";

  return (
    <div className="card finding-card-wrap">
      <div className="finding-card-header">
        <div className="finding-card-agent-row">
          <div className={`agent-icon-sq ${meta.sq}`}>
            <AgentIcon size={16} strokeWidth={1.75} />
          </div>
          <span className="badge badge-brand">{meta.label}</span>
          <StatusBadge status={sevStatus} />
          <span className="badge badge-info">{finding.confidence || "—"}</span>
        </div>
        <span className="font-mono text-sm text-muted">
          {finding.file_path}:{finding.start_line}
        </span>
      </div>

      <div className="finding-title">{finding.title}</div>

      <div className="tab-bar tab-bar-inline">
        {["developer", "manager", "executive"].map((t) => (
          <button
            key={t}
            type="button"
            className={`tab-btn ${tab === t ? "active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      <p className={`finding-desc ${descExpanded ? "" : "collapsed"}`}>{body}</p>
      <button
        type="button"
        className="link-muted-btn"
        onClick={() => setDescExpanded((e) => !e)}
      >
        {descExpanded ? "Show less" : "Read more"}
      </button>

      <div className="finding-actions">
        <button
          type="button"
          className="link-muted-btn"
          onClick={() => setShowEvidence((v) => !v)}
        >
          {showEvidence ? "Hide evidence" : "Show evidence"}
        </button>
        <button
          type="button"
          className="link-muted-btn"
          onClick={() => setShowFix((v) => !v)}
        >
          {showFix ? "Hide fix" : "View fix"}
        </button>
      </div>

      {showEvidence && (
        <pre className="evidence-snippet" style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>
          {finding.evidence || "—"}
        </pre>
      )}

      {showFix && (
        <div className="diff-block" style={{ marginTop: 12 }}>
          {String(card.fix_snippet || "")
            .split("\n")
            .map((line, i) => (
              <span
                key={`${i}-${line.slice(0, 12)}`}
                className={`diff-line ${line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-del" : "diff-ctx"}`}
              >
                {line}
              </span>
            ))}
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap" style={{ marginTop: 12 }}>
        {card.estimated_effort && <EffortSpan effort={card.estimated_effort} />}
      </div>

      <div className="finding-card-footer">
        <StatusBadge status={verdictStatus} />
        <span className="critique-note">{card.critique_note || ""}</span>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          className={`btn btn-sm btn-ghost ${feedback === "up" ? "active" : ""}`}
          onClick={() => setFeedback("up")}
        >
          👍 Helpful
        </button>
        <button
          type="button"
          className={`btn btn-sm btn-ghost ${feedback === "down" ? "active" : ""}`}
          onClick={() => setFeedback("down")}
        >
          👎 Not Helpful
        </button>
      </div>
    </div>
  );
}

function EffortSpan({ effort }) {
  const e = (effort || "").toLowerCase();
  const cls = e === "low" ? "badge-green" : e === "high" ? "badge-red" : "badge-amber";
  return <span className={`badge ${cls}`}>Effort: {effort}</span>;
}
