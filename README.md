# DynamicAnalyser
1.1 Problem Statement
Modern software teams deploy code through CI/CD pipelines — automated sequences of steps like installing dependencies, running tests, building artefacts, and deploying to servers. These pipelines often have unexplained slowdowns: a pipeline that ran in 18 seconds last week now takes 25 seconds. Developers waste hours reading raw log files trying to find the cause.
DynamicAnalyser solves this by automatically ingesting GitHub repository source code and CI/CD execution logs, correlating them, and using a large language model (LLM) to diagnose why a particular pipeline step is slow and what code change would fix it.

Primary Objective : Reduce CI/CD pipeline execution time from 20 seconds to 15 seconds (25% improvement) by identifying the root cause of slowness through AI-powered dynamic log analysis and code correlation.

1.3 Key Innovations
Dynamic analysis — analyses logs produced at runtime, not just static source code
Trace correlation — maps each slow log event back to the exact function in the source code
AI root cause engine — uses an LLM with structured context to explain WHY a step is slow
Fix recommendations — outputs ranked, actionable suggestions with estimated time savings
GitHub integration — automatically posts analysis as a PR comment on every slow run


Layer	Name	Purpose	Key Components
Layer	Name	Purpose	Key Components
1 — Sources	Data ingestion sources	Raw inputs to the system	GitHub repo, CI logs, runtime metrics
2 — Ingestion	Parsing & indexing	Normalise and structure raw data	Log parser, AST indexer, trace correlator
3 — AI Core	Intelligence layer	Find problems and suggest fixes	Bottleneck ranker, LLM engine, recommender
4 — Output	Delivery layer	Present findings to the developer	Dashboard UI, report generator, PR commenter

Startup Commands
Open two terminals:

Terminal 1 — Backend (port 8000):


cd ~/Desktop/DynamicAnalyzer/backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
Terminal 2 — Frontend (port 5173):


cd ~/Desktop/DynamicAnalyzer/frontend
npm run dev
Then open http://localhost:5173 in your browser.

Usage Guide
1. Load Demo Data (start here)
The app starts with an empty database. Click the "Load Demo Data" button on the Dashboard, or call the API directly:


curl -X POST http://localhost:8000/api/demo/seed
This creates:

1 repository (demo-org/sample-api)
20 pipeline runs with 6 steps each (Checkout, Install, Migrations, Test, Build, Deploy)
3 pre-computed AI analyses with root causes and fix suggestions
A code index with 8 functions and 5 log calls
2. Dashboard (/)
What to expect:

5 KPI cards: total repos (1), total runs (20), total analyses (3), avg duration, avg estimated saving
Repository table: click demo-org/sample-api to go to the repo detail page
Recent activity: last 10 runs with status badges (success/failure), durations, branches
3. Repository Detail (/repos/demo-org/sample-api)
What to expect:

Top 3 bottleneck cards showing the slowest steps with composite scores, p95 values, and trend direction
Runs table: all 20 runs listed with run number, status, duration, branch, timestamp
Click any run to go to the Run Detail page
4. Run Detail (/runs/{runId})
What to expect:

Metadata bar: status badge, total duration, branch, workflow name
Flamegraph: horizontal bars for each step, color-coded:
Green = fast (below p50)
Amber = moderate (p50–p95)
Red = slow (above p95)
Hover for tooltips with exact durations
AI Analysis panel (for the last 3 runs that have analyses):
Root cause explanation
Anti-pattern badges (e.g., "No dependency caching", "Unindexed DB queries")
Suggestion cards with:
Title, description, target file/function
Estimated saving (ms), effort level, confidence %
Expandable diff hint
Accept/Reject feedback buttons
For runs without an analysis, you'll see a "Run Analysis" button (requires ANTHROPIC_API_KEY in .env to actually call Claude).

5. Analytics (/analytics)
What to expect:

Repo selector dropdown (pick demo-org/sample-api)
Duration trend line chart: 20 data points showing total pipeline duration over time, with a 15s target reference line
Step evolution stacked area chart: how each step's duration changes over time
Anti-pattern frequency bar chart: how often each anti-pattern was detected
Insights KPI cards: most common bottleneck, avg estimated saving
6. Settings (/settings)
Add repository form: enter a GitHub owner/repo to track (requires GITHUB_TOKEN)
Tracked repos table: lists currently tracked repositories
Webhook config guide: shows the payload URL for GitHub webhook setup
Testing Checklist
Test	How	Expected
Empty state	Open dashboard before seeding	All zeros, empty tables, "Load Demo Data" button visible
Seed demo	Click "Load Demo Data"	KPIs populate, repo table shows 1 repo, activity feed shows runs
Idempotent seed	Click "Load Demo Data" again	No errors, same data, counts unchanged
Repo detail	Click repo name in table	Bottleneck cards + 20 runs listed
Run detail	Click any of the last 3 runs	Flamegraph + AI analysis with suggestions
Run without analysis	Click an early run (e.g., run #1)	Flamegraph shows, "Run Analysis" button (no pre-computed analysis)
Analytics	Go to /analytics, select repo	3 charts render with 20 data points
Feedback	On a suggestion card, click Accept/Reject	Button state changes (requires analysis present)
Backend API docs	Open http://localhost:8000/docs	Swagger UI with all endpoints
Tests	cd backend && pytest tests/ -v	174/174 pass
API Endpoints (for manual testing with curl)

# Health check
curl http://localhost:8000/api/health

# Dashboard summary
curl http://localhost:8000/api/dashboard/summary

# Repo analytics
curl http://localhost:8000/api/repos/demo-org/sample-api/analytics

# Bottleneck ranking
curl http://localhost:8000/api/repos/demo-org/sample-api/bottlenecks

# Single run detail
curl http://localhost:8000/api/runs/1

# Step statistics
curl "http://localhost:8000/api/repos/demo-org/sample-api/step/Install%20dependencies/stats"

# Latest analysis for a run
curl http://localhost:8000/api/runs/20/analysis/latest
Optional: Enable AI Analysis on Demand
To actually trigger live Claude-powered analysis (not just the pre-seeded ones), create a .env file:


echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" > ~/Desktop/DynamicAnalyzer/backend/.env
Then on any run detail page, click "Run Analysis" — it will call Claude to generate a real root-cause analysis with fix suggestions.

Backend dependencies installed successfully. You're all set — just run the two terminal commands above and open http://localhost:5173.

Both dependency installs finished. Go ahead and start the servers:

Terminal 1:


cd ~/Desktop/DynamicAnalyzer/backend && source venv/bin/activate && uvicorn app.main:app --reload --port 8000
Terminal 2:


cd ~/Desktop/DynamicAnalyzer/frontend && npm run dev
Then open http://localhost:5173 and click "Load Demo Data" to populate everything.