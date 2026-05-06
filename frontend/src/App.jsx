import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Analyze from "./pages/Analyze";
import RunDetail from "./pages/RunDetail";
import RepoDetail from "./pages/RepoDetail";
import Settings from "./pages/Settings";
import AppLogUpload from "./pages/AppLogUpload";
import AppLogSession from "./pages/AppLogSession";
import AppLogsByApp from "./pages/AppLogsByApp";
import StaticAnalysis from "./pages/StaticAnalysis";

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/analyze" element={<Analyze />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/repos/:owner/:name" element={<RepoDetail />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/app-logs/upload" element={<AppLogUpload />} />
          <Route path="/app-logs/sessions/:id" element={<AppLogSession />} />
          <Route path="/app-logs/apps/:appName" element={<AppLogsByApp />} />
          <Route path="/static-analysis" element={<StaticAnalysis />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
