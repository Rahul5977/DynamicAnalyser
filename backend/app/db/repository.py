from sqlalchemy import func, desc
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import (
    DatabaseError,
    RepositoryNotFoundError,
    RunNotFoundError,
)
from app.core.logging import logger
from app.models.database import TrackedRepository, PipelineRun, StepTiming


class TrackedRepoRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self, active_only: bool = True) -> list[TrackedRepository]:
        try:
            query = self.db.query(TrackedRepository)
            if active_only:
                query = query.filter(TrackedRepository.is_active.is_(True))
            return query.order_by(TrackedRepository.full_name).all()
        except Exception as e:
            logger.error("Failed to list repositories: %s", e)
            raise DatabaseError("Failed to list repositories", detail=str(e)) from e

    def get_by_full_name(self, full_name: str) -> TrackedRepository:
        repo = (
            self.db.query(TrackedRepository)
            .filter(TrackedRepository.full_name == full_name)
            .first()
        )
        if not repo:
            raise RepositoryNotFoundError(
                f"Repository '{full_name}' is not tracked",
                detail="Add it first via POST /api/repos",
            )
        return repo

    def get_by_id(self, repo_id: int) -> TrackedRepository:
        repo = self.db.query(TrackedRepository).get(repo_id)
        if not repo:
            raise RepositoryNotFoundError(f"Repository with id={repo_id} not found")
        return repo

    def create(self, full_name: str) -> TrackedRepository:
        try:
            parts = full_name.split("/", 1)
            repo = TrackedRepository(
                full_name=full_name, owner=parts[0], name=parts[1]
            )
            self.db.add(repo)
            self.db.commit()
            self.db.refresh(repo)
            logger.info("Tracked new repository: %s", full_name)
            return repo
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to create tracked repo %s: %s", full_name, e)
            raise DatabaseError(
                f"Failed to track repository '{full_name}'", detail=str(e)
            ) from e

    def exists(self, full_name: str) -> bool:
        return (
            self.db.query(TrackedRepository)
            .filter(TrackedRepository.full_name == full_name)
            .first()
            is not None
        )


class PipelineRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, run_id: int) -> PipelineRun:
        run = (
            self.db.query(PipelineRun)
            .options(joinedload(PipelineRun.step_timings))
            .filter(PipelineRun.id == run_id)
            .first()
        )
        if not run:
            raise RunNotFoundError(f"Pipeline run with id={run_id} not found")
        return run

    def get_by_github_run_id(
        self, repo_id: int, github_run_id: int
    ) -> PipelineRun | None:
        return (
            self.db.query(PipelineRun)
            .filter(
                PipelineRun.repository_id == repo_id,
                PipelineRun.github_run_id == github_run_id,
            )
            .first()
        )

    def list_by_repo(
        self, repo_id: int, page: int = 1, page_size: int = 20
    ) -> tuple[list[PipelineRun], int]:
        try:
            query = self.db.query(PipelineRun).filter(
                PipelineRun.repository_id == repo_id
            )
            total = query.count()
            runs = (
                query.order_by(desc(PipelineRun.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return runs, total
        except Exception as e:
            logger.error("Failed to list runs for repo %d: %s", repo_id, e)
            raise DatabaseError("Failed to list pipeline runs", detail=str(e)) from e

    def create_with_steps(
        self, run: PipelineRun, steps: list[StepTiming]
    ) -> PipelineRun:
        try:
            self.db.add(run)
            self.db.flush()
            for step in steps:
                step.pipeline_run_id = run.id
                self.db.add(step)
            self.db.commit()
            self.db.refresh(run)
            logger.info(
                "Saved pipeline run #%d with %d steps", run.run_number, len(steps)
            )
            return run
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to save pipeline run: %s", e)
            raise DatabaseError(
                "Failed to save pipeline run", detail=str(e)
            ) from e

    def get_step_p95_duration(
        self, repo_id: int, step_name: str, last_n: int = 50
    ) -> int | None:
        """Get p95 duration for a step across last N runs of a repo."""
        try:
            subquery = (
                self.db.query(StepTiming.duration_ms)
                .join(PipelineRun)
                .filter(
                    PipelineRun.repository_id == repo_id,
                    StepTiming.step_name == step_name,
                )
                .order_by(desc(PipelineRun.created_at))
                .limit(last_n)
                .subquery()
            )
            result = self.db.query(
                func.percentile_cont(0.95)
                .within_group(subquery.c.duration_ms)
            ).scalar()
            return int(result) if result else None
        except Exception:
            # percentile_cont not available on SQLite; fall back to approximation
            rows = (
                self.db.query(StepTiming.duration_ms)
                .join(PipelineRun)
                .filter(
                    PipelineRun.repository_id == repo_id,
                    StepTiming.step_name == step_name,
                )
                .order_by(desc(PipelineRun.created_at))
                .limit(last_n)
                .all()
            )
            if not rows:
                return None
            durations = sorted(r[0] for r in rows)
            idx = int(len(durations) * 0.95)
            return durations[min(idx, len(durations) - 1)]
