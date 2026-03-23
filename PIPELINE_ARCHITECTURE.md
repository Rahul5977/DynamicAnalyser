# DynamicAnalyzer: Complete Architecture & Pipeline Guide

## Executive Summary

**DynamicAnalyzer** is an AI-powered CI/CD pipeline diagnostics system that automatically identifies performance bottlenecks in GitHub Actions workflows and recommends code-level fixes. The system ingests CI/CD logs, correlates them with source code, performs statistical analysis, and uses Claude AI to generate actionable recommendations.

---

## Table of Contents

1. [System Overview & Architecture](#system-overview--architecture)
2. [Data Pipeline (4 Layers)](#data-pipeline-4-layers)
3. [Backend Services (Detailed)](#backend-services-detailed)
4. [Frontend Pages & UI Flow](#frontend-pages--ui-flow)
5. [API Endpoints Reference](#api-endpoints-reference)
6. [Complete End-to-End Flow](#complete-end-to-end-flow)
7. [Database Schema](#database-schema)

---

## System Overview & Architecture

### High-Level Data Flow

```
GitHub Repository
    ↓
    └─→ [Source Code Indexing] → AST Parser
    └─→ [CI/CD Execution] → GitHub Actions Logs
            ↓
    [Log Ingestion] → Log Parser
            ↓
    [Step Extraction] → Trace Correlator
            ↓
    [Source Code Mapping] → Call Graph Builder
            ↓
    [Statistical Analysis] → Bottleneck Ranker
            ↓
    [AI Analysis] → Claude LLM
            ↓
    [Fix Recommendations] → Fix Recommender
            ↓
    [Frontend Visualization] → Dashboard UI
```

### 4-Layer Architecture

| Layer | Name          | Purpose                | Components                                   |
| ----- | ------------- | ---------------------- | -------------------------------------------- |
| 1     | **Sources**   | Data ingestion sources | GitHub repo, CI logs, runtime metrics        |
| 2     | **Ingestion** | Parsing & indexing     | Log parser, AST indexer, trace correlator    |
| 3     | **AI Core**   | Intelligence layer     | Bottleneck ranker, LLM engine, recommender   |
| 4     | **Output**    | Delivery layer         | Dashboard UI, report generator, PR commenter |

---

## Data Pipeline (4 Layers)

### Layer 1: Sources

**What happens:** Data enters the system from external sources.

#### 1.1 GitHub Repository Source

- **Input:** Repository owner and name (e.g., `octocat/Hello-World`)
- **Fetch:** Latest commit SHA from default branch (or user-specified SHA)
- **Storage:** Tracked repository record in database
- **API:** `POST /repos/{owner}/{name}/index`

#### 1.2 CI/CD Execution Logs

- **Input:** GitHub Actions workflow run logs (raw text format)
- **Format:** Each log line has ISO 8601 timestamp + GitHub Actions annotations
- **Example log line:** `2024-03-19T10:32:01.4567890Z Run npm install`
- **Storage:** Raw logs temporarily held during parsing

---

### Layer 2: Ingestion

**What happens:** Raw data is parsed, structured, and stored in the database.

#### 2.1 Log Ingestion Pipeline (`LogIngester`)

**File:** `backend/app/services/ingester.py`

**Process:**

1. **Validate Repository:** Check if repo is tracked in database
2. **Fetch Run Metadata:** Get workflow run details from GitHub API
   - Run ID, status, conclusion, branch, commit SHA
3. **Download Logs:** Fetch the raw log archive from GitHub
4. **Parse Logs:** Convert raw logs into structured step data
5. **Store:** Persist steps and timings to database

**Code Location:**

```python
def ingest_run(repo_full_name: str, github_run_id: int) -> IngestionResult:
    # 1. Ensure repository is tracked
    # 2. Check for duplicate ingestion
    # 3. Fetch run metadata from GitHub
    # 4. Download and parse logs
    # 5. Build ORM objects and persist
```

**Output:**

- `PipelineRun` record with status, conclusion, total duration
- `StepTiming` records for each step in the workflow
  - Step name, duration (ms), start/end timestamps
  - Status (success/failure)
  - Log excerpt (first 2000 chars)

#### 2.2 Log Parser (`LogParser`)

**File:** `backend/app/services/log_parser.py`

**Parsing Rules:**

1. **Timestamp Extraction:** Regex matches `YYYY-MM-DDTHH:MM:SS.fZ` format
2. **Annotation Detection:** Identifies GitHub Actions annotations (##[group], ##[error], etc.)
3. **Step Extraction:** Groups log lines by step header `=== job/step_name.txt ===`
4. **Duration Calculation:** `ended_at - started_at` in milliseconds

**Key Data Structures:**

```python
@dataclass
class ParsedLogLine:
    timestamp: datetime
    raw_message: str
    annotation: str | None
    message: str

@dataclass
class ParsedStep:
    step_name: str
    step_number: int
    duration_ms: int
    status: str
    log_excerpt: str  # First 2000 chars for analysis
```

#### 2.3 Source Code Indexing (`CodeIndexer` + `ASTParser`)

**Files:**

- `backend/app/services/ast_parser.py`
- `backend/app/api/routes/analysis.py` → `/repos/{owner}/{name}/index`

**Process:**

1. **Fetch Repository:** Clone or fetch source code at specific commit SHA
2. **Parse Files:** Use tree-sitter library for multi-language AST parsing
   - Supported languages: Python, JavaScript, TypeScript, Go
3. **Extract Functions:** Walk AST to find all function definitions
   - Capture: name, qualified name, file path, line numbers, language
4. **Trace Calls:** Build call graph by finding all function calls
5. **Find Log Calls:** Identify logging statements (logger.info, console.log, etc.)
   - Capture: log string, line number, containing function
6. **Calculate Language Breakdown:** Count functions per language

**Data Structures:**

```python
@dataclass
class FunctionInfo:
    name: str
    qualified_name: str | None
    file_path: str
    line_number: int
    end_line_number: int
    calls: list[str]  # Functions this function calls
    language: str

@dataclass
class LogCallInfo:
    log_string: str
    file_path: str
    line_number: int
    function_name: str | None
    log_level: str | None
    language: str

@dataclass
class CodeIndexData:
    functions: list[FunctionInfo]
    log_calls: list[LogCallInfo]
    call_graph: dict[str, list[str]]  # Caller → [Callees]
    reverse_call_graph: dict[str, list[str]]  # Callee → [Callers]
    language_breakdown: dict[str, int]  # Language → Count
```

**Storage:**

- `CodeIndex` record (status: running → completed)
- `IndexedFunction` records (one per function found)
- `IndexedLogCall` records (one per logging call found)

#### 2.4 Trace Correlation (`TraceCorrelator`)

**File:** `backend/app/services/trace_correlator.py`

**Purpose:** Map each pipeline step back to the exact function in source code that caused the slowness.

**Matching Strategy:**

1. **Log Excerpt Matching (Primary)**
   - Extract log excerpt from step (first 2000 chars)
   - Clean timestamps and annotations
   - Compute fuzzy string similarity against all indexed log calls
   - If match confidence > 70%, use matched function

2. **Grep Fallback (Secondary)**
   - If no log excerpt match, search for step name keywords in source code
   - Look in function names, file names, and comments
   - Lower confidence than log matching

**Output: `AnnotatedTrace`**

```python
@dataclass
class AnnotatedStep:
    step_name: str
    duration_ms: int
    source_location: SourceLocation | None
    call_chain: list[CallChainEntry]  # Callers up the stack
    match_confidence: float | None
    match_method: str | None  # "log_excerpt" or "grep"

@dataclass
class AnnotatedTrace:
    total_runs_analyzed: int
    steps: list[AnnotatedStep]
    matched_count: int
```

**API Endpoint:** `GET /runs/{run_id}/trace`

---

### Layer 3: AI Core (Intelligence)

**What happens:** Statistical analysis identifies patterns, then Claude AI generates explanations and recommendations.

#### 3.1 Bottleneck Ranking (`BottleneckRanker`)

**File:** `backend/app/services/bottleneck_ranker.py`

**Purpose:** Identify which steps are causing the most pipeline slowness using statistical metrics.

**Algorithm:**

1. **Collect Durations:** For each step, gather all durations from last N runs (default: 50)

2. **Compute Statistics:**
   - `mean_ms`: Average step duration
   - `p50_ms`: Median (50th percentile)
   - `p95_ms`: 95th percentile (how slow is a "bad" run?)
   - `std_dev_ms`: Standard deviation
   - `trend_slope`: Linear regression to detect if step is getting slower or faster

3. **Calculate Composite Score:**

   ```
   Score = 0.5 * (pct_of_total)
          + 0.3 * (anomaly_score)
          + 0.2 * (trend_score)
   ```

   Where:
   - **% of Total:** Step's mean duration / total pipeline duration
   - **Anomaly Score:** How often is this step slow?
     - Count runs where step > p95 / total runs
   - **Trend Score:** Is it getting worse?
     - Slope of linear regression line

4. **Rank Steps:** Sort by composite score, return top N (default: 3)

**Output:**

```python
@dataclass
class BottleneckEntry:
    rank: int
    step_name: str
    composite_score: float
    pct_of_total: float  # % of total pipeline time
    anomaly_score: float  # How often is it slow?
    trend_direction: str  # "increasing", "decreasing", "stable"
    mean_ms: float
    p50_ms: int
    p95_ms: int
```

**API Endpoints:**

- `GET /repos/{owner}/{name}/bottlenecks` → Return top 3 bottleneck steps
- `GET /repos/{owner}/{name}/step/{step_name}/stats` → Detailed stats for one step

#### 3.2 AI Analysis Engine (`AIEngine`)

**File:** `backend/app/services/ai_engine.py`

**Purpose:** Use Claude LLM to understand WHY a step is slow and what code change would fix it.

**Process:**

1. **Assembly Context:** Gather all relevant information about the slow step:

   ```python
   AnalysisContext(
       repo_full_name="octocat/Hello-World",
       commit_sha="abc123...",
       total_duration_ms=25000,
       target_duration_ms=15000,  # User goal

       bottlenecks=[
           BottleneckContext(
               step_name="Install dependencies",
               duration_ms=8000,
               p95_ms=7500,
               pct_of_total=0.32,
               trend_direction="increasing",
               source_function="run_npm_install",
               source_file="scripts/install.js",
               source_line=42,
               function_source_code="...",  # Actual function body
               call_chain="main → orchestrate → install"
           ),
           # ... more bottlenecks
       ]
   )
   ```

2. **Build Prompt:** Construct a detailed prompt for Claude that includes:
   - Repository context
   - Known anti-patterns (checklist of 6 common CI/CD issues)
   - Current bottleneck statistics
   - Source code of slow functions
   - Call chain information

3. **Call Claude API:** Send prompt to Claude with structured response format

4. **Parse Response:** Extract:
   - Root cause explanation (string)
   - Primary bottleneck step (string)
   - Detected anti-patterns (list)
   - Suggestions (list of fixes with effort/saving estimates)
   - Total estimated saving (ms)

**Anti-Patterns Checked:**

1. **No dependency caching** - npm/pip install without cache
2. **Sequential test execution** - Tests running single-threaded
3. **Unindexed DB queries** - SELECT on non-indexed columns
4. **Blocking I/O** - sleep(), sync file reads in hot path
5. **Redundant installs** - Same package installed in multiple steps
6. **No build cache** - Full recompile every run

**LLM Response Schema:**

```python
class LLMSuggestion(BaseModel):
    title: str  # e.g., "Add npm cache"
    description: str  # Why and how to fix
    target_function: str  # Which function to modify
    target_file: str  # Which file
    estimated_saving_ms: int  # How much time saved
    effort: str  # "low", "medium", "high"
    diff_hint: str  # Pseudo-code diff before/after

class LLMAnalysisResult(BaseModel):
    root_cause: str
    primary_bottleneck: str
    anti_patterns: list[str]
    suggestions: list[LLMSuggestion]
    estimated_total_saving_ms: int
```

**Storage:** `Analysis` and `AnalysisSuggestion` records in database

#### 3.3 Fix Recommender (`FixRecommender`)

**File:** `backend/app/services/fix_recommender.py`

**Purpose:** Enrich AI suggestions with actual diffs and confidence scores.

**Enrichment Steps:**

1. **Generate Unified Diff:**
   - Parse diff_hint from Claude (before/after code snippets)
   - Generate proper unified diff format (like git diff)
   - Store as `enriched_diff` field

2. **Compute Confidence Score:**
   - Factors:
     - Match quality (how well log excerpt matched source code)
     - Anti-pattern certainty (did we definitely detect this issue?)
     - Saving estimate validity (is saving estimate reasonable?)
   - Score range: 0.0 - 1.0

**Output Stored:**

```python
AnalysisSuggestion(
    rank=1,
    title="Add npm cache to workflow",
    description="...",
    target_file=".github/workflows/ci.yml",
    target_function="install-dependencies",
    estimated_saving_ms=4500,
    effort="low",
    diff_hint="...",
    enriched_diff="--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n...",
    confidence_score=0.92,
    anti_pattern="No dependency caching"
)
```

---

### Layer 4: Output (Delivery)

**What happens:** Results are presented to users through dashboard UI and API responses.

#### 4.1 Dashboard API (`DashboardSummary`)

**Endpoint:** `GET /dashboard/summary`

**Returns:** High-level KPIs

```python
@dataclass
class DashboardSummary:
    total_repos: int  # How many repos tracked
    total_runs: int  # Total workflow runs ingested
    total_analyses: int  # Total AI analyses completed
    avg_duration_ms: float  # Average pipeline duration
    avg_saving_ms: float  # Average saving per analysis
```

#### 4.2 Analytics API

**Endpoints:**

- `GET /repos/{owner}/{name}/analytics` → Trend charts data
- `GET /repos/{owner}/{name}/insights` → High-level insights

**Returns:**

- **Duration Trend:** Pipeline duration over time (detects if getting slower/faster)
- **Step Evolution:** How each step's duration changes over time
- **Anti-Pattern Frequency:** Which anti-patterns are most common

---

## Backend Services (Detailed)

### Service Architecture

```
┌─────────────────────────────────────────────┐
│         FastAPI Application                  │
│  (app/main.py)                              │
└──────────┬──────────────────────────────────┘
           │
      ┌────┴────────────────────────────────┐
      │                                      │
      ↓                                      ↓
┌─────────────────────┐        ┌─────────────────────┐
│   API Routes        │        │   Services          │
├─────────────────────┤        ├─────────────────────┤
│ /repos              │        │ CodeIndexer         │
│ /runs               │        │ LogIngester         │
│ /analyses           │        │ TraceCorrelator     │
│ /dashboard          │        │ BottleneckRanker    │
│ /demo/seed          │        │ AIEngine            │
└─────────────────────┘        │ FixRecommender      │
                               └─────────────────────┘
      │                              │
      └──────────────┬───────────────┘
                     ↓
            ┌─────────────────────┐
            │   Repositories      │
            ├─────────────────────┤
            │ CodeIndexRepository │
            │ PipelineRunRepo     │
            │ TrackedRepoRepo     │
            │ AnalysisRepository  │
            └──────────┬──────────┘
                       ↓
            ┌─────────────────────┐
            │   SQLAlchemy ORM    │
            ├─────────────────────┤
            │ SQLite Database     │
            └─────────────────────┘
```

### API Routes Organization

**File Structure:**

```
app/api/routes/
├── health.py          # Health checks
├── repos.py           # Repository management
├── runs.py            # Pipeline runs
├── analysis.py        # Code indexing, bottleneck ranking
├── ai_analysis.py     # AI analysis, suggestions, feedback
└── dashboard.py       # KPIs, analytics, webhook, demo seed
```

### Core Modules

**`core/logging.py`** - Unified logging across services

**`core/exceptions.py`** - Custom exception hierarchy

- `DynamicAnalyserError` (base)
- `RepositoryNotFoundError`
- `RunNotFoundError`
- `LogParseError`
- `ASTParseError`
- `IndexingError`
- `CorrelationError`
- `AnalysisError`
- `LLMError`

**`config.py`** - Settings from environment

```python
settings = {
    "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN"),
    "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
    "DATABASE_URL": os.getenv("DATABASE_URL", "sqlite:///dynamic_analyser.db"),
    "APP_NAME": "DynamicAnalyzer",
    "APP_VERSION": "1.0.0",
    "TARGET_DURATION_MS": 15000,  # Goal: achieve 15s pipeline
}
```

---

## Frontend Pages & UI Flow

### Page Architecture (React + React Router)

**File Structure:**

```
frontend/src/
├── App.jsx              # Root router
├── main.jsx             # Entry point
├── pages/
│   ├── Dashboard.jsx    # Home page - KPIs + repos list
│   ├── RepoDetail.jsx   # Repo detail - bottleneck cards + runs table
│   ├── RunDetail.jsx    # Run detail - flamegraph + AI analysis
│   ├── Analytics.jsx    # Trends - duration chart, step evolution
│   └── Settings.jsx     # Admin - add repos, webhook config
├── components/
│   ├── Flamegraph.jsx   # Horizontal bar chart for steps
│   ├── SuggestionCard.jsx # Displays one fix suggestion
│   ├── StatusBadge.jsx   # Status indicator
│   ├── KPICard.jsx       # Summary metric card
│   └── Layout.jsx        # Header + nav + footer
└── services/
    └── api.js           # All HTTP calls to backend
```

### Page Flow

#### 1. **Dashboard** (`/`)

**Purpose:** System overview and entry point.

**Components:**

- **Header:** "Load Demo Data" button
- **KPI Cards:**
  - Repos Tracked
  - Total Runs
  - Analyses Done
  - Avg Duration
  - Avg Saving
- **Repository Table:**
  - Rows: full_name, owner, name, active status
  - Click row → Go to `/repos/{owner}/{name}`
- **Recent Activity Feed:**
  - Last 10 runs with status, duration, branch, timestamp

**Logic:**

```jsx
const handleSeed = async () => {
  await seedDemo(); // POST /api/demo/seed
  load(); // Refresh KPIs and repos
};
```

#### 2. **Repository Detail** (`/repos/{owner}/{name}`)

**Purpose:** View all runs for a repo + bottleneck analysis.

**Components:**

- **Top 3 Bottleneck Cards:**
  - Step name, composite score, p95_ms, trend direction
  - Click → Scroll to runs table, filter by step name (if possible)
- **Runs Table:**
  - Columns: run number, status badge, duration, branch, timestamp
  - Sorted: newest first
  - Click row → Go to `/runs/{runId}`

**Data Fetched:**

```javascript
GET /repos/{owner}/{name}/bottlenecks?window=50&top_n=3
GET /repos/{owner}/{name}  // List all runs for repo
```

**Example bottleneck:**

```
┌────────────────────────────────────────┐
│ Install Dependencies                    │
│                                         │
│ Rank: 1                                 │
│ Composite Score: 0.68                   │
│ P95: 7500ms                             │
│ % of Total: 32%                         │
│ Trend: ↑ increasing                     │
│ Anomaly: 24% of runs                    │
└────────────────────────────────────────┘
```

#### 3. **Run Detail** (`/runs/{runId}`)

**Purpose:** Deep dive into a single pipeline run with AI analysis.

**Components:**

**A. Metadata Bar**

- Run number, status badge, total duration
- Branch, workflow name, commit SHA
- Created timestamp

**B. Flamegraph**

- Horizontal stacked bar chart showing all steps
- Each step is a colored bar:
  - 🟢 **Green** = Fast (duration < p50)
  - 🟡 **Amber** = Moderate (p50 ≤ duration < p95)
  - 🔴 **Red** = Slow (duration ≥ p95)
- Hover → Tooltip with exact duration, step name
- Y-axis: Step names
- X-axis: Time (ms)

**Example:**

```
Checkout         ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 500ms 🟢
Install          ████████████████░░░░░░░░░░░░░░░░░░░░ 8000ms 🔴
Build            ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 2500ms 🟡
Test             ██████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 3200ms 🟡
Deploy           ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 1000ms 🟢
                 └───────────────────────────────────┘
                        Total: ~15000ms (target reached!)
```

**C. Run Trace (Source Code Mapping)**

- For each step, show matched source location:
  ```
  Install Dependencies
    ├─ Source: src/scripts/install.js:42 (run_npm_install)
    ├─ Confidence: 85%
    └─ Call Chain:
          main → orchestrate → run_npm_install
  ```

**D. AI Analysis Panel** (for last 3 runs with analyses)

- **Root Cause:** Explanation of why step is slow
- **Primary Bottleneck:** Which step is the main issue
- **Anti-Patterns:** Detected problems (e.g., "No dependency caching")
  ```
  ⚠️ No dependency caching
  ⚠️ Sequential test execution
  ✓ Build cache is configured
  ```
- **Suggestions Cards:** (see below)

**E. Suggestion Cards** (one per fix recommendation)

```
┌─────────────────────────────────────────────────────────┐
│ Add npm cache to GitHub Actions workflow                 │
│                                                          │
│ Description:                                             │
│ npm install runs without caching dependencies. Adding a  │
│ cache action will save 3000-4500ms per run.             │
│                                                          │
│ Target: .github/workflows/ci.yml                         │
│ Estimated Saving: 4500ms                                 │
│ Effort: low      Confidence: 92%                         │
│                                                          │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ Diff Preview:                                        │ │
│ │ - npm ci                                             │ │
│ │ + uses: actions/cache@v3                             │ │
│ │   with:                                              │ │
│ │     path: ~/.npm                                     │ │
│ │     key: ${{ runner.os }}-npm-${{ hashFiles(...) }} │ │
│ └──────────────────────────────────────────────────────┘ │
│                                                          │
│ [Accept] [Reject] [View Full Diff]                      │
└─────────────────────────────────────────────────────────┘
```

**F. Manual Analysis Button**

- "Run Analysis" button for runs without analysis
- Requires `ANTHROPIC_API_KEY` set
- Triggers: `POST /runs/{runId}/analyse`
- Shows spinner while processing

**G. Duration Trend (Optional)**

- Line chart showing this run's duration vs. previous runs
- Reference line at target duration (15s)

**Data Fetched:**

```javascript
GET /runs/{runId}               // Run metadata + steps
GET /runs/{runId}/trace         // Source code mapping
GET /analyses/{analysisId}      // AI analysis (if exists)
GET /analyses?run_id={runId}    // Get latest analysis
POST /runs/{runId}/analyse      // Trigger AI analysis
POST /analyses/{id}/feedback    // Submit verdict on suggestion
```

#### 4. **Analytics** (`/analytics`)

**Purpose:** System-wide trends and insights.

**Components:**

**A. Repository Selector Dropdown**

- Select which repo to analyze

**B. Duration Trend Chart**

- X-axis: Run number (or date)
- Y-axis: Total pipeline duration (ms)
- Reference line: Target duration (15s = 15000ms)
- Trend shows if pipeline is speeding up or slowing down

**Example:**

```
Duration Trend
  |
  |        ╱╲              Target: 15000ms (dashed line)
25|   ╱╲  ╱  ╲      ╱╲
  |  ╱  ╲╱    ╲    ╱  ╲
20|         ╱  ╲  ╱    ╲
  |        ╱    ╲╱
15|───────────────────────
  |
  └─────────────────────→
    Run 1  5  10 15 20 25
```

**C. Step Evolution (Stacked Area Chart)**

- X-axis: Run number
- Y-axis: Duration (ms), stacked by step
- Shows how each step changes over time
- Helps spot which step is getting slower

**D. Anti-Pattern Frequency Bar Chart**

- X-axis: Anti-pattern name
- Y-axis: Frequency (% of analyses where detected)
- Example:
  ```
  No dependency caching:    ████████ 40%
  Sequential tests:         ██████ 30%
  Unindexed DB queries:     ████ 20%
  No build cache:           ██████ 30%
  ```

**E. Insights KPI Cards**

- Most common bottleneck step
- Average estimated saving per analysis
- Most impactful anti-pattern

**Data Fetched:**

```javascript
GET /repos/{owner}/{name}/analytics
  -> { duration_trend, step_evolution, anti_patterns, insights }
```

#### 5. **Settings** (`/settings`)

**Purpose:** Repository configuration and webhook setup.

**Components:**

**A. Add Repository Form**

- Input: Full repository name (owner/repo)
- Button: "Add Repository"
- Requires: GitHub API token

**B. Tracked Repositories Table**

- Columns: full_name, owner, name, default_branch, active?, created_at
- Actions: Edit, Delete, View

**C. Webhook Configuration Guide**

- Shows URL: `https://api.dynamicanalyzer.com/webhook`
- Shows payload format: GitHub push + workflow_run events
- Copy button for easy configuration

**Data Fetched:**

```javascript
POST / repos; // Add new repo
GET / repos; // List tracked repos
DELETE / repos / { id }; // Remove repo
GET / webhook / config; // Webhook setup guide
```

---

## API Endpoints Reference

### Health & Demo

| Method | Endpoint         | Purpose                |
| ------ | ---------------- | ---------------------- |
| GET    | `/health`        | Health check + version |
| POST   | `/api/demo/seed` | Load demo data         |

### Repository Management

| Method | Endpoint                | Purpose                    |
| ------ | ----------------------- | -------------------------- |
| POST   | `/repos`                | Add new tracked repository |
| GET    | `/repos`                | List all tracked repos     |
| GET    | `/repos/{owner}/{name}` | Get repo details           |

### Code Indexing (Phase 2)

| Method | Endpoint                                       | Purpose                         |
| ------ | ---------------------------------------------- | ------------------------------- |
| POST   | `/repos/{owner}/{name}/index`                  | Trigger AST indexing for commit |
| GET    | `/repos/{owner}/{name}/bottlenecks`            | Get top 3 bottleneck steps      |
| GET    | `/repos/{owner}/{name}/step/{step_name}/stats` | Get stats for one step          |

### Pipeline Runs

| Method | Endpoint                | Purpose                        |
| ------ | ----------------------- | ------------------------------ |
| GET    | `/runs/{run_id}`        | Get run metadata + steps       |
| POST   | `/runs/{run_id}/ingest` | Fetch + parse logs from GitHub |
| GET    | `/runs/{run_id}/trace`  | Get source code mapping        |

### AI Analysis (Phase 3)

| Method | Endpoint                           | Purpose                       |
| ------ | ---------------------------------- | ----------------------------- |
| POST   | `/runs/{run_id}/analyse`           | Trigger AI analysis           |
| GET    | `/analyses/{analysis_id}`          | Get analysis + suggestions    |
| POST   | `/analyses/{analysis_id}/feedback` | Submit feedback on suggestion |
| GET    | `/repos/{owner}/{name}/insights`   | Get repo-level insights       |

### Dashboard & Analytics (Phase 4)

| Method | Endpoint                          | Purpose                 |
| ------ | --------------------------------- | ----------------------- |
| GET    | `/dashboard/summary`              | KPI aggregates          |
| GET    | `/repos/{owner}/{name}/analytics` | Trend charts + insights |
| POST   | `/webhook/github`                 | GitHub webhook receiver |

---

## Complete End-to-End Flow

### Scenario: Analyzing a Slow Pipeline Run

**Timeline:**

#### **Day 1: Setup**

1. **User adds repository:**

   ```
   POST /repos
   { "full_name": "my-org/my-api" }
   → Creates TrackedRepository record
   ```

2. **Index source code:**
   ```
   POST /repos/my-org/my-api/index
   → CodeIndexer fetches repo at HEAD
   → ASTParser walks AST
   → Extracts 45 functions, 12 log calls
   → Stores CodeIndex + IndexedFunction + IndexedLogCall
   → Response: CodeIndexResponse { id, commit_sha, total_functions: 45, ... }
   ```

#### **Day 2: CI Run (Pipeline Execution)**

3. **GitHub Actions runs workflow:**

   ```
   Workflow starts (on push)
   ├─ Checkout (300ms)
   ├─ Install dependencies (8000ms) ← SLOW!
   ├─ Run migrations (2500ms)
   ├─ Run tests (4200ms)
   ├─ Build (2000ms)
   └─ Deploy (1500ms)
   Total: 18500ms
   ```

4. **User manually triggers ingestion (or webhook auto-triggers):**

   ```
   POST /runs/{github_run_id}/ingest?repo=my-org/my-api

   LogIngester:
   ├─ Fetches run metadata from GitHub API
   ├─ Downloads logs from GitHub
   ├─ Calls parse_logs() to extract steps
   ├─ Creates PipelineRun + 6 StepTiming records
   └─ Response: IngestionResult { run_id: 42, steps_parsed: 6, ... }
   ```

#### **Day 3: Analysis**

5. **Get trace (source code mapping):**

   ```
   GET /runs/42/trace

   TraceCorrelator:
   ├─ Loads CodeIndexData for commit
   ├─ For each step:
   │  ├─ Match log excerpt against indexed log calls
   │  ├─ If no match, grep fallback by step name
   │  └─ Build call chain (who called this function?)
   ├─ Returns AnnotatedTrace with source locations
   │
   Example output:
   {
     steps: [
       {
         step_name: "Install dependencies",
         duration_ms: 8000,
         source_location: {
           file_path: "scripts/install.js",
           line_number: 42,
           function_name: "run_npm_install"
         },
         call_chain: ["main", "orchestrate", "run_npm_install"],
         match_confidence: 0.85,
         match_method: "log_excerpt"
       },
       ...
     ]
   }
   ```

6. **Get bottleneck ranking:**

   ```
   GET /repos/my-org/my-api/bottlenecks?window=50&top_n=3

   BottleneckRanker:
   ├─ Query: last 50 runs for repo
   ├─ For "Install dependencies" step:
   │  ├─ Collect durations: [8000, 7500, 8200, 7800, 9000, ...]
   │  ├─ Compute: mean=8100, p50=8000, p95=8800, std_dev=450
   │  ├─ Compute trend: slope=+150 (getting slower!)
   │  ├─ Compute anomaly: 24% of runs > p95
   │  └─ Composite score: 0.68
   │
   └─ Return top 3 steps sorted by score

   Response:
   {
     bottlenecks: [
       {
         rank: 1,
         step_name: "Install dependencies",
         composite_score: 0.68,
         pct_of_total: 0.44,
         anomaly_score: 0.24,
         trend_direction: "increasing",
         mean_ms: 8100,
         p50_ms: 8000,
         p95_ms: 8800
       },
       ...
     ]
   }
   ```

7. **Trigger AI analysis:**

   ```
   POST /runs/42/analyse?force=true

   AIEngine:
   ├─ Assemble AnalysisContext:
   │  ├─ Fetch run, repo, bottlenecks, trace
   │  ├─ Load source code of slow functions
   │  ├─ Build call chains
   │  └─ Calculate target_duration_ms (15000)
   │
   ├─ Call Claude API with prompt:
   │  "The 'Install dependencies' step takes 8100ms on average
   │   (44% of total pipeline). It's getting slower (trend +150ms).
   │   The source code is in scripts/install.js:42.
   │   Here's the function body: ...
   │   What's the root cause and how to fix it?"
   │
   ├─ Claude responds with:
   │  {
   │    root_cause: "npm install without cache is fetching all dependencies",
   │    primary_bottleneck: "Install dependencies",
   │    anti_patterns: ["No dependency caching"],
   │    suggestions: [
   │      {
   │        title: "Add npm cache to workflow",
   │        description: "...",
   │        target_file: ".github/workflows/ci.yml",
   │        estimated_saving_ms: 4500,
   │        effort: "low",
   │        diff_hint: "Before: npm ci\nAfter: use cache + npm ci"
   │      }
   │    ],
   │    estimated_total_saving_ms: 4500
   │  }
   │
   ├─ FixRecommender enriches:
   │  ├─ Converts diff_hint to unified diff
   │  ├─ Computes confidence score: 0.92
   │  └─ Stores enriched_diff
   │
   └─ Response: AnalysisResponse
   ```

#### **Day 4: User Reviews**

8. **User views run detail:**

   ```
   GET /runs/42
   → Shows flamegraph with red bars for slow steps
   → Shows AI analysis panel with:
      - Root cause explanation
      - Anti-pattern badges
      - Suggestion cards with diff preview
   ```

9. **User accepts suggestion:**
   ```
   POST /analyses/{analysis_id}/feedback
   {
     "suggestion_id": 1,
     "verdict": "accepted"
   }
   → Stores user feedback for future model tuning
   ```

#### **Day 5: Fix Applied**

10. **User applies fix to .github/workflows/ci.yml:**

    ```diff
    - name: Install dependencies
      run: npm ci

    + - uses: actions/cache@v3
    +   with:
    +     path: ~/.npm
    +     key: ${{ runner.os }}-npm-${{ hashFiles(...) }}
    +
    + - name: Install dependencies
    +   run: npm ci
    ```

11. **Next pipeline run is faster:**

    ```
    New pipeline:
    ├─ Checkout (300ms)
    ├─ Install dependencies (3500ms) ← FIXED!
    ├─ Run migrations (2500ms)
    ├─ Run tests (4200ms)
    ├─ Build (2000ms)
    └─ Deploy (1500ms)
    Total: 14000ms ✓ (Goal achieved: < 15000ms)
    ```

12. **Dashboard updates:**

    ```
    GET /dashboard/summary
    → avg_duration_ms decreases
    → total_analyses increments
    → avg_saving_ms increases

    GET /repos/my-org/my-api/analytics
    → Duration trend chart shows downward slope
    → Anti-pattern frequency for "No dependency caching" decreases
    ```

---

## Database Schema

### Entity-Relationship Diagram

```
┌─────────────────────────────────┐
│    TrackedRepository            │
├─────────────────────────────────┤
│ id (PK)                         │
│ full_name (unique)              │
│ owner                           │
│ name                            │
│ default_branch                  │
│ is_active                       │
│ created_at                      │
│ updated_at                      │
└────────────────┬────────────────┘
                 │ 1:N
                 ↓
┌─────────────────────────────────┐
│      PipelineRun                │
├─────────────────────────────────┤
│ id (PK)                         │
│ repository_id (FK)              │
│ github_run_id                   │
│ run_number                      │
│ workflow_name                   │
│ status                          │
│ conclusion                      │
│ head_branch                     │
│ head_sha                        │
│ total_duration_ms               │
│ created_at                      │
│ ingested_at                     │
└────────────────┬────────────────┘
                 │ 1:N
                 ↓
    ┌────────────────────────────┐
    │      StepTiming            │
    ├────────────────────────────┤
    │ id (PK)                    │
    │ pipeline_run_id (FK)       │
    │ step_name                  │
    │ step_number                │
    │ duration_ms                │
    │ started_at                 │
    │ ended_at                   │
    │ status                     │
    │ annotation                 │
    │ log_excerpt                │
    │ source_function            │
    └────────────────────────────┘

┌─────────────────────────────────┐
│       CodeIndex                 │
├─────────────────────────────────┤
│ id (PK)                         │
│ repository_id (FK)              │
│ commit_sha                      │
│ status (running/completed)      │
│ total_functions                 │
│ total_log_calls                 │
│ language_breakdown_json         │
│ created_at                      │
│ completed_at                    │
│ error_message                   │
└────────────────┬────────────────┘
                 │ 1:N
         ┌───────┴────────┐
         ↓                ↓
    ┌──────────────┐  ┌──────────────┐
    │IndexedFn     │  │IndexedLogCall│
    ├──────────────┤  ├──────────────┤
    │ id (PK)      │  │ id (PK)      │
    │code_idx(FK)  │  │code_idx(FK)  │
    │function_name │  │log_string    │
    │qual_name     │  │file_path     │
    │file_path     │  │line_number   │
    │line_number   │  │func_name     │
    │end_line      │  │log_level     │
    │language      │  │language      │
    │calls_json    │  └──────────────┘
    └──────────────┘

┌─────────────────────────────────┐
│       Analysis                  │
├─────────────────────────────────┤
│ id (PK)                         │
│ pipeline_run_id (FK)            │
│ repository_id (FK)              │
│ status (running/completed)      │
│ root_cause                      │
│ primary_bottleneck              │
│ anti_patterns_json              │
│ estimated_total_saving_ms       │
│ llm_model                       │
│ created_at                      │
│ completed_at                    │
└────────────────┬────────────────┘
                 │ 1:N
                 ↓
    ┌────────────────────────────┐
    │  AnalysisSuggestion        │
    ├────────────────────────────┤
    │ id (PK)                    │
    │ analysis_id (FK)           │
    │ rank                       │
    │ title                      │
    │ description                │
    │ target_function            │
    │ target_file                │
    │ estimated_saving_ms        │
    │ effort (low/medium/high)   │
    │ diff_hint                  │
    │ enriched_diff              │
    │ confidence_score           │
    │ anti_pattern               │
    └────────────────────────────┘
```

### Table Definitions

**TrackedRepository**

- Stores repos being monitored
- Unique on `full_name`

**PipelineRun**

- One record per GitHub Actions workflow run
- Links to TrackedRepository
- Stores run metadata from GitHub API

**StepTiming**

- One record per step in a pipeline run
- Extracted from parsed logs
- `log_excerpt`: First 2000 chars of step logs (used for trace correlation)
- `source_function`: Set by TraceCorrelator

**CodeIndex**

- One record per repo + commit SHA combination
- Status: running → completed (or failed)
- Stores aggregated language breakdown

**IndexedFunction**

- One record per function found in AST parsing
- Stores function metadata (location, signature)
- `calls_json`: JSON array of function names this function calls

**IndexedLogCall**

- One record per logging statement found in source
- Used for fuzzy matching against log excerpts

**Analysis**

- One record per AI analysis run
- Status: running → completed
- Stores Claude's response (root cause, anti-patterns, total saving)

**AnalysisSuggestion**

- One record per suggestion within an analysis
- Ranked (1, 2, 3, ...)
- Stores enriched diffs and confidence scores

**AnalysisFeedback**

- Stores user feedback on suggestions
- Used for model tuning and quality measurement

---

## Key Design Patterns

### 1. Repository Pattern

All database access goes through repository classes:

- `TrackedRepoRepository`
- `PipelineRunRepository`
- `CodeIndexRepository`
- `AnalysisRepository`

This isolates database logic from business logic.

### 2. Service Layer

Business logic is in service classes:

- `LogIngester`: Orchestrates log parsing
- `CodeIndexer`: Builds source code index
- `TraceCorrelator`: Maps steps to source code
- `BottleneckRanker`: Ranks problematic steps
- `AIEngine`: Generates AI analysis
- `FixRecommender`: Enriches suggestions

### 3. Error Handling

Custom exception hierarchy allows fine-grained error handling:

```python
try:
    analysis = engine.analyse_run(run_id)
except AnalysisError as e:
    raise to_http_exception(e)  # → 500 with error details
except RunNotFoundError as e:
    raise to_http_exception(e)  # → 404
```

### 4. Async Context Manager (Lifespan)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables, initialize connections
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown: Clean up connections
```

### 5. Dependency Injection (FastAPI)

```python
@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    # FastAPI automatically injects db session
    run = PipelineRunRepository(db).get_by_id(run_id)
    return run
```

---

## Performance Considerations

### Indexing Strategy

**Database Indexes:**

- `tracked_repositories.full_name` (unique) - Fast repo lookup
- `pipeline_runs(repository_id, github_run_id)` (unique) - Prevent duplicates
- `step_timings(pipeline_run_id, step_name)` - Fast step filtering
- `step_timings(step_name, duration_ms)` - Fast bottleneck ranking

### Caching Checks

**Code Index Caching:**

```python
# Before indexing, check if already done
existing = idx_store.get_by_repo_and_sha(repo_id, commit_sha)
if existing and existing.status == "completed":
    return existing  # Skip re-indexing
```

### Pagination (Future)

Currently loads all runs in memory. For large repos, should paginate:

```python
# TODO: Add pagination
@router.get("/runs?page=1&limit=20")
def list_runs(page: int, limit: int):
    offset = (page - 1) * limit
    runs = db.query(PipelineRun).offset(offset).limit(limit).all()
```

---

## Future Enhancements

1. **Real-time Webhook Integration**
   - Automatically ingest runs when GitHub webhook fires
   - Auto-trigger analysis for new runs

2. **PR Comments**
   - Post analysis + suggestions as GitHub PR comment
   - Link back to DynamicAnalyzer dashboard

3. **Historical Comparisons**
   - "This PR increased Install step by 500ms"
   - Compare run metrics before/after code changes

4. **Custom Thresholds**
   - Let users set custom target durations per step
   - Alert when step exceeds threshold

5. **Integration with Cost Analysis**
   - GitHub Actions bill minutes of compute
   - Show cost savings alongside time savings

6. **Multi-Language Support**
   - Extend tree-sitter to support more languages
   - Add language-specific anti-patterns

7. **Advanced Trace Correlation**
   - Use LLM to understand semantic meaning of logs
   - Better fallback matching when no lexical match

8. **Feedback Loop**
   - Collect user feedback on suggestions
   - Retrain analysis model with feedback data

---

## Conclusion

**DynamicAnalyzer** is a comprehensive system that:

1. **Ingests** CI/CD logs and source code
2. **Correlates** pipeline steps with source functions
3. **Analyzes** performance bottlenecks statistically
4. **Generates** AI-powered fix recommendations
5. **Presents** findings through an intuitive dashboard

The 4-layer architecture separates concerns cleanly:

- **Layer 1 (Sources):** Data collection
- **Layer 2 (Ingestion):** Parsing & structuring
- **Layer 3 (AI Core):** Analysis & intelligence
- **Layer 4 (Output):** UI & API delivery

By combining statistical analysis with large language models, DynamicAnalyzer helps development teams quickly identify and fix CI/CD performance issues, reducing pipeline time and improving productivity.
