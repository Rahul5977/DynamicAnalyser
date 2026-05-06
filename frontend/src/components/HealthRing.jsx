import React from "react";

export default function HealthRing({ score = 0, size = 72 }) {
  const clamped = Math.min(100, Math.max(0, Number(score) || 0));
  const r = size / 2 - 6;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - clamped / 100);
  const stroke =
    clamped >= 80 ? "var(--green-500)" : clamped >= 50 ? "var(--amber-500)" : "var(--red-500)";

  return (
    <svg width={size} height={size} className="health-ring-svg">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="var(--gray-100)"
        strokeWidth="6"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={stroke}
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 1s ease, stroke 0.3s ease" }}
      />
      <text
        x="50%"
        y="50%"
        dominantBaseline="middle"
        textAnchor="middle"
        fill="var(--text-primary)"
        fontFamily="var(--font-sans)"
      >
        <tspan fontSize={size * 0.26} fontWeight="700">
          {clamped}
        </tspan>
        <tspan fontSize={size * 0.14} fontWeight="600">
          %
        </tspan>
      </text>
    </svg>
  );
}
