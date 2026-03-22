"""GitHub webhook handler: verifies signatures and processes events."""

import hashlib
import hmac
import json

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import AnalysisError
from app.core.logging import logger
from app.db.repository import TrackedRepoRepository, PipelineRunRepository, AnalysisRepository
from app.services.github_client import GitHubClient


class WebhookHandler:
    """Processes incoming GitHub webhook events."""

    def __init__(self, db: Session):
        self.db = db
        self._settings = get_settings()

    @staticmethod
    def verify_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
        """Verify the X-Hub-Signature-256 header."""
        if not signature_header or not secret:
            return False
        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"),
            payload_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def handle_workflow_run_completed(self, payload: dict) -> dict:
        """Process a workflow_run.completed event.

        Steps:
        1. Extract repo and run info
        2. Check if repo is tracked
        3. Ingest the run
        4. If duration exceeds threshold, trigger analysis and post PR comment
        """
        action = payload.get("action")
        if action != "completed":
            return {"status": "ignored", "reason": f"action={action}"}

        workflow_run = payload.get("workflow_run", {})
        repo_data = payload.get("repository", {})
        repo_full_name = repo_data.get("full_name", "")
        github_run_id = workflow_run.get("id")
        head_branch = workflow_run.get("head_branch", "")

        if not repo_full_name or not github_run_id:
            return {"status": "ignored", "reason": "missing repo or run_id"}

        # Check if repo is tracked
        repo_store = TrackedRepoRepository(self.db)
        try:
            tracked_repo = repo_store.get_by_full_name(repo_full_name)
        except Exception:
            return {"status": "ignored", "reason": f"repo {repo_full_name} not tracked"}

        # Ingest the run
        try:
            from app.services.ingester import LogIngester
            ingester = LogIngester(self.db)
            result = ingester.ingest_run(repo_full_name, github_run_id)
            logger.info(
                "Webhook ingested run %d for %s: %dms",
                github_run_id, repo_full_name, result.total_duration_ms,
            )
        except Exception as e:
            logger.warning("Webhook ingestion failed for run %d: %s", github_run_id, e)
            return {"status": "error", "reason": f"ingestion failed: {e}"}

        # Check threshold and trigger analysis
        threshold = self._settings.SLOW_STEP_THRESHOLD_MS
        response = {
            "status": "ingested",
            "run_id": result.run_id,
            "total_duration_ms": result.total_duration_ms,
        }

        if result.total_duration_ms > threshold:
            try:
                from app.services.ai_engine import AIEngine
                engine = AIEngine(self.db)
                analysis = engine.analyse_run(result.run_id)

                # Try to post PR comment
                self._post_pr_comment(
                    repo_full_name, head_branch, workflow_run, analysis
                )
                response["status"] = "analysed"
                response["analysis_id"] = analysis.id
            except Exception as e:
                logger.warning("Webhook analysis failed: %s", e)
                response["analysis_warning"] = str(e)

        return response

    def _post_pr_comment(
        self, repo_full_name: str, head_branch: str,
        workflow_run: dict, analysis,
    ) -> None:
        """Post a PR comment with the analysis summary."""
        # Find associated PRs
        pull_requests = workflow_run.get("pull_requests", [])
        if not pull_requests:
            logger.info("No PRs associated with run, skipping comment")
            return

        comment_body = self._format_pr_comment(analysis, workflow_run)

        try:
            gh = GitHubClient()
            for pr in pull_requests:
                pr_number = pr.get("number")
                if pr_number:
                    gh.post_pr_comment(repo_full_name, pr_number, comment_body)
                    logger.info("Posted PR comment on #%d", pr_number)
        except Exception as e:
            logger.warning("Failed to post PR comment: %s", e)

    def _format_pr_comment(self, analysis, workflow_run: dict) -> str:
        """Format the PR comment markdown."""
        run_number = workflow_run.get("run_number", "?")
        total_ms = analysis.pipeline_run.total_duration_ms or 0
        target_ms = self._settings.ANALYSIS_TARGET_DURATION_MS
        over_ms = max(0, total_ms - target_ms)

        lines = [
            f"## DynamicAnalyser Report — Run #{run_number}",
            f"> Total duration: **{total_ms / 1000:.1f}s** "
            f"(target: {target_ms / 1000:.0f}s) — "
            f"**{over_ms / 1000:.1f}s over threshold**",
            "",
        ]

        # Bottleneck table
        if analysis.suggestions:
            lines.append("### Top Bottlenecks")
            lines.append("| Step | Saving | Effort |")
            lines.append("|------|--------|--------|")
            for s in sorted(analysis.suggestions, key=lambda x: x.rank):
                saving = f"{s.estimated_saving_ms / 1000:.1f}s"
                lines.append(f"| {s.title} | {saving} | {s.effort} |")
            lines.append("")

        # Root cause
        if analysis.root_cause:
            lines.append("### Root Cause")
            lines.append(analysis.root_cause)
            lines.append("")

        # Suggestions
        if analysis.suggestions:
            lines.append("### Suggestions")
            for s in sorted(analysis.suggestions, key=lambda x: x.rank):
                saving = f"{s.estimated_saving_ms / 1000:.1f}s"
                lines.append(
                    f"{s.rank}. **{s.title}** — estimated saving: {saving} ({s.effort} effort)"
                )
            lines.append("")

        dashboard_url = self._settings.DASHBOARD_URL
        lines.append(f"[View full analysis →]({dashboard_url}/runs/{analysis.pipeline_run_id})")

        return "\n".join(lines)
