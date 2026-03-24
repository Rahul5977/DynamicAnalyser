from sqlalchemy.orm import Session

from app.core.exceptions import IngestionError, RunNotFoundError
from app.core.logging import logger
from app.db.repository import PipelineRunRepository, TrackedRepoRepository
from app.models.database import PipelineRun, StepTiming
from app.models.schemas import IngestionResult
from app.services.github_client import GitHubClient
from app.services.log_parser import parse_logs


class LogIngester:
    """Orchestrates the full ingestion pipeline: fetch logs -> parse -> store."""

    def __init__(self, db: Session, github_client: GitHubClient | None = None):
        self.db = db
        self.github_client = github_client or GitHubClient()
        self.repo_store = TrackedRepoRepository(db)
        self.run_store = PipelineRunRepository(db)

    def ingest_run(self, repo_full_name: str, github_run_id: int) -> IngestionResult:
        """Full ingestion pipeline for a single workflow run."""
        logger.info(
            "Starting ingestion for %s run %d", repo_full_name, github_run_id
        )

        # 1. Ensure repository is tracked
        tracked_repo = self.repo_store.get_by_full_name(repo_full_name)

        # 2. Check for duplicate ingestion
        existing = self.run_store.get_by_github_run_id(
            tracked_repo.id, github_run_id
        )
        if existing:
            raise IngestionError(
                f"Run {github_run_id} has already been ingested",
                detail=f"Existing run id={existing.id}",
            )

        # 3. Fetch run metadata directly by GitHub run ID
        try:
            run_info = self.github_client.get_workflow_run_by_id(
                repo_full_name, github_run_id
            )
        except Exception as e:
            raise IngestionError(
                f"Failed to fetch run metadata for {github_run_id}",
                detail=str(e),
            ) from e

        # 4. Download and parse logs
        try:
            raw_logs = self.github_client.get_run_logs(
                repo_full_name, github_run_id
            )
        except Exception as e:
            raise IngestionError(
                f"Failed to download logs for run {github_run_id}",
                detail=str(e),
            ) from e

        try:
            parsed_steps = parse_logs(raw_logs)
        except Exception as e:
            raise IngestionError(
                f"Failed to parse logs for run {github_run_id}",
                detail=str(e),
            ) from e

        # 5. Build ORM objects
        total_duration_ms = sum(s.duration_ms for s in parsed_steps)

        pipeline_run = PipelineRun(
            repository_id=tracked_repo.id,
            github_run_id=github_run_id,
            run_number=run_info.run_number,
            workflow_name=run_info.workflow_name,
            status=run_info.status,
            conclusion=run_info.conclusion,
            head_branch=run_info.head_branch,
            head_sha=run_info.head_sha,
            total_duration_ms=total_duration_ms,
            created_at=run_info.created_at,
        )

        step_timings = [
            StepTiming(
                step_name=s.step_name,
                step_number=s.step_number,
                duration_ms=s.duration_ms,
                started_at=s.started_at,
                ended_at=s.ended_at,
                status=s.status,
                annotation=s.annotation,
                log_excerpt=s.log_excerpt,
            )
            for s in parsed_steps
        ]

        # 6. Persist in a single transaction
        saved_run = self.run_store.create_with_steps(pipeline_run, step_timings)

        # 7. Build result
        slowest = max(parsed_steps, key=lambda s: s.duration_ms)
        result = IngestionResult(
            run_id=saved_run.id,
            github_run_id=github_run_id,
            steps_parsed=len(step_timings),
            total_duration_ms=total_duration_ms,
            slowest_step=slowest.step_name,
            slowest_step_ms=slowest.duration_ms,
        )

        logger.info(
            "Ingestion complete for run %d: %d steps, total %dms, slowest=%s (%dms)",
            github_run_id,
            result.steps_parsed,
            result.total_duration_ms,
            result.slowest_step,
            result.slowest_step_ms,
        )
        return result
