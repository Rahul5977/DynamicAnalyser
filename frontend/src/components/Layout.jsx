import React from "react";
import { Link, useLocation } from "react-router-dom";
import { LayoutDashboard, GitBranch, BarChart3, Settings } from "lucide-react";

const NAV_ITEMS = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard },
  { path: "/analytics", label: "Analytics", icon: BarChart3 },
  { path: "/settings", label: "Settings", icon: Settings },
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
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
