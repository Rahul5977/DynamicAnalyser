import React, { useState } from "react";

function getBarColor(durationMs, p50, p95) {
  if (p95 && durationMs > p95) return "red";
  if (p50 && durationMs > p50) return "amber";
  return "green";
}

function formatMs(ms) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

export default function Flamegraph({ steps, targetMs = 15000, stepStats = {}, onStepClick }) {
  const [tooltip, setTooltip] = useState(null);
  const maxDuration = Math.max(...steps.map((s) => s.duration_ms), targetMs);

  return (
    <div className="flamegraph">
      {steps
        .sort((a, b) => a.step_number - b.step_number)
        .map((step) => {
          const pct = (step.duration_ms / maxDuration) * 100;
          const stats = stepStats[step.step_name] || {};
          const color = getBarColor(step.duration_ms, stats.p50_ms, stats.p95_ms);
          const targetPct = (targetMs / maxDuration) * 100;

          return (
            <div className="flame-bar-wrap" key={step.step_name}>
              <div className="flame-label" title={step.step_name}>
                {step.step_name}
              </div>
              <div
                className="flame-bar-container"
                onClick={() => onStepClick && onStepClick(step.step_name)}
                onMouseEnter={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  setTooltip({
                    step,
                    stats,
                    x: rect.left + rect.width / 2,
                    y: rect.top - 10,
                  });
                }}
                onMouseLeave={() => setTooltip(null)}
              >
                <div
                  className={`flame-bar ${color}`}
                  style={{ width: `${Math.max(pct, 1)}%` }}
                >
                  {pct > 15 ? `${step.step_name} ${formatMs(step.duration_ms)}` : ""}
                </div>
                <div className="flame-target" style={{ left: `${targetPct}%` }} />
              </div>
              <div className="flame-duration">{formatMs(step.duration_ms)}</div>
            </div>
          );
        })}
      {tooltip && (
        <div
          className="tooltip-box"
          style={{
            position: "fixed",
            left: tooltip.x,
            top: tooltip.y,
            transform: "translate(-50%, -100%)",
          }}
        >
          <dl>
            <dt>Step</dt>
            <dd>{tooltip.step.step_name}</dd>
            <dt>Duration</dt>
            <dd>{formatMs(tooltip.step.duration_ms)}</dd>
            {tooltip.stats.p50_ms != null && (
              <>
                <dt>p50 / p95</dt>
                <dd>
                  {formatMs(tooltip.stats.p50_ms)} / {formatMs(tooltip.stats.p95_ms || 0)}
                </dd>
              </>
            )}
            {tooltip.step.source_location && (
              <>
                <dt>Source</dt>
                <dd>
                  {tooltip.step.source_location.function_name} ({tooltip.step.source_location.file_path}:{tooltip.step.source_location.line_number})
                </dd>
              </>
            )}
          </dl>
        </div>
      )}
    </div>
  );
}
