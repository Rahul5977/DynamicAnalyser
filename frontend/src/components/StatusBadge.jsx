import React from "react";

export default function StatusBadge({ status, className = "" }) {
  const cls =
    status === "success" || status === "completed"
      ? "badge-success"
      : status === "failure"
      ? "badge-failure"
      : status === "in_progress"
      ? "badge-warning"
      : "badge-info";
  return <span className={`badge ${cls} ${className}`}>{status}</span>;
}

export function EffortBadge({ effort }) {
  const cls = effort === "low" ? "badge-low" : effort === "high" ? "badge-high" : "badge-medium";
  return <span className={`badge ${cls}`}>{effort}</span>;
}

export function TrendIndicator({ direction }) {
  if (direction === "increasing") return <span style={{ color: "var(--red)" }}>&#9650; {direction}</span>;
  if (direction === "decreasing") return <span style={{ color: "var(--green)" }}>&#9660; {direction}</span>;
  return <span style={{ color: "var(--text-muted)" }}>&#9679; {direction}</span>;
}
