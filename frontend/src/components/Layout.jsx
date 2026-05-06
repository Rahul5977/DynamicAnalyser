import React, { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  GitBranch,
  LayoutDashboard,
  Settings,
  Shield,
  Upload,
  Zap,
} from "lucide-react";
import { getActiveRegressions } from "../services/api";

function navLinkClass(isActive) {
  return isActive ? "active" : "";
}

export default function Layout({ children }) {
  const location = useLocation();
  const [alertCount, setAlertCount] = useState(0);
  const [apiOk, setApiOk] = useState(null);

  useEffect(() => {
    getActiveRegressions()
      .then((d) => setAlertCount((d || []).length))
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch("/api/health");
        if (!cancelled) setApiOk(res.ok);
      } catch {
        if (!cancelled) setApiOk(false);
      }
    };
    check();
    const t = setInterval(check, 30000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const paths = useMemo(
    () => ({
      dashboard:
        location.pathname === "/" || location.pathname.startsWith("/repos/"),
      analyze:
        location.pathname === "/analyze" || location.pathname.startsWith("/runs/"),
      staticAnalysis: location.pathname === "/static-analysis",
      uploadLog: location.pathname.startsWith("/app-logs"),
      settings: location.pathname === "/settings",
    }),
    [location.pathname]
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-mark">
            <Zap size={18} strokeWidth={2.25} />
          </div>
          <div>
            <div className="sidebar-logo-text">CodeAnalyser</div>
            <div className="sidebar-logo-sub">AI Platform</div>
          </div>
        </div>

        <div className="sidebar-section-label">Analysis</div>
        <ul className="sidebar-nav">
          <li className="sidebar-nav-item">
            <Link to="/" className={navLinkClass(paths.dashboard)}>
              <LayoutDashboard size={16} strokeWidth={1.75} />
              Dashboard
              {alertCount > 0 && <span className="sidebar-badge">{alertCount}</span>}
            </Link>
          </li>
          <li className="sidebar-nav-item">
            <Link to="/analyze" className={navLinkClass(paths.analyze)}>
              <GitBranch size={16} strokeWidth={1.75} />
              Analyze Repo
            </Link>
          </li>
          <li className="sidebar-nav-item">
            <Link to="/static-analysis" className={navLinkClass(paths.staticAnalysis)}>
              <Shield size={16} strokeWidth={1.75} />
              Static Analysis
            </Link>
          </li>
        </ul>

        <div className="sidebar-section-label">App logs</div>
        <ul className="sidebar-nav">
          <li className="sidebar-nav-item">
            <Link to="/app-logs/upload" className={navLinkClass(paths.uploadLog)}>
              <Upload size={16} strokeWidth={1.75} />
              Upload Log
            </Link>
          </li>
        </ul>

        <div className="sidebar-section-label">System</div>
        <ul className="sidebar-nav">
          <li className="sidebar-nav-item">
            <Link to="/settings" className={navLinkClass(paths.settings)}>
              <Settings size={16} strokeWidth={1.75} />
              Settings
            </Link>
          </li>
        </ul>

        <div className="sidebar-footer">
          <div className="api-status-pill">
            <span className={`api-status-dot ${apiOk ? "ok" : "bad"}`} />
            {apiOk === null
              ? "Checking API…"
              : apiOk
                ? "API Connected"
                : "API Offline"}
          </div>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
