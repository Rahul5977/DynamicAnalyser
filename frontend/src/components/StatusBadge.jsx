import React from "react";

const MAP = {
  success: { cls: "badge-green", label: "Success" },
  completed: { cls: "badge-green", label: "Completed" },
  running: { cls: "badge-brand", label: "Running" },
  in_progress: { cls: "badge-brand", label: "Running" },
  pending: { cls: "badge-gray", label: "Pending" },
  failed: { cls: "badge-red", label: "Failed" },
  error: { cls: "badge-red", label: "Error" },
  failure: { cls: "badge-red", label: "Failed" },
  increasing: { cls: "badge-red", label: "↑ Increasing" },
  decreasing: { cls: "badge-green", label: "↓ Decreasing" },
  stable: { cls: "badge-gray", label: "→ Stable" },
  inactive: { cls: "badge-gray", label: "Inactive" },
  CRITICAL: { cls: "badge-critical", label: "CRITICAL" },
  HIGH: { cls: "badge-high", label: "HIGH" },
  MEDIUM: { cls: "badge-medium", label: "MEDIUM" },
  LOW: { cls: "badge-low", label: "LOW" },
  INFO: { cls: "badge-info", label: "INFO" },
  CONFIRMED: { cls: "badge-green", label: "✓ CONFIRMED" },
  PLAUSIBLE: { cls: "badge-amber", label: "~ PLAUSIBLE" },
  DISPUTED: { cls: "badge-red", label: "✗ DISPUTED" },
};

export default function StatusBadge({ status, className = "" }) {
  const m = MAP[status] || { cls: "badge-gray", label: status };
  return <span className={`badge ${m.cls} ${className}`.trim()}>{m.label}</span>;
}

export function EffortBadge({ effort }) {
  const cls = effort === "low" ? "badge-low" : effort === "high" ? "badge-high" : "badge-medium";
  return <span className={`badge ${cls}`}>{effort}</span>;
}

export function TrendIndicator({ direction }) {
  if (direction === "increasing") {
    return <span className="kpi-trend-down">▲ {direction}</span>;
  }
  if (direction === "decreasing") {
    return <span className="kpi-trend-up">▼ {direction}</span>;
  }
  return <span className="text-muted">● {direction}</span>;
}
