# DynamicAnalyser — Comprehensive Technical README

> **An AI-powered dynamic analysis platform that ingests CI/CD pipeline logs and application runtime logs, correlates them back to source code via AST indexing, and produces ranked, actionable bottleneck fixes using a large language model.**

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Repository Layout](#4-repository-layout)
5. [Data Model (Database Schema)](#5-data-model-database-schema)
6. [CI/CD Log Analysis Pipeline — Deep Dive](#6-cicd-log-analysis-pipeline--deep-dive)
   - 6.1 [GitHub Integration & Log Ingestion](#61-github-integration--log-ingestion)
   - 6.2 [Log Parser (`log_parser.py`)](#62-log-parser-log_parserpy)
   - 6.3 [Bottleneck Ranker (`bottleneck_ranker.py`)](#63-bottleneck-ranker-bottleneck_rankerpy)
   - 6.4 [AST Indexer (`ast_parser.py`)](#64-ast-indexer-ast_parserpy)
   - 6.5 [Trace Correlator (`trace_correlator.py`)](#65-trace-correlator-trace_correlatorpy)
   - 6.6 [AI Engine (`ai_engine.py`)](#66-ai-engine-ai_enginepy)
   - 6.7 [Fix Recommender (`fix_recommender.py`)](#67-fix-recommender-fix_recommenderpy)
7. [Application Log Analysis Pipeline — Deep Dive](#7-application-log-analysis-pipeline--deep-dive)
   - 7.1 [Log Format Detection](#71-log-format-detection)
   - 7.2 [App Log Parser (`app_log_parser.py`)](#72-app-log-parser-app_log_parserpy)
   - 7.3 [AI Schema Inferrer (`log_schema_inferrer.py`)](#73-ai-schema-inferrer-log_schema_inferrerpy)
   - 7.4 [App Trace Correlator (`app_trace_correlator.py`)](#74-app-trace-correlator-app_trace_correlatorpy)
   - 7.5 [App AI Engine (`app_ai_engine.py`)](#75-app-ai-engine-app_ai_enginepy)
8. [How CI/CD and App Logs Are Correlated with the Codebase](#8-how-cicd-and-app-logs-are-correlated-with-the-codebase)
9. [Composite Bottleneck Scoring Algorithm](#9-composite-bottleneck-scoring-algorithm)
10. [API Routes Reference](#10-api-routes-reference)
11. [Frontend — Analyze Pipeline (React)](#11-frontend--analyze-pipeline-react)
12. [Testing Strategy](#12-testing-strategy)
13. [Configuration & Environment Variables](#13-configuration--environment-variables)
14. [End-to-End Data Flow Walkthrough](#14-end-to-end-data-flow-walkthrough)

---

## 1. What This System Does

DynamicAnalyser solves one concrete problem: **developers waste hours waiting for slow CI/CD pipelines and debugging slow runtime code without knowing where to look.** This tool automates the entire investigation cycle:

```
GitHub Actions Logs          Application Runtime Logs
        │                              │
        ▼                              ▼
  Ingest & Parse               Upload & Parse
        │                              │
        ▼                              ▼
  Step Timing DB            Function Call Timing DB
        │                              │
        └──────────┬───────────────────┘
                   ▼
         Bottleneck Ranking
         (statistical scoring)
                   │
                   ▼
       Source Code AST Indexing
       (tree-sitter, multi-lang)
                   │
                   ▼
        Log ↔ Code Correlation
        (exact + fuzzy + grep)
                   │
                   ▼
         Claude LLM Analysis
     (context: timing + code + history)
                   │
                   ▼
   Ranked Suggestions + Diffs + Confidence
```

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                         │
│  Dashboard | Analyze | CI/CD Runs | App Log Upload | Settings   │
└───────────────────────────┬─────────────────────────────────────┘
                            │ REST /api/…
┌───────────────────────────▼─────────────────────────────────────┐
│                    BACKEND (FastAPI / Python)                    │
│                                                                 │
│  ┌─────────────┐  ┌───────────────┐  ┌────────────────────┐    │
│  │ CI/CD Routes│  │ App Log Routes│  │ Analysis Routes    │    │
│  └──────┬──────┘  └──────┬────────┘  └────────┬───────────┘    │
│         │                │                     │                │
│  ┌──────▼──────────────────────────────────────▼───────────┐   │
│  │                    Service Layer                         │   │
│  │  LogIngester · LogParser · BottleneckRanker             │   │
│  │  ASTParser · CodeIndexer · TraceCorrelator              │   │
│  │  AIEngine · FixRecommender                              │   │
│  │  AppIngester · AppLogParser · AppTraceCorrelator        │   │
│  │  AppAIEngine · LogSchemaInferrer                        │   │
│  └──────────────────────┬──────────────────────────────────┘   │
│                         │                                        │
│  ┌──────────────────────▼──────────────────────────────────┐   │
│  │                  SQLAlchemy ORM                          │   │
│  │  TrackedRepository · PipelineRun · StepTiming           │   │
│  │  CodeIndex · IndexedFunction · IndexedLogCall           │   │
│  │  Analysis · AnalysisSuggestion · AnalysisFeedback       │   │
│  │  AppLogSession · AppFunctionCall · LogFormatSchema      │   │
│  └──────────────────────┬──────────────────────────────────┘   │
│                         │                                        │
│               ┌─────────▼─────────┐                             │
│               │  SQLite / Postgres │                             │
│               └───────────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
         │                                          │
         ▼                                          ▼
  GitHub API (PyGitHub)                  Anthropic API (claude-sonnet)
  - Workflow runs                        - Root cause analysis
  - Log ZIP archives                     - Anti-pattern detection
  - File tree & source                   - Diff suggestions
```

---

## 3. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Backend framework** | FastAPI (Python 3.12) | Async REST API, dependency injection |
| **ORM** | SQLAlchemy 2.x (sync sessions) | All DB access via Repository pattern |
| **Database** | SQLite (dev) / PostgreSQL (prod) | Persistent storage of runs, indexes, analyses |
| **GitHub integration** | PyGitHub + requests | Fetch workflow runs, log ZIPs, source trees |
| **AST parsing** | tree-sitter + language plugins | Multi-language static code analysis |
| **Language support** | Python, JS/TS, Java, Go | tree-sitter grammar modules per extension |
| **AI / LLM** | `anthropic` SDK → `claude-sonnet-4-6` | Bottleneck root cause & fix generation |
| **Log parsing** | Pure-Python regex, JSON, heuristics | CI/CD & app log format handling |
| **Fuzzy matching** | `difflib.SequenceMatcher` | Log line ↔ source code correlation |
| **Statistics** | Python `statistics` stdlib | Mean, P50, P95, trend, anomaly scoring |
| **Frontend** | React 18 + React Router | Single-page app, all UI |
| **Styling** | Custom CSS variables (dark/light) | No framework dependency |
| **Build/Dev** | Vite | Frontend bundling |
| **Testing** | pytest + SQLite in-memory fixtures | Unit + integration tests |
| **Validation** | Pydantic v2 | Request/response schemas & LLM output parsing |

---

## 4. Repository Layout

```
/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app factory, CORS, lifespan
│   │   ├── config.py                  # Settings (pydantic-settings, .env)
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── health.py          # GET /api/health
│   │   │       ├── repos.py           # Repository CRUD + run listing
│   │   │       ├── runs.py            # Ingest + trace endpoints
│   │   │       ├── analysis.py        # Code indexing + bottleneck ranking
│   │   │       ├── ai_analysis.py     # LLM analysis + feedback
│   │   │       ├── dashboard.py       # Summary stats for both modes
│   │   │       └── app_logs.py        # All App Log Analysis endpoints
│   │   ├── core/
│   │   │   ├── exceptions.py          # Domain exception hierarchy
│   │   │   └── logging.py             # Structured logger setup
│   │   ├── db/
│   │   │   ├── session.py             # SQLAlchemy engine + get_db()
│   │   │   └── repository.py          # Data access objects (per-table classes)
│   │   ├── models/
│   │   │   ├── database.py            # SQLAlchemy ORM table definitions
│   │   │   └── schemas.py             # Pydantic request/response models
│   │   └── services/
│   │       ├── github_client.py       # GitHub API wrapper
│   │       ├── log_parser.py          # GitHub Actions log parser
│   │       ├── ingester.py            # CI/CD run ingestion orchestrator
│   │       ├── bottleneck_ranker.py   # Statistical ranking of slow steps
│   │       ├── ast_parser.py          # Multi-language tree-sitter AST parser
│   │       ├── trace_correlator.py    # Log excerpt → source code location
│   │       ├── ai_engine.py           # CI/CD LLM analysis engine
│   │       ├── fix_recommender.py     # Diff enrichment + confidence scoring
│   │       ├── app_log_parser.py      # Universal app log format parser
│   │       ├── app_ingester.py        # App log ingestion orchestrator
│   │       ├── app_trace_correlator.py# App function → source location
│   │       ├── app_ai_engine.py       # App log LLM analysis engine
│   │       └── log_schema_inferrer.py # Claude-powered log schema inference
│   └── tests/
│       ├── conftest.py                # In-memory SQLite fixtures
│       ├── test_log_parser.py
│       ├── test_ingester.py
│       ├── test_bottleneck_ranker.py
│       ├── test_trace_correlator.py
│       ├── test_fix_recommender.py
│       ├── test_feedback_loop.py
│       └── fixtures/
│           └── sample_javascript.js   # AST parsing test fixture
└── frontend/
    └── src/
        ├── pages/
        │   ├── Dashboard.jsx          # Dual-mode dashboard (CI/CD + App Logs)
        │   ├── Analyze.jsx            # 7-stage analysis pipeline UI
        │   ├── Runs.jsx               # CI/CD run browser
        │   ├── AppLogUpload.jsx       # Log upload with format preview
        │   └── Settings.jsx           # Repo management + webhook guide
        └── services/
            └── api.js                 # All fetch() calls to /api/
```

---

## 5. Data Model (Database Schema)

### CI/CD Tables

```
tracked_repositories
  id, full_name (owner/repo), owner, name, default_branch, is_active, created_at

pipeline_runs
  id, repository_id → tracked_repositories
  github_run_id, run_number, workflow_name
  status, conclusion, head_branch, head_sha
  total_duration_ms, created_at, ingested_at

step_timings
  id, pipeline_run_id → pipeline_runs
  step_name, step_number, duration_ms
  started_at, ended_at, status, annotation
  log_excerpt (TEXT — raw log lines for this step)
  source_function (filled after trace correlation)

code_indexes
  id, repository_id, commit_sha
  total_functions, total_log_calls
  language_breakdown (JSON), status, created_at

indexed_functions
  id, code_index_id → code_indexes
  function_name, qualified_name, file_path
  line_number, end_line_number, calls_json (JSON list), language

indexed_log_calls
  id, code_index_id
  log_string, file_path, line_number, function_name, log_level, language

analyses
  id, pipeline_run_id, repository_id
  status, root_cause, primary_bottleneck
  anti_patterns_json, estimated_total_saving_ms
  raw_llm_response, llm_model, llm_prompt_tokens, llm_completion_tokens
  created_at, completed_at

analysis_suggestions
  id, analysis_id, rank
  title, description, target_function, target_file
  estimated_saving_ms, effort (low|medium|high)
  diff_hint (LLM-generated), enriched_diff (unified diff)
  confidence_score, anti_pattern

analysis_feedback
  id, analysis_id, suggestion_id
  verdict (accepted|rejected|partial), comment, created_at
```

### App Log Tables

```
app_log_sessions
  id, app_name, log_file_path, log_format
  source_repo (GitHub URL for code correlation)
  custom_pattern (user regex), total_duration_ms
  total_calls, status, ai_analysis (JSON), created_at

app_function_calls
  id, session_id → app_log_sessions
  function_name, call_number, duration_ms
  started_at, ended_at, log_excerpt
  source_function, source_file, source_line (after correlation)
  call_chain_json (JSON list of callers)

log_format_schemas
  id, app_name (cache key)
  strategy (inline|enter_exit), ts_regex, func_regex
  elapsed_regex, elapsed_unit, enter_pattern, exit_pattern
  created_at
```

---

## 6. CI/CD Log Analysis Pipeline — Deep Dive

### 6.1 GitHub Integration & Log Ingestion

**File:** `backend/app/services/github_client.py` + `ingester.py`

**Entry point:** `POST /api/runs/{github_run_id}/ingest?repo=owner/name`

The `LogIngester.ingest_run()` method orchestrates the full intake:

```
1. Resolve or create TrackedRepository in DB
2. Call github_client.get_workflow_run(run_id) → run metadata
3. Check if already ingested (dedup via github_run_id unique index)
4. Create PipelineRun record (status, conclusion, head_sha, timing)
5. github_client.download_logs(run_id) → ZIP archive in memory
6. For each .txt file in ZIP → parse_log_file() → list[ParsedStep]
7. For each ParsedStep → create StepTiming row (name, duration_ms, log_excerpt)
8. Update PipelineRun.total_duration_ms = sum of all steps
9. Return IngestionResult (steps_parsed, slowest_step, total_duration_ms)
```

The log archive from GitHub contains one `.txt` file per step, organized as `job_name/step_number_step_name.txt`. This path naming convention is parsed to extract the step number and human-readable name.

---

### 6.2 Log Parser (`log_parser.py`)

**Purpose:** Parse raw GitHub Actions log text into structured `ParsedStep` objects with precise millisecond timing.

**Key mechanisms:**

**Timestamp extraction:**
```python
TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\s+(.*)"
)
```
Every log line from GitHub Actions is prefixed with an ISO 8601 timestamp. The parser reads the first and last timestamp on each step file to compute `duration_ms = (ended_at - started_at).total_seconds() * 1000`.

**Annotation detection:**
```python
ANNOTATION_RE = re.compile(r"##\[(group|endgroup|error|warning)\](.*)")
```
GitHub Actions wraps step sections in `##[group]` / `##[endgroup]` markers. `##[error]` and `##[warning]` annotations are extracted and stored on the `StepTiming.annotation` column.

**Log excerpt trimming:** The first 2,000 characters of meaningful lines (non-timestamp-only lines) per step are stored as `log_excerpt` — this is the text later used for source code correlation.

**Key classes:**
- `ParsedLogLine` — single log line with timestamp, message, annotation
- `ParsedStep` — one CI step: name, number, timestamps, duration, status, log_excerpt, lines

---

### 6.3 Bottleneck Ranker (`bottleneck_ranker.py`)

**Purpose:** Given all step timing history across N runs, produce a ranked list of steps that are genuinely causing slowness — not just slow on the most recent run.

**`BottleneckRanker.compute_stats(repo_id, step_name, last_n=50)`** queries all duration samples for a step name across the last N runs and computes:

| Statistic | Method |
|---|---|
| `mean_ms` | arithmetic mean |
| `p50_ms` | median (index `n//2` after sort) |
| `p95_ms` | 95th percentile (index `int(n*0.95)`) |
| `std_dev_ms` | population std dev (`statistics.pstdev`) |
| `trend_slope` | **linear regression slope** (ms/run) |
| `latest_ms` | duration in most recent run |
| `pct_of_total` | `mean_ms / sum(all_step_means)` |

**Trend computation (linear regression):**
```python
x_mean = (n - 1) / 2
y_mean = mean(durations)
slope = Σ[(i - x_mean)(d - y_mean)] / Σ[(i - x_mean)²]
```
A positive slope means the step is getting slower run-over-run — a leading indicator of a growing problem.

**Composite bottleneck score:**
```python
score = 0.5 * pct_of_total          # weight: share of total pipeline time
      + 0.3 * (anomaly_score / 5.0)  # weight: current run vs historical avg (z-score clamped 0-5)
      + 0.2 * (1.0 if slope > 0 else 0.0)  # weight: increasing trend flag
```

The anomaly score is `(latest_ms - mean_ms) / std_dev_ms`, clamped to [0, 5]. This catches steps that are significantly worse *right now* vs their historical average.

---

### 6.4 AST Indexer (`ast_parser.py`)

**Purpose:** Build a queryable in-memory index of the repository's source code — every function, every `console.log`/`print`/`logger.info` call, and the call graph between them.

**Supported languages and their tree-sitter modules:**

| Extension | Module | Function Node Types |
|---|---|---|
| `.py` | `tree_sitter_python` | `function_definition` |
| `.js` | `tree_sitter_javascript` | `function_declaration`, `method_definition` |
| `.ts` | `tree_sitter_typescript` | `function_declaration`, `method_definition` |
| `.tsx` | `tree_sitter_typescript` (tsx variant) | same |
| `.java` | `tree_sitter_java` | `method_declaration` |
| `.go` | `tree_sitter_go` | `function_declaration`, `method_declaration` |

**Log call patterns per language:**

```python
# Python
{"logger.info", "logger.error", "logger.warning", "print", "logging.info", ...}

# JavaScript / TypeScript
{"console.log", "console.error", "console.warn", "logger.info", ...}

# Java
{"log.info", "log.error", "logger.info", "System.out.println", ...}

# Go
{"log.Print", "log.Printf", "fmt.Println", "slog.Info", ...}
```

**Indexing flow in `CodeIndexer.build_index()`:**
```
1. github_client.list_tree(repo, commit_sha)
   → full recursive file tree from GitHub API

2. Filter: supported extensions only, max file size (configurable), cap at MAX_FILES

3. For each source file:
   a. github_client.get_file_contents(path, ref=commit_sha)
   b. ast_parser.parse_file(content, path)
      → tree_sitter.Parser.parse(bytes) → CST
      → Walk CST for function_definition nodes → FunctionInfo list
      → Walk CST for call_expression nodes matching log patterns → LogCallInfo list

4. Build call graph: {function_name → [called_function_names]}
   (parsed from call_expression children inside each function body)

5. Build reverse call graph: {function_name → [callers]}

6. Build log_line_map: {log_string_text → SourceLocation}
   Maps the first argument of each log call to the function & line it appears in.

7. Persist to DB: CodeIndex + IndexedFunction[] + IndexedLogCall[]
```

**`CodeIndexData` — in-memory representation:**
```python
@dataclass
class CodeIndexData:
    functions: list[FunctionInfo]
    log_calls: list[LogCallInfo]
    call_graph: dict[str, list[str]]          # forward: fn → calls
    reverse_call_graph: dict[str, list[str]]  # reverse: fn → callers
    log_line_map: dict[str, SourceLocation]   # log text → file:line:fn
```

The `get_callers(function_name, max_depth=5)` method does a DFS up the reverse call graph to produce the full call chain reaching any function.

---

### 6.5 Trace Correlator (`trace_correlator.py`)

**Purpose:** Given a `PipelineRun` and its `CodeIndexData`, map each slow CI step's log excerpt back to the exact source file, line number, and function that produced that log output.

**Why this is the engineering centerpiece:** CI/CD logs contain human-readable text like `"Running database migrations"`. The source code somewhere has `logger.info("Running database migrations")`. The trace correlator bridges these two worlds.

**Three-tier matching cascade:**

**Tier 1 — Exact match (confidence: 1.0)**
```python
# Strip GitHub timestamps and ##[group] annotations from log lines
cleaned = TIMESTAMP_STRIP_RE.sub("", line)
cleaned = ANNOTATION_STRIP_RE.sub("", cleaned).strip()

# Direct dictionary lookup in log_line_map
if cleaned in index.log_line_map:
    return log_line_map[cleaned], 1.0, "exact"
```

**Tier 2 — Fuzzy match (confidence: 0.5–0.9+)**
```python
# difflib.get_close_matches for every cleaned log line vs every known log string
matches = difflib.get_close_matches(line, all_log_strings, n=1, cutoff=threshold)
ratio = difflib.SequenceMatcher(None, line, match).ratio()
# Default threshold from config: FUZZY_MATCH_THRESHOLD = 0.6
```

**Tier 3 — Grep fallback (confidence: 0.3–0.5)**
```python
# Normalize step name: "Run npm install" → "npm install"
# Search for that substring in function names, then file paths
for func in index.functions:
    if search_term in func.name.lower():
        return SourceLocation(func.file_path, func.line_number, func.name), 0.5, "grep"
```

After correlation, each `AnnotatedStep` carries:
- `source_location`: `{file_path, line_number, function_name, qualified_name}`
- `call_chain`: list of `CallChainEntry` (callers of the matched function, depth ≤ 5)
- `match_method`: `"exact"` | `"fuzzy"` | `"grep"` | `None`
- `match_confidence`: float 0.0–1.0

---

### 6.6 AI Engine (`ai_engine.py`)

**Purpose:** Assemble rich context from bottleneck rankings, trace correlation, and source code, then call Claude to produce structured JSON with root cause, anti-patterns, and ranked fix suggestions.

**Context assembly (`_assemble_context`):**
```
AnalysisContext
├── repo_full_name, commit_sha
├── total_duration_ms, target_duration_ms (= current * 0.5 as improvement goal)
├── status, conclusion
├── feedback_history: past accepted/rejected suggestions for this repo (loop-learning)
└── bottlenecks: list[BottleneckContext]
    ├── step_name, duration_ms, p95_ms, pct_of_total, trend_direction
    ├── source_function, source_file, source_line (from TraceCorrelator)
    ├── call_chain string (e.g. "main → build → install_deps")
    └── function_source_code (fetched live from GitHub API at analysis time)
```

**Prompt construction:** The user prompt is built as a structured markdown document:
- Pipeline run summary section
- Top N slowest steps section (each with timing, source location, call chain, and actual source code)
- Developer feedback history (prior accepted/rejected suggestions)
- JSON schema for expected response

**System prompt:** Contains the `ANTI_PATTERN_EXAMPLES` catalog (7 well-known CI anti-patterns with detection heuristics and typical savings estimates).

**LLM call:**
```python
client = anthropic.Anthropic()
message = client.messages.create(
    model=settings.LLM_MODEL,  # "claude-sonnet-4-6"
    max_tokens=1000,
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_prompt}],
)
```

**Response parsing with Pydantic:**
```python
class LLMAnalysisResult(BaseModel):
    root_cause: str
    primary_bottleneck: str
    anti_patterns: list[str]
    suggestions: list[LLMSuggestion]
    estimated_total_saving_ms: int = Field(ge=0)

class LLMSuggestion(BaseModel):
    title: str
    description: str
    target_function: str
    target_file: str
    estimated_saving_ms: int = Field(ge=0)
    effort: str = Field(pattern=r"^(low|medium|high)$")
    diff_hint: str       # e.g. "Before: npm install\nAfter: npm install --cache-dir .cache"
```

Pydantic validation ensures the LLM output is structurally correct before persistence. If validation fails, a `LLMError` is raised and the analysis is marked failed.

---

### 6.7 Fix Recommender (`fix_recommender.py`)

**Purpose:** Post-process raw LLM suggestions to add two things:
1. A unified diff format enriched diff (from the LLM's `diff_hint` prose)
2. A numeric confidence score (0.0–1.0)

**Unified diff generation:**
```python
# Parse LLM's diff_hint in multiple formats:
# - "Before: old code\nAfter: new code"
# - "old → new"
# - "+new line\n-old line" (git diff format)

before_lines, after_lines = _parse_diff_hint(diff_hint)
diff = difflib.unified_diff(before_lines, after_lines, fromfile="a/path", tofile="b/path")
```

**Confidence score computation (4 factors, range 0.0–1.0):**

```python
score = 0.5  # base

# Factor 1: Anti-pattern recurrence in past analyses for this repo
if count_past_anti_pattern(repo_id, anti_pattern) >= 3:
    score += 0.3   # seen 3+ times → high confidence pattern
elif count >= 1:
    score += 0.15  # seen before → moderate boost

# Factor 2: Target function verified to exist in code index
if function_name_in_code_index:
    score += 0.1   # grounded recommendation

# Factor 3: Saving estimate is in a realistic range (500ms–300s)
if 500 <= estimated_saving_ms <= 300_000:
    score += 0.1

# Factor 4: Developer feedback history for this anti-pattern + repo
if accepted_count > 0:
    score += 0.15  # developer liked similar suggestions before
if rejected_count > 0 and accepted_count == 0:
    score -= 0.2   # developer consistently rejected this anti-pattern

return clamp(score, 0.0, 1.0)
```

This feedback loop means the system gets smarter over time: suggestions that developers accept get boosted; suggestions they reject get penalized in future analyses for the same repository.

---

## 7. Application Log Analysis Pipeline — Deep Dive

### 7.1 Log Format Detection

**File:** `app_log_parser.py` — `FormatDetector` class

Before parsing begins, the system needs to know what format the log file uses. The detector scores 8 candidate formats against the first 100 lines:

| Format | Detection Strategy |
|---|---|
| `json` | Try `json.loads()` on each line; score = fraction that parse |
| `radcom` | Regex for `D:timestamp FN:method` pattern |
| `spring` | Regex for `YYYY-MM-DD HH:MM:SS.mmm LEVEL [thread]` prefix |
| `rails` | Regex for `Completed 200 OK` / `Processing by` / `Started GET` |
| `tshark` | Regex for `Frame N:` / `dissect_*` / `elapsed=N` |
| `syslog` | Regex for `Mon DD HH:MM:SS host app[pid]:` |
| `logfmt` | Regex for ≥3 `key=value` pairs per line |
| `enter_exit` | Count `ENTER`/`EXIT` / `START`/`END` keyword pairs |

Each scorer returns a float 0.0–1.0. The format with the highest score above 0.3 wins. Below 0.3, it falls back to the `heuristic` parser.

A **real-time preview** is also available: `POST /api/app-logs/detect-format` accepts just the first 50 lines of a file (as JSON), runs detection, and returns the detected format + confidence + 5 sample parsed records — all before the full upload. This is wired to the file-drop event in the UI.

---

### 7.2 App Log Parser (`app_log_parser.py`)

**Architecture:** One `BaseParser` subclass per format, all returning `list[UniversalLogRecord]`.

```python
@dataclass
class UniversalLogRecord:
    func_name:   str    # "processPayment", "handle_request", etc.
    duration_ms: int    # how long this function took
    timestamp:   datetime
    log_excerpt: str    # surrounding context lines (3–5 lines)
    raw_line:    str    # original matched line
    call_number: int    # nth call of this function in the session
```

**Per-format parsing strategies:**

**JSON parser:** Looks for keys `func`, `function`, `operation`, `method` (for name) and `elapsed_ms`, `duration_ms`, `duration`, `time_ms` (for timing). Handles both inline records (`{"func":"x","elapsed_ms":42}`) and `event: exit` records.

**Spring Boot parser:** Matches `fetchUsers() in 1234ms` patterns at end of log lines. Also handles `Executing query [SELECT *] took 890ms`.

**Rails parser:** Parses `Completed 200 OK in 1234ms (Views: 12ms | ActiveRecord: 890ms)` → emits separate records for the full request and each sub-component.

**tshark parser:** Matches `dissect_tcp  elapsed=0.342s` and `Frame N: ...` headers with `elapsed` fields.

**syslog parser:** Extracts function name from the message body, duration from `Xms` / `took X ms` suffixes.

**logfmt parser:** Parses `key=value` space-separated pairs; looks for `func=`, `duration=`, `elapsed=` keys.

**enter_exit parser:** Pairs `ENTER functionName` / `EXIT functionName (2345ms)` across lines, computing duration from the exit line's embedded timing or from timestamp delta between enter and exit events.

**heuristic parser (fallback):** `r'\b(\w[\w.]+)\b.*?\b(\d+(?:\.\d+)?)\s*(ms|s|us)\b'` — catches any line mentioning a word followed by a duration value and unit.

**Custom parser:** The user provides a Python-compatible named-group regex:
```
(?P<func>\w+)\s+completed in (?P<elapsed>\d+)(?P<unit>ms|s)
```
Groups `func`, `elapsed`, `unit`, `ts` (optional timestamp) are extracted.

---

### 7.3 AI Schema Inferrer (`log_schema_inferrer.py`)

**Purpose:** When none of the built-in format scorers achieve >0.3 confidence, Claude itself is asked to infer the log schema from sample lines.

**Prompt template:**
```
These are sample lines from an application log file:

{sample_lines}

Identify the timestamp, function/operation name, and duration fields.
Return ONLY a JSON object with:
  strategy: "inline" or "enter_exit"
  ts_regex: named-group regex or null
  func_regex: named-group regex or null
  elapsed_regex: named-group regex or null
  elapsed_unit: "ms" | "s" | "us"
  enter_pattern: regex for entry lines or null
  exit_pattern: regex for exit lines or null
```

The response is parsed and validated:
1. All regex strings are compiled with `re.compile()` to verify correctness
2. The inferred schema is cached in the `log_format_schemas` table keyed by `app_name`
3. On the next upload from the same app, the cached schema is used without another LLM call

---

### 7.4 App Trace Correlator (`app_trace_correlator.py`)

**Purpose:** Unlike CI/CD correlation where we match log text, here the log already contains real function names. The task is to map those runtime function names back to their source file locations in the indexed codebase.

**Three-tier matching cascade:**

**Tier 1 — Exact match:**
```python
by_name = {f.function_name: [f, ...] for f in indexed_functions}
if target_function in by_name:
    return by_name[target_function][0], "exact"
```

**Tier 2 — Normalised match:**
```python
def _normalise(name: str) -> str:
    name = re.sub(r"\(.*\)", "", name).strip()  # remove "()" suffixes
    name = name.lstrip("_")                      # strip leading underscores
    name = name.rsplit(".", 1)[-1]               # strip module prefix: "pkg.Func" → "Func"
    name = name.rsplit("::", 1)[-1]              # strip C++/Rust:: prefix
    return name.lower()
```

**Tier 3 — Fuzzy match:**
```python
# difflib.SequenceMatcher ratio ≥ FUZZY_MATCH_THRESHOLD (default 0.6)
ratios = [(difflib.SequenceMatcher(None, norm_target, norm_fn).ratio(), fn)
          for fn in all_funcs]
best = max(ratios, key=lambda x: x[0])
if best[0] >= threshold:
    return best[1], "fuzzy"
```

After matching, the call chain is built from the reverse call graph stored in the `CodeIndex`:
```python
# Walk reverse_call_graph up to 5 levels
chain = [{"fn": caller.function_name, "file": caller.file_path, "line": caller.line_number}
         for caller in get_callers(matched_function)]
```

Results are written back to `AppFunctionCall.source_file`, `.source_line`, `.call_chain_json`.

---

### 7.5 App AI Engine (`app_ai_engine.py`)

**Runtime anti-patterns catalog (10 patterns):**

The App AI Engine ships with a different catalog than the CI/CD engine, targeting runtime behavioral issues:

| # | Anti-Pattern | Typical Saving | Fix |
|---|---|---|---|
| 1 | Busy-wait loop | 5,000–15,000ms | condition variable / event.wait() |
| 2 | N+1 function calls | 2,000–10,000ms | batch calls outside loop |
| 3 | Synchronous blocking I/O | 3,000–12,000ms | async I/O / non-blocking select() |
| 4 | Unbounded data accumulation | 1,000–8,000ms | ring buffer / streaming |
| 5 | Repeated recomputation | 1,000–5,000ms | memoization / caching |
| 6 | Lock contention | 1,000–6,000ms | narrow critical section |
| 7 | String concatenation in loop | 500–3,000ms | join() / StringBuilder |
| 8 | Missing connection pooling | 500–5,000ms | connection pool |
| 9 | Excessive serialization | 200–2,000ms | cache parsed result / binary format |
| 10 | Unindexed DB query in hot path | 1,000–8,000ms | DB index |

**Context assembly for app logs:**
```
AppAnalysisContext
├── app_name, session_id
├── total_duration_ms, total_calls
├── top N slowest functions (from AppFunctionCall ordered by duration_ms desc)
│   ├── function_name, duration_ms, call_count
│   ├── source_file, source_line (from AppTraceCorrelator)
│   ├── call_chain (callers)
│   └── log_excerpt (surrounding log context)
└── target_functions (optional user-specified list)
```

The same `Analysis` + `AnalysisSuggestion` ORM tables are reused, so the feedback routes and history tracking work unchanged for app log analyses.

---

## 8. How CI/CD and App Logs Are Correlated with the Codebase

This is the core technical innovation. Here is the precise data flow connecting a slow log entry to the line of source code that caused it:

### For CI/CD Logs:

```
GitHub Actions log ZIP
  └── 3_Run tests.txt
      2024-03-19T10:32:01.456Z Running database migrations
      2024-03-19T10:32:08.123Z Migration completed
                    │
                    ▼ (log_parser.py)
StepTiming(
  step_name="Run tests",
  duration_ms=6667,
  log_excerpt="Running database migrations\nMigration completed"
)
                    │
                    ▼ (ast_parser.py — at index time, earlier)
IndexedLogCall(
  log_string="Running database migrations",
  file_path="db/migrate.py",
  line_number=47,
  function_name="run_migrations"
)
                    │
                    ▼ (trace_correlator.py — at analysis time)
log_line_map["Running database migrations"] = SourceLocation(
  file_path="db/migrate.py",
  line_number=47,
  function_name="run_migrations"
)

Step log excerpt → exact match → run_migrations @ db/migrate.py:47

                    │
                    ▼ (reverse call graph)
call_chain = ["main", "build_pipeline", "run_migrations"]
```

### For Application Logs:

```
Application log file (Spring Boot format)
  2024-03-19 10:32:01.456 INFO [main] c.e.Svc - fetchUsers() in 1234ms
                    │
                    ▼ (app_log_parser.py — SpringParser)
AppFunctionCall(
  function_name="fetchUsers",
  duration_ms=1234,
  log_excerpt="fetchUsers() in 1234ms"
)
                    │
                    ▼ (app_trace_correlator.py)
IndexedFunction(
  function_name="fetchUsers",       ← exact name match
  file_path="src/UserService.java",
  line_number=89
)

AppFunctionCall updated:
  source_function="fetchUsers"
  source_file="src/UserService.java"
  source_line=89
  call_chain_json=[{"fn":"UserController.getAll","file":"...","line":45}]
```

### The Shared Code Index

Both pipelines share the **same `CodeIndex` / `IndexedFunction` / `IndexedLogCall` tables** for a given repository and commit SHA. This means:

- If a repo is tracked for CI/CD analysis **and** app logs are uploaded with `source_repo=owner/repo`, the same AST index serves both correlation paths.
- The CI/CD path matches via **log string text** (because the log output contains the literal text of `logger.info("...")` calls).
- The app log path matches via **function name** (because the runtime log contains the actual function name).

---

## 9. Composite Bottleneck Scoring Algorithm

Both CI/CD and app log analysis use the same conceptual ranking formula, implemented in `bottleneck_ranker.py`:

```
CompositeScore = 0.5 × PctOfTotal
              + 0.3 × NormalisedAnomaly
              + 0.2 × TrendFlag

where:
  PctOfTotal        = step_mean_ms / sum(all_step_means)        [0.0–1.0]
  NormalisedAnomaly = clamp((latest_ms - mean_ms) / std_dev_ms, 0, 5) / 5.0
  TrendFlag         = 1.0 if linear_regression_slope > 0 else 0.0
```

**Why these weights:**
- 50% weight on `PctOfTotal` — the biggest absolute time wasters matter most
- 30% weight on anomaly — a step that is suddenly worse than usual needs attention now
- 20% weight on trend — a step getting slowly worse over time should be addressed before it becomes critical

**Linear regression for trend:** A least-squares regression is computed over the ordered sequence of duration samples. The slope (`ms/run`) tells us whether the step is getting faster or slower over time, independent of absolute duration.

---

## 10. API Routes Reference

### CI/CD Routes

| Method | Path | Service | Description |
|---|---|---|---|
| `GET` | `/api/health` | — | Health check + DB connectivity |
| `POST` | `/api/repos` | TrackedRepoRepository | Add a GitHub repo to tracking |
| `GET` | `/api/repos` | TrackedRepoRepository | List all tracked repos |
| `GET` | `/api/repos/{owner}/{name}/runs` | PipelineRunRepository | Paginated run history |
| `GET` | `/api/repos/{owner}/{name}/github-runs` | GitHubClient | Fetch recent run IDs from GitHub API |
| `GET` | `/api/repos/{owner}/{name}/bottlenecks` | BottleneckRanker | Top-N ranked bottlenecks |
| `POST` | `/api/repos/{owner}/{name}/index` | CodeIndexer | Trigger AST indexing |
| `POST` | `/api/runs/{github_run_id}/ingest` | LogIngester | Ingest a GitHub Actions run |
| `GET` | `/api/runs/{run_id}` | PipelineRunRepository | Run detail + step timings |
| `GET` | `/api/runs/{run_id}/trace` | TraceCorrelator | Annotated trace with source locations |
| `POST` | `/api/runs/{run_id}/analyse` | AIEngine | Trigger LLM analysis |
| `GET` | `/api/runs/{run_id}/analysis/latest` | AnalysisRepository | Get latest analysis for run |
| `POST` | `/api/analyses/{id}/feedback` | AnalysisFeedback | Submit developer feedback |
| `GET` | `/api/dashboard/summary` | Dashboard service | Aggregated stats for both modes |

### App Log Routes

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/app-logs/detect-format` | Format detection preview (pre-upload) |
| `POST` | `/api/app-logs/upload` | Upload + parse log file → create AppLogSession |
| `GET` | `/api/app-logs/sessions` | List all sessions |
| `GET` | `/api/app-logs/sessions/{id}` | Session detail + function calls |
| `POST` | `/api/app-logs/sessions/{id}/index-source` | Trigger code index for `source_repo` |
| `GET` | `/api/app-logs/sessions/{id}/trace` | Source-correlated function calls |
| `POST` | `/api/app-logs/sessions/{id}/analyse` | Run LLM analysis on session |
| `GET` | `/api/app-logs/sessions/{id}/analysis` | Latest analysis for session |

---

## 11. Frontend — Analyze Pipeline (React)

The `Analyze.jsx` page implements a **7-stage sequential analysis pipeline** with live logging per stage. Each stage is shown as a collapsible card with a status indicator (running / success / error / skipped).

```
Stage 1: "Add Repo"         → POST /api/repos {full_name}
Stage 2: "Fetch Runs"       → GET /api/repos/{owner}/{name}/github-runs
Stage 3: "Ingest Runs"      → POST /api/runs/{id}/ingest  (loops N runs)
Stage 4: "Index Source"     → POST /api/repos/{owner}/{name}/index
Stage 5: "Rank Bottlenecks" → GET  /api/repos/{owner}/{name}/bottlenecks
Stage 6: "AI Analysis"      → POST /api/runs/{run_id}/analyse
Stage 7: "Download Report"  → Generate markdown report in browser
```

Each stage emits timestamped log lines to its panel in real time, showing exact API responses (run IDs, step names, timings, function names, estimated savings). The final report is a complete markdown document with all ingested runs, code index stats, bottleneck table, and AI analysis with suggestion diff hints — all downloadable as a `.md` file.

The Dashboard supports two modes toggled via buttons:
- **CI/CD Pipeline mode** — shows tracked repos, run counts, pipeline duration trends, top bottlenecks
- **Application Logs mode** — shows uploaded app sessions, function call counts, slowest functions per app

---

## 12. Testing Strategy

**Test setup:** All tests use an in-memory SQLite database created fresh per test via the `db_session` fixture in `conftest.py`:
```python
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(bind=engine)
```

**Test coverage by module:**

| Test File | What It Covers |
|---|---|
| `test_log_parser.py` | Timestamp parsing, annotation extraction, step duration computation, log excerpt trimming |
| `test_ingester.py` | Full ingestion pipeline with mocked GitHub client, step timing DB writes |
| `test_bottleneck_ranker.py` | Mean/P50/P95/std_dev, linear regression slope, composite scoring, ranking order |
| `test_trace_correlator.py` | Exact match, fuzzy match, grep fallback, timestamp/annotation stripping, call chain building |
| `test_fix_recommender.py` | Diff hint parsing (git diff, before/after, arrow formats), unified diff generation, confidence scoring factors |
| `test_feedback_loop.py` | Feedback history's effect on confidence score, prompt injection of past verdicts, score clamping 0–1 |

**Notable testing patterns:**
- The bottleneck ranker tests use carefully constructed step duration sequences (e.g., `install_durations = [3000, 3200, ..., 5000]`) to make statistics and regression slopes predictable
- The trace correlator tests create real `IndexedLogCall` rows and verify which match method (`exact` vs `fuzzy` vs `grep`) is selected
- The feedback loop tests verify that `accepted` feedback boosts confidence and `rejected` feedback reduces it, while also testing the edge case where accepted cancels out a rejection penalty

---

## 13. Configuration & Environment Variables

All settings are loaded via `pydantic-settings` from environment variables or a `.env` file:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./dynamicanalyser.db` | SQLAlchemy DB URL |
| `GITHUB_TOKEN` | required | Personal access token for GitHub API |
| `ANTHROPIC_API_KEY` | required | Anthropic API key for LLM calls |
| `LLM_MODEL` | `claude-sonnet-4-6` | Claude model string |
| `APP_LOG_MAX_SIZE_MB` | `50` | Max upload size for app log files |
| `APP_LOG_UPLOAD_DIR` | `./uploads` | Directory for saved log files |
| `AST_INDEX_MAX_FILES` | `500` | Max source files to index per repo |
| `AST_INDEX_MAX_FILE_SIZE_KB` | `500` | Max source file size to parse |
| `FUZZY_MATCH_THRESHOLD` | `0.6` | difflib ratio cutoff for fuzzy log matching |
| `ANALYSIS_BOTTLENECK_TOP_N` | `3` | How many top bottlenecks to send to LLM |
| `ANALYSIS_HISTORY_WINDOW` | `20` | Number of past runs for bottleneck statistics |
| `DEBUG` | `false` | Enable SQLAlchemy query echo |

---

## 14. End-to-End Data Flow Walkthrough

Here is the complete journey for a single CI/CD analysis:

```
Developer clicks "Analyse" on owner/repo
         │
         ▼ POST /api/repos {full_name: "owner/repo"}
TrackedRepository created or fetched from DB
         │
         ▼ GET /api/repos/owner/repo/github-runs?limit=5
GitHubClient.get_workflow_runs() → list of recent GitHub Actions run IDs
         │
         ▼ POST /api/runs/123456/ingest?repo=owner/repo  (per run)
         │   GitHubClient.download_logs(123456) → ZIP archive
         │   log_parser.parse_log_file() → list[ParsedStep] with durations
         │   PipelineRun + StepTiming[] saved to DB
         ▼
PipelineRun(id=7, github_run_id=123456, total_duration_ms=45000)
StepTiming(step_name="Install deps", duration_ms=12000, log_excerpt="Installing npm packages...")
StepTiming(step_name="Run tests",    duration_ms=8000,  log_excerpt="Running test suite...")
StepTiming(step_name="Build",        duration_ms=6000,  log_excerpt="Starting build process...")
         │
         ▼ POST /api/repos/owner/repo/index
         │   GitHubClient.list_tree(repo, commit_sha) → 847 source files
         │   Filter → 312 supported files (.py, .js, .ts)
         │   For each file: tree-sitter parse → FunctionInfo[] + LogCallInfo[]
         │   build_call_graph() + build_reverse_graph() + build_log_line_map()
         ▼
CodeIndex(total_functions=1247, total_log_calls=423)
IndexedLogCall(log_string="Installing npm packages", file_path="scripts/ci.js", line=12, fn="installDependencies")
IndexedLogCall(log_string="Running test suite", file_path="scripts/ci.js", line=34, fn="runTests")
         │
         ▼ GET /api/repos/owner/repo/bottlenecks
         │   BottleneckRanker.rank_bottlenecks(repo_id, last_n=20, top_n=3)
         │   For each step: compute mean, P95, std_dev, trend_slope
         │   Composite score = 0.5*pct + 0.3*anomaly + 0.2*trend
         ▼
BottleneckReport: [
  {rank:1, step:"Install deps", score:0.623, mean_ms:11800, p95_ms:14200, trend:"increasing"},
  {rank:2, step:"Run tests",    score:0.341, mean_ms:7900,  p95_ms:9100,  trend:"stable"},
]
         │
         ▼ POST /api/runs/7/analyse
         │
         │   TraceCorrelator.correlate_run(7)
         │     "Installing npm packages" → exact match → installDependencies @ scripts/ci.js:12
         │     "Running test suite"      → exact match → runTests @ scripts/ci.js:34
         │     call_chain: main → build → installDependencies
         │
         │   AIEngine._assemble_context()
         │     Fetches source code of installDependencies from GitHub API
         │     Injects bottleneck stats + source + call chain into prompt
         │     Fetches past feedback history for owner/repo
         │
         │   anthropic.messages.create(model="claude-sonnet-4-6", ...)
         │   → JSON: {root_cause, primary_bottleneck, anti_patterns, suggestions}
         │
         │   Pydantic validates LLMAnalysisResult
         │   FixRecommender.enrich_analysis()
         │     Parse diff_hint → generate unified diff
         │     Compute confidence: 0.5 base + recurrence + code_index + saving range + feedback
         ▼
Analysis(id=3, status="completed",
  root_cause="npm install runs without cache on every CI run",
  primary_bottleneck="Install deps",
  estimated_total_saving_ms=9000)
AnalysisSuggestion(rank=1,
  title="Add npm dependency caching",
  target_function="installDependencies",
  target_file="scripts/ci.js",
  estimated_saving_ms=9000,
  effort="low",
  enriched_diff="--- a/scripts/ci.js\n+++ b/scripts/ci.js\n-npm install\n+npm install --cache .npm",
  confidence_score=0.85)
         │
         ▼ Developer clicks thumbs up on suggestion
POST /api/analyses/3/feedback {verdict:"accepted", suggestion_id:1}
AnalysisFeedback saved → next analysis for this repo gets +0.15 confidence for "No dependency caching"
```

---

*DynamicAnalyser — turning log noise into actionable engineering intelligence.*