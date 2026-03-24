# DynamicAnalyzer — Full Pipeline Analysis Report

**Date:** 2026-03-24
**Target Repository:** `OpenLake/canonforces`
**Runs Ingested:** 5 (GitHub run IDs: 23408210926, 23408210899, 23404099269, 23404099259, 23404064496)
**Workflows Analyzed:** Canonforces CI Pipeline (runs #18–20) · Docker Build Check (runs #7–8)

---

## 1. Pipeline Execution Summary

All 6 pipeline stages completed successfully.

| Stage | Result |
|-------|--------|
| Add Repository | ✅ `OpenLake/canonforces` tracked (DB id=2) |
| Fetch GitHub Runs | ✅ 5 completed runs fetched |
| Ingest Runs | ✅ 5 runs ingested · 21 total steps |
| Build Code Index | ✅ Functions and log calls indexed |
| Compute Bottlenecks | ✅ 5 bottlenecks ranked across 5 runs |
| AI Analysis | ✅ `claude-sonnet-4-6` — 5 suggestions · 154s estimated saving |

All 18 testable API routes executed successfully end-to-end (same as previous report).

---

## 2. Ingestion Results

5 completed workflow runs ingested for `OpenLake/canonforces`.

| DB Run ID | GitHub Run ID | Workflow | Run # | Branch | Steps | Total Duration |
|-----------|--------------|----------|-------|--------|-------|---------------|
| 6 | 23408210926 | Docker Build Check | 8 | main | 1 | 83,787ms (1.4 min) |
| 7 | 23408210899 | Canonforces CI Pipeline | 20 | main | 5 | 190,785ms (3.2 min) |
| 8 | 23404099269 | Canonforces CI Pipeline | 19 | main | 5 | 181,650ms (3.0 min) |
| 9 | 23404099259 | Docker Build Check | 7 | main | 1 | 84,789ms (1.4 min) |
| 10 | 23404064496 | Canonforces CI Pipeline | 18 | Adding-evaluation-pipeline | 5 | 182,007ms (3.0 min) |

**Average total duration (CI Pipeline runs only):** ~184,814ms (~3.1 minutes)
**Average total duration (Docker runs only):** ~84,288ms (~1.4 minutes)

### Parsed Steps (Run #20 — Canonforces CI Pipeline)

| Step Name | Duration (ms) | % of Total |
|-----------|--------------|------------|
| build | 52,537ms | 27.5% |
| tests (20) | 40,952ms | 21.5% |
| typecheck | 35,536ms | 18.6% |
| lint | 32,001ms | 16.8% |
| deploy | 29,759ms | 15.6% |

---

## 3. Bottleneck Analysis

Statistical analysis across **5 real pipeline runs**.

| Rank | Step Name | Score | % of Total | Mean (ms) | P95 (ms) | Trend |
|------|-----------|-------|------------|-----------|----------|-------|
| 1 | tests (20) | 0.3473 | 13.4% | 35,912 | 40,952 | **increasing** |
| 2 | lint | 0.3150 | 11.3% | 30,495 | 32,001 | **increasing** |
| 3 | typecheck | 0.3118 | 12.5% | 33,562 | 35,536 | **increasing** |
| 4 | docker-build | 0.1566 | 31.3% | 84,288 | 84,789 | decreasing |
| 5 | build | 0.0906 | 18.1% | 48,772 | 52,537 | decreasing |

**Key observations:**
- Top 3 bottlenecks (tests, lint, typecheck) are all **increasing** — pipeline is getting slower over time
- All three run sequentially despite being independent — they can be parallelised
- `docker-build` consumes 31% of total time but is **decreasing** (improving)
- `build` is also **decreasing** — likely benefiting from some existing caching

---

## 4. Code Index

Built AST index for `OpenLake/canonforces` (latest commit on main).

| Metric | Value |
|--------|-------|
| Status | completed |
| Language breakdown | Available via API |

**Note:** Canonforces is a competitive programming platform. The codebase includes backend services (Node.js/Python) and frontend (React). The CI pipeline runs lint, typecheck, tests, build, and deploy steps sequentially.

---

## 5. Trace Correlation

Trace correlation was not explicitly tested in this run. For CI pipelines running lint/typecheck/test steps, match rates are expected to be low because the step names describe tool operations, not application log strings. The trace correlator works best for deployment/migration workflows where CI output matches source log statements.

---

## 6. AI Analysis Results

**Model:** `claude-sonnet-4-6`
**Primary Bottleneck:** `tests`
**Total Estimated Saving:** 154,000ms (2.6 minutes per run)

### Root Cause

> The pipeline is running at 190,785ms against a 15,000ms target — more than 12× over budget. The three heaviest steps (tests at 40,952ms, typecheck at 35,536ms, and lint at 32,001ms) together account for 37.2% of total time and are all trending upward, suggesting no parallelism or caching has been applied. The tests step exhibits a duration consistent with sequential single-threaded execution (no `-n auto` / `--workers` flag), the lint and typecheck steps likely perform full re-analysis on every run with no incremental or cached output, and across all three steps there is no evidence of dependency caching, meaning npm/pip installs are re-executed from scratch each run. The combination of sequential test execution, absent build/tool caches, and no parallelisation of independent steps (lint, typecheck, and tests could all run concurrently) is responsible for the observed explosion in total pipeline time.

### Detected Anti-Patterns

1. Sequential test execution
2. No dependency caching
3. No build cache

### Suggestions

| # | Title | Saving | Effort | Confidence | Anti-Pattern |
|---|-------|--------|--------|------------|--------------|
| 1 | Parallelise test execution with pytest-xdist or jest --workers | 22,000ms | Low | 0.75 | Sequential test execution |
| 2 | Cache pip/npm dependencies between runs | 12,000ms | Low | 0.75 | No dependency caching |
| 3 | Run lint, typecheck, and tests as parallel CI jobs | 67,000ms | Medium | 0.75 | Sequential test execution |
| 4 | Enable incremental/cached output for typecheck (tsc --incremental or mypy cache) | 28,000ms | Medium | 0.75 | No build cache |
| 5 | Cache ESLint / Ruff lint results with --cache flag | 25,000ms | Low | 0.75 | No build cache |

**Suggestion #3 (parallel CI jobs) alone would save ~67s** — the single highest-impact change. Running lint, typecheck, and tests as separate parallel jobs means total pipeline time would approach the slowest individual step (~41s tests) instead of their sum (~108s).

---

## 7. Step Statistics

### tests (20)

| Metric | Value |
|--------|-------|
| Sample count | 3 runs |
| Mean | 35,912ms |
| P50 (median) | 34,835ms |
| P95 | 40,952ms |
| Trend slope | +573ms/run (increasing) |

### lint

| Metric | Value |
|--------|-------|
| Sample count | 3 runs |
| Mean | 30,495ms |
| P50 (median) | 31,121ms |
| P95 | 32,001ms |
| Trend slope | increasing |

### docker-build

| Metric | Value |
|--------|-------|
| Sample count | 2 runs |
| Mean | 84,288ms |
| P50 (median) | 84,789ms |
| P95 | 84,789ms |
| Trend slope | decreasing (improving) |

---

## 8. Dashboard & Analytics

| Metric | Value |
|--------|-------|
| Repositories tracked | 2 (tiangolo/fastapi + OpenLake/canonforces) |
| Pipeline runs stored | 10 |
| Completed analyses | 2 |
| Average pipeline duration | ~184,814ms (CI Pipeline) |
| Average estimated saving | 154,000ms |

**Anti-pattern frequency across both analyses:**
- Sequential test execution: 2× (4 suggestions total)
- No dependency caching: 2×
- No build cache: 2× (3 suggestions total)
- Large test fixtures: 1× (fastapi only)

---

## 9. UI Changes in This Session

The following UI improvements were made to show full pipeline visibility:

### New: Analyze Repo Page (`/analyze`)

A new pipeline runner page was added with:

1. **Live step-by-step progress** — each of the 6 pipeline stages shows:
   - Status indicator (spinner while running, ✓/✗ when done)
   - Expandable log panel with timestamped output for each stage
   - Inline result table/panel on expansion (runs table, bottleneck table, AI suggestions)

2. **Pipeline stages displayed:**
   - Stage 1 — Add Repository: calls `POST /api/repos`
   - Stage 2 — Fetch GitHub Runs: calls new `GET /api/repos/{owner}/{name}/github-runs`
   - Stage 3 — Ingest Runs: calls `POST /api/runs/{run_id}/ingest` for each run with live `N/total` counter
   - Stage 4 — Build Code Index: calls `POST /api/repos/{owner}/{name}/index` with progress note
   - Stage 5 — Compute Bottlenecks: calls `GET /api/repos/{owner}/{name}/bottlenecks?top_n=5`
   - Stage 6 — AI Analysis: calls `POST /api/runs/{run_id}/analyse`

3. **Download Report button** — generates a complete Markdown report client-side from accumulated pipeline data and triggers a browser download as `dynamicanalyzer-{repo}-{timestamp}.md`

4. **Done summary panel** — after completion shows KPI cards (runs ingested, functions indexed, bottlenecks, estimated saving) and links to RunDetail and RepoDetail pages

### New Backend Endpoint

`GET /api/repos/{owner}/{name}/github-runs?limit=5` — returns recent completed GitHub Actions run IDs, run numbers, workflow names, branches, and conclusions for the pipeline runner to ingest.

### Bug Fixed: Re-ingestion Error

`ingester.py` — `ingest_run()` previously raised `IngestionError` when a run had already been ingested. Fixed to return the cached result (existing DB run data) instead, so re-running the Analyze pipeline on the same repo doesn't abort at stage 3.

---

## 10. Conclusion

The DynamicAnalyzer pipeline runs **end-to-end correctly** on real GitHub Actions data from `OpenLake/canonforces`:

1. **Ingestion** — 5 real workflow runs parsed (1–5 steps per run, infrastructure files excluded)
2. **Bottleneck Detection** — tests, lint, and typecheck correctly identified as top bottlenecks, all trending upward; docker-build and build trending downward
3. **AI Analysis** — `claude-sonnet-4-6` produced 5 actionable suggestions with correct confidence scores (0.75), estimated 2.6 minutes of savings per run
4. **All 6 UI pipeline stages visible** — live logs, expandable result panels, download report button
5. **Report download works** — comprehensive Markdown report generated client-side

**Primary recommendation:** Run lint, typecheck, and tests as parallel CI jobs (Suggestion #3) — saves ~67s per run with medium effort.
