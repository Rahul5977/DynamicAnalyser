"""
Chunked static analysis for large GitHub repos.

1. Pull file tree + blob list from GitHub (no full clone).
2. Partition paths into domains: security, database, backend, frontend, infrastructure.
3. Run Python DB Layer1 (AST) on `.py` files in a temp directory mirror.
4. For each non-empty domain, call Claude with manifest + excerpts + AST signals.
5. Merge structured issues (before/after code + explanation) and an executive summary.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from collections import defaultdict
from typing import Any

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.logging import logger
from app.db.repository import StaticAnalysisRepository
from app.services.app_trace_correlator import _parse_github_url
from app.services.ast_parser import ASTParser
from app.services.db_analyser.layer1_scanner import Layer1Scanner
from app.services.github_client import GitHubClient


STATIC_EXTRA_EXT = frozenset(
    {".sql", ".prisma", ".graphql", ".yaml", ".yml", ".toml", ".md"}
)


def static_source_extensions() -> frozenset[str]:
    return frozenset(ASTParser.SUPPORTED_EXTENSIONS) | STATIC_EXTRA_EXT


def classify_domain(file_path: str) -> str:
    """Primary domain bucket for path-based chunking (one label per file)."""
    p = file_path.replace("\\", "/").lower()
    ext = os.path.splitext(p)[1]

    if ext in (".jsx", ".tsx", ".vue", ".css", ".scss", ".less", ".svelte"):
        return "frontend"

    sec_markers = (
        ".env",
        "id_rsa",
        ".pem",
        "secrets/",
        "secret_",
        "/oauth",
        "/auth/",
        "csrf",
        "xss",
        "jwt",
        "password",
        "api_key",
        "apikey",
        "credential",
    )
    if any(m in p for m in sec_markers):
        return "security"

    db_markers = (
        "migration",
        "alembic",
        "prisma",
        "/models/",
        "schema.sql",
        "knex",
        "sequelize",
        "migrations/",
        "drizzle",
        "typeorm",
        "querybuilder",
        "db/",
        "database/",
    )
    if ext in (".sql", ".prisma") or any(m in p for m in db_markers):
        return "database"

    infra_markers = (
        "dockerfile",
        "docker-compose",
        ".github/workflows",
        "kubernetes",
        ".tf",
        "terraform",
        "helm/",
        "nginx.conf",
        "k8s/",
    )
    if any(m in p for m in infra_markers) or p.endswith("dockerfile"):
        return "infrastructure"

    fe_markers = (
        "/frontend/",
        "/web/",
        "/ui/",
        "/client/",
        "/static/",
        "/components/",
        "src/pages/",
        "src/app/",
        "/views/",
    )
    if any(m in p for m in fe_markers):
        return "frontend"

    return "backend"


_DOMAINS_ORDER = (
    "security",
    "database",
    "backend",
    "frontend",
    "infrastructure",
)


class _LLMIssue(BaseModel):
    severity: str = Field(default="medium")
    title: str
    file_path: str = ""
    line_start: int = 0
    line_end: int = 0
    before_code: str = ""
    after_code: str = ""
    explanation: str = ""


class _LLMDomainResult(BaseModel):
    domain_summary: str = ""
    issues: list[_LLMIssue] = Field(default_factory=list)


STATIC_ANALYSIS_SYSTEM = """You are a principal security and software-quality engineer.
You analyse repository excerpts for ONE domain at a time.
You MUST respond with a single JSON object (no markdown fences) matching exactly:
{
  "domain_summary": "2-6 sentences for stakeholders",
  "issues": [
    {
      "severity": "critical|high|medium|low",
      "title": "short title",
      "file_path": "path/in/repo.ext",
      "line_start": 0,
      "line_end": 0,
      "before_code": "exact or representative snippet BEFORE fix",
      "after_code": "corrected snippet AFTER fix",
      "explanation": "why this is a problem and why the fix works"
    }
  ]
}
Rules:
- Prefer actionable items visible in the supplied code; do not invent files.
- If a signal mentions line numbers, align issues with those files.
- Always include non-empty before_code and after_code when suggesting a code fix.
- Use severity consistent with real risk (injection = critical/high)."""


EXEC_SUMMARY_SYSTEM = """You write concise executive summaries for engineering leads.
Respond with JSON only: {"executive_summary": "markdown string with ## headings and bullets"}"""


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\{[\s\S]*\})\s*$", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


def _security_signals(path: str, content: str) -> list[str]:
    hits: list[str] = []
    patterns = [
        (r"eval\s*\(", "possible eval injection"),
        (r"exec\s*\(", "dynamic exec"),
        (r"subprocess\.[a-z_]+\([^)]*shell\s*=\s*True", "subprocess shell=True"),
        (r"pickle\.loads?\s*\(", "unsafe pickle deserialization"),
        (r"yaml\.load\s*\([^)]*\)(?!\s*Loader\s*=\s*yaml\.SafeLoader)", "unsafe yaml.load"),
        (r"password\s*=\s*['\"][^'\"]+['\"]", "possible hard-coded password"),
        (r"api[_-]?key\s*=\s*['\"]", "possible hard-coded API key"),
        (r"SELECT\s+.+\s+FROM\s+.+\s*\+\s*|f[\"'].*SELECT.*\{", "possible SQL string building"),
    ]
    for pat, label in patterns:
        if re.search(pat, content, re.IGNORECASE | re.DOTALL):
            hits.append(f"{path}: {label}")
    return hits[:20]


def _pick_top_files(
    domain_files: list[tuple[str, str, int]],
    max_files: int,
    max_chars: int,
) -> list[tuple[str, str]]:
    """Sort by interest score desc, then take top N with truncated content."""
    domain_files.sort(key=lambda x: -x[2])
    out: list[tuple[str, str]] = []
    for path, content, _score in domain_files[:max_files]:
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n# … truncated …\n"
        out.append((path, content))
    return out


def _path_write(full: str, content: str) -> None:
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(full, "w", encoding="utf-8", errors="replace") as fh:
        fh.write(content)


def _layer1_issue_domain(file_path: str, category: str) -> str:
    c = category.lower()
    if (
        c.startswith("orm_")
        or c.startswith("transaction")
        or "sql" in c
        or c.startswith("n_plus_one")
        or c.startswith("fk_")
        or c.startswith("migration")
    ):
        return "database"
    return classify_domain(file_path)


class StaticAnalysisEngine:
    def __init__(self, db: Session):
        self.db = db
        self._settings = get_settings()

    def run(self, report_id: int) -> None:
        store = StaticAnalysisRepository(self.db)
        report = store.get_by_id(report_id)
        store.update_running(report_id)

        gh = GitHubClient()
        full_name = report.github_full_name
        sha = report.commit_sha
        settings = self._settings

        try:
            tree = gh.list_tree(full_name, sha)
        except Exception as e:
            store.update_failed(report_id, f"GitHub tree: {e}")
            return

        exts = static_source_extensions()
        max_repo = settings.STATIC_ANALYSIS_MAX_REPO_FILES
        max_sz = settings.AST_INDEX_MAX_FILE_SIZE_KB * 1024

        blobs: list[dict] = []
        for item in tree:
            path = item["path"]
            ext = os.path.splitext(path)[1].lower()
            if ext not in exts:
                continue
            if (item.get("size") or 0) > max_sz:
                continue
            blobs.append(item)

        if len(blobs) > max_repo:
            blobs = blobs[:max_repo]

        layer1_by_path: dict[str, list[str]] = defaultdict(list)
        layer1_issues: list[dict[str, Any]] = []
        security_all: list[str] = []

        py_paths = [b["path"] for b in blobs if b["path"].endswith(".py")]
        if py_paths:
            tmp_root = tempfile.mkdtemp(prefix="da-static-")
            try:
                written: list[str] = []
                for b in blobs:
                    if not b["path"].endswith(".py"):
                        continue
                    p = b["path"]
                    try:
                        src = gh.get_file_contents(full_name, p, ref=sha)
                    except Exception as e:
                        logger.warning("skip %s: %s", p, e)
                        continue
                    full = os.path.join(tmp_root, p)
                    _path_write(full, src)
                    written.append(p)

                if written:
                    res = Layer1Scanner(tmp_root, written).scan()
                    for op in res.operations:
                        rel = os.path.relpath(op.file_path, tmp_root).replace("\\", "/")
                        layer1_by_path[rel].append(
                            f"L{op.line_number} op={op.op_type} orm={op.orm_framework} table={op.table_hint}"
                        )
                    for f in res.findings:
                        rel = os.path.relpath(f.file_path, tmp_root).replace("\\", "/")
                        layer1_by_path[rel].append(
                            f"FINDING {f.category} [{f.severity}]: {f.title} — {f.description[:220]}"
                        )
                        layer1_issues.append(
                            {
                                "domain": _layer1_issue_domain(rel, f.category),
                                "severity": f.severity.lower(),
                                "title": f.title,
                                "file_path": rel,
                                "line_start": f.line_number,
                                "line_end": f.end_line_number,
                                "before_code": f.evidence or "",
                                "after_code": f.fix_code or "",
                                "explanation": f.fix_description or f.description,
                                "source": "ast_db_layer1",
                            }
                        )
            finally:
                shutil.rmtree(tmp_root, ignore_errors=True)
        domain_payloads: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        for b in blobs:
            path = b["path"]
            try:
                content = gh.get_file_contents(full_name, path, ref=sha)
            except Exception as e:
                logger.warning("fetch %s: %s", path, e)
                continue
            d = classify_domain(path)
            sigs = _security_signals(path, content)
            security_all.extend(sigs)
            score = 0
            nm = path.replace("\\", "/")
            if nm in layer1_by_path:
                score += 80 + len(layer1_by_path[nm]) * 5
            if sigs:
                score += 60
            if "test" in nm or "spec." in nm:
                score -= 15
            score += min(len(content) // 2000, 25)
            domain_payloads[d].append((path, content, score))

        if not settings.ANTHROPIC_API_KEY:
            store.update_failed(report_id, "ANTHROPIC_API_KEY not configured")
            return

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=6)
        model = settings.LLM_MODEL
        max_out = settings.STATIC_ANALYSIS_LLM_MAX_TOKENS
        max_per_domain = settings.STATIC_ANALYSIS_MAX_FILES_PER_DOMAIN
        max_chars = settings.STATIC_ANALYSIS_MAX_CHARS_PER_FILE

        total_pt = 0
        total_ct = 0
        all_issues: list[dict[str, Any]] = []
        domain_stats: dict[str, Any] = {}
        _domain_call_count = 0

        for dom in _DOMAINS_ORDER:
            payloads = domain_payloads.get(dom) or []
            if not payloads:
                domain_stats[dom] = {"file_count": 0, "llm_issues": 0, "files_sample": []}
                continue

            picked = _pick_top_files(payloads, max_per_domain, max_chars)
            manifest = [p for p, _ in picked]

            ast_lines: list[str] = []
            for path in manifest:
                rel = path.replace("\\", "/")
                if rel in layer1_by_path:
                    ast_lines.append(
                        "**"
                        + rel
                        + "**:\n- "
                        + "\n- ".join(layer1_by_path[rel][:12])
                    )
            if dom == "security":
                ast_lines.extend(security_all[:40])

            excerpt_blocks: list[str] = []
            for path, content in picked:
                excerpt_blocks.append(f"### FILE: {path}\n```\n{content}\n```")

            user_msg = "\n".join(
                [
                    f"DOMAIN: {dom}",
                    f"REPOSITORY: {full_name} @ {sha[:12]}",
                    f"FILES_IN_THIS_CHUNK ({len(manifest)} shown of {len(payloads)} in domain):",
                    json.dumps(manifest, indent=2),
                    "",
                    "## Static / AST signals (may be incomplete)",
                    "\n".join(ast_lines) if ast_lines else "(none)",
                    "",
                    "## Code excerpts",
                    "\n\n".join(excerpt_blocks),
                ]
            )

            if _domain_call_count > 0:
                time.sleep(3)
            _domain_call_count += 1
            try:
                resp = client.messages.create(
                    model=model,
                    max_tokens=max_out,
                    system=STATIC_ANALYSIS_SYSTEM,
                    messages=[{"role": "user", "content": user_msg}],
                )
            except Exception as e:
                logger.error("Claude domain %s failed: %s", dom, e)
                domain_stats[dom] = {
                    "file_count": len(payloads),
                    "llm_issues": 0,
                    "files_sample": manifest[:15],
                    "error": str(e)[:500],
                }
                continue

            raw = resp.content[0].text
            total_pt += resp.usage.input_tokens
            total_ct += resp.usage.output_tokens
            data = _extract_json_object(raw) or {}
            try:
                parsed = _LLMDomainResult.model_validate(data)
            except Exception:
                parsed = _LLMDomainResult(
                    domain_summary=data.get("domain_summary", "") if isinstance(data, dict) else "",
                    issues=[],
                )

            for issue in parsed.issues:
                all_issues.append(
                    {
                        "domain": dom,
                        "severity": (issue.severity or "medium").lower(),
                        "title": issue.title,
                        "file_path": issue.file_path or "",
                        "line_start": issue.line_start,
                        "line_end": issue.line_end,
                        "before_code": issue.before_code or "",
                        "after_code": issue.after_code or "",
                        "explanation": issue.explanation or "",
                        "source": "llm",
                    }
                )

            domain_stats[dom] = {
                "file_count": len(payloads),
                "llm_issues": len(parsed.issues),
                "files_sample": manifest[:15],
                "domain_summary": parsed.domain_summary,
            }

        all_issues.extend(layer1_issues)

        exec_summary = self._executive_summary_llm(
            client, model, full_name, sha, domain_stats, all_issues
        )
        total_pt += exec_summary.get("pt", 0)
        total_ct += exec_summary.get("ct", 0)
        summary_md = exec_summary.get("text") or self._fallback_summary(domain_stats, all_issues)

        store.update_completed(
            report_id,
            summary_markdown=summary_md,
            domains_json=json.dumps(domain_stats, indent=2),
            findings_json=json.dumps(all_issues, indent=2),
            llm_model=model,
            prompt_tokens=total_pt,
            completion_tokens=total_ct,
        )

    def _executive_summary_llm(
        self,
        client: anthropic.Anthropic,
        model: str,
        full_name: str,
        sha: str,
        domain_stats: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        tops = sorted(
            issues,
            key=lambda i: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                i.get("severity", "low"), 3
            ),
        )[:24]
        brief = json.dumps(
            {
                "domains": domain_stats,
                "top_findings": [
                    {k: v for k, v in x.items() if k in ("domain", "severity", "title", "file_path")}
                    for x in tops
                ],
            },
            indent=2,
        )[:12000]
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=min(2048, self._settings.STATIC_ANALYSIS_LLM_MAX_TOKENS),
                system=EXEC_SUMMARY_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Repository {full_name} @ {sha[:12]}.\n"
                            f"Consolidated domain stats + top findings JSON:\n{brief}\n"
                            "Write executive_summary markdown: repo-level risks, domain hotspots, "
                            "recommended priority order."
                        ),
                    }
                ],
            )
            raw = resp.content[0].text
            data = _extract_json_object(raw) or {}
            text = data.get("executive_summary", raw)
            return {
                "text": text,
                "pt": resp.usage.input_tokens,
                "ct": resp.usage.output_tokens,
            }
        except Exception as e:
            logger.warning("Executive summary LLM failed: %s", e)
            return {"text": None, "pt": 0, "ct": 0}

    def _fallback_summary(self, domain_stats: dict, issues: list[dict]) -> str:
        lines = ["## Static analysis overview", ""]
        for dom, st in domain_stats.items():
            if isinstance(st, dict) and st.get("file_count"):
                lines.append(f"- **{dom}**: {st['file_count']} files, {st.get('llm_issues', 0)} LLM issues")
        lines.append("")
        lines.append(f"**Total unified issues:** {len(issues)}")
        return "\n".join(lines)


def resolve_github_target(url_or_full: str | None, full_name_opt: str | None) -> str:
    if full_name_opt and "/" in full_name_opt:
        p = full_name_opt.strip().strip("/")
        if re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", p):
            return p
    if url_or_full:
        parsed = _parse_github_url(url_or_full.strip())
        if parsed:
            return parsed
        p = url_or_full.strip().strip("/")
        if re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", p):
            return p
    raise ValueError("Provide a valid github_url or full_name (owner/repo)")


def resolve_commit_sha(gh: GitHubClient, full_name: str, override: str | None) -> str:
    if override:
        return override
    runs = gh.get_workflow_runs(full_name, limit=1)
    if runs:
        return runs[0].head_sha
    repo_obj = gh._get_repo(full_name)
    # default branch from tracked repo if possible — else repo.default_branch
    branch = repo_obj.default_branch
    return repo_obj.get_branch(branch).commit.sha


def run_static_analysis_job(report_id: int) -> None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        StaticAnalysisEngine(db).run(report_id)
    except Exception as e:
        logger.exception("Static analysis job failed for report %s", report_id)
        try:
            StaticAnalysisRepository(db).update_failed(report_id, str(e))
        except Exception:
            logger.exception("Failed to mark static analysis as failed")
    finally:
        db.close()
