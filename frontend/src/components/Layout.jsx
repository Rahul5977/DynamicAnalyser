import React, { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { LayoutDashboard, Play, Settings, Upload } from "lucide-react";
import { getActiveRegressions } from "../services/api";

const NAV_ITEMS = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard },
  { path: "/analyze", label: "Analyze Repo", icon: Play },
  { path: "/settings", label: "Settings", icon: Settings },
];

const APP_LOG_NAV = [
  { path: "/app-logs/upload", label: "Upload App Log", icon: Upload },
];

export default function Layout({ children }) {
  const location = useLocation();
  const [alertCount, setAlertCount] = useState(0);

  useEffect(() => {
    getActiveRegressions().then((d) => setAlertCount((d || []).length)).catch(() => {});
  }, []);

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div
          style={{
            padding: "14px 20px 14px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <div
            style={{
              width: 26,
              height: 26,
              background: "linear-gradient(135deg,#6366f1,#8b5cf6)",
              borderRadius: 8,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 14,
              flexShrink: 0,
            }}
          >
            ⚡
          </div>
          <div
            style={{
              fontSize: 12,
              fontWeight: 700,
              background: "linear-gradient(135deg,#818cf8,#a78bfa)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}
          >
            DynamicAnalyser
          </div>
        </div>
        <ul className="sidebar-nav">
          {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
            <li key={path}>
              <Link
                to={path}
                className={location.pathname === path ? "active" : ""}
              >
                <Icon />
                {label}
                {path === "/" && alertCount > 0 && (
                  <span
                    style={{
                      marginLeft: "auto",
                      background: "rgba(239,68,68,.2)",
                      color: "#ef4444",
                      fontSize: 9,
                      fontWeight: 700,
                      padding: "1px 5px",
                      borderRadius: 999,
                    }}
                  >
                    {alertCount}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
        <div style={{ padding: "16px 0 4px 16px", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-muted)", opacity: 0.7 }}>
          App Logs
        </div>
        <ul className="sidebar-nav">
          {APP_LOG_NAV.map(({ path, label, icon: Icon }) => (
            <li key={path}>
              <Link
                to={path}
                className={location.pathname === path ? "active" : ""}
              >
                <Icon />
                {label}
              </Link>
            </li>
          ))}
        </ul>
        <div style={{ marginTop: "auto", padding: 12, borderTop: "1px solid var(--border)" }}>
          <div
            style={{
              background: alertCount > 0 ? "rgba(239,68,68,.07)" : "rgba(34,197,94,.07)",
              border: `1px solid ${alertCount > 0 ? "rgba(239,68,68,.2)" : "rgba(34,197,94,.2)"}`,
              borderRadius: 6,
              padding: "6px 8px",
            }}
          >
            <div style={{ fontSize: 9, color: alertCount > 0 ? "#ef4444" : "#22c55e", fontWeight: 700 }}>
              FLEET STATUS
            </div>
            <div style={{ fontSize: 10, color: "#64748b", marginTop: 1 }}>
              {alertCount === 0 ? "✓ No active regressions" : `⚠ ${alertCount} regression(s)`}
            </div>
          </div>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
