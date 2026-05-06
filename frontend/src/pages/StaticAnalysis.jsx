import React from "react";
import { Link } from "react-router-dom";
import { Shield } from "lucide-react";

/**
 * Placeholder: static-analysis backend was removed for a deeper rebuild.
 * Navigation and route stay so the next iteration can wire new APIs here.
 */
export default function StaticAnalysis() {
  return (
    <div className="fade-in">
      <div className="page-header">
        <h1>Static Code Analysis</h1>
        <p>
          The previous static analysis API has been removed. A new pipeline will be added in upcoming
          steps.
        </p>
      </div>
      <div className="card centered-hero-input">
        <div className="flex items-center gap-3" style={{ marginBottom: 16 }}>
          <div className="feature-tile-icon indigo">
            <Shield size={22} />
          </div>
          <div>
            <div className="card-title" style={{ margin: 0 }}>
              SAST — coming next
            </div>
            <div className="card-subtitle">Multi-agent analysis will connect here once the new backend is ready.</div>
          </div>
        </div>
        <Link to="/" className="btn btn-secondary">
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
