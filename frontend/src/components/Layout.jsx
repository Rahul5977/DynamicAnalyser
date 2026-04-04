import React from "react";
import { Link, useLocation } from "react-router-dom";
import { LayoutDashboard, Play, BarChart3, Settings, FileText, Upload } from "lucide-react";

const NAV_ITEMS = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard },
  { path: "/analyze", label: "Analyze Repo", icon: Play },
  { path: "/analytics", label: "Analytics", icon: BarChart3 },
  { path: "/settings", label: "Settings", icon: Settings },
];

const APP_LOG_NAV = [
  { path: "/app-logs/upload", label: "Upload App Log", icon: Upload },
];

export default function Layout({ children }) {
  const location = useLocation();

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-logo">DynamicAnalyser</div>
        <ul className="sidebar-nav">
          {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
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
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
