import React from "react";

export default function KPICard({ label, value, sub, trend, trendDir, valueClassName = "" }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${valueClassName}`.trim()}>{value ?? "—"}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
      {trend && (
        <div className={trendDir === "up" ? "kpi-trend-up" : "kpi-trend-down"}>
          {trendDir === "up" ? "↑" : "↓"} {trend}
        </div>
      )}
    </div>
  );
}
