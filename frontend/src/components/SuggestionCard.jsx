import React, { useState } from "react";
import { EffortBadge } from "./StatusBadge";

function formatMs(ms) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function renderDiff(diff) {
  if (!diff) return null;
  return diff.split("\n").map((line, i) => {
    let cls = "";
    if (line.startsWith("+") && !line.startsWith("+++")) cls = "diff-add";
    else if (line.startsWith("-") && !line.startsWith("---")) cls = "diff-del";
    return (
      <span key={i} className={cls}>
        {line}
        {"\n"}
      </span>
    );
  });
}

export default function SuggestionCard({ suggestion, onFeedback }) {
  const [expanded, setExpanded] = useState(false);
  const diff = suggestion.enriched_diff || suggestion.diff_hint;

  return (
    <div className="suggestion-card">
      <h4>
        #{suggestion.rank} {suggestion.title}
      </h4>
      <p>{suggestion.description}</p>
      <div className="suggestion-meta">
        {suggestion.target_file && (
          <span>
            {suggestion.target_file}
            {suggestion.target_function ? `:${suggestion.target_function}` : ""}
          </span>
        )}
        <span style={{ color: "var(--green)", fontWeight: 600 }}>
          ~{formatMs(suggestion.estimated_saving_ms)} saving
        </span>
        <EffortBadge effort={suggestion.effort} />
        {suggestion.confidence_score != null && (
          <span>
            Confidence: {Math.round(suggestion.confidence_score * 100)}%
          </span>
        )}
        {suggestion.anti_pattern && (
          <span className="badge badge-warning">{suggestion.anti_pattern}</span>
        )}
      </div>
      {diff && (
        <>
          <button
            className="btn btn-secondary btn-sm"
            style={{ marginTop: 8 }}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Hide diff" : "Show diff"}
          </button>
          {expanded && <div className="diff-block">{renderDiff(diff)}</div>}
        </>
      )}
      {onFeedback && (
        <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
          <button
            className="btn btn-sm btn-primary"
            onClick={() => onFeedback(suggestion.id, "accepted")}
          >
            Accept
          </button>
          <button
            className="btn btn-sm btn-secondary"
            onClick={() => onFeedback(suggestion.id, "rejected")}
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
