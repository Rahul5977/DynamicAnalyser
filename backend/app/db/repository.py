import json

from sqlalchemy import func, desc, distinct, asc
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import (
    AnalysisNotFoundError,
    DatabaseError,
    RepositoryNotFoundError,
    RunNotFoundError,
)
from app.core.logging import logger
from app.models.database import (
    TrackedRepository,
    PipelineRun,
    StepTiming,
    CodeIndex,
    IndexedFunction,
    IndexedLogCall,
    Analysis,
    AnalysisSuggestion,
    AnalysisFeedback,
    AppLogSession,
)


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
        repo = self.db.get(TrackedRepository, repo_id)
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

    def get_step_durations_for_repo(
        self, repo_id: int, step_name: str, last_n: int = 50
    ) -> list[tuple[int, int]]:
        """Return (run_id, duration_ms) for a step, ordered oldest→newest."""
        try:
            rows = (
                self.db.query(PipelineRun.id, StepTiming.duration_ms)
                .join(StepTiming)
                .filter(
                    PipelineRun.repository_id == repo_id,
                    StepTiming.step_name == step_name,
                )
                .order_by(desc(PipelineRun.created_at))
                .limit(last_n)
                .all()
            )
            # Reverse to oldest→newest for trend analysis
            return list(reversed(rows))
        except Exception as e:
            logger.error("Failed to get step durations: %s", e)
            raise DatabaseError("Failed to get step durations", detail=str(e)) from e

    def get_all_step_names_for_repo(
        self, repo_id: int, last_n: int = 50
    ) -> list[str]:
        """Return distinct step names that appear in the last N runs."""
        try:
            # Get the last N run IDs
            run_ids_subq = (
                self.db.query(PipelineRun.id)
                .filter(PipelineRun.repository_id == repo_id)
                .order_by(desc(PipelineRun.created_at))
                .limit(last_n)
                .subquery()
            )
            rows = (
                self.db.query(distinct(StepTiming.step_name))
                .filter(StepTiming.pipeline_run_id.in_(
                    self.db.query(run_ids_subq.c.id)
                ))
                .all()
            )
            return [r[0] for r in rows]
        except Exception as e:
            logger.error("Failed to get step names: %s", e)
            raise DatabaseError("Failed to get step names", detail=str(e)) from e

    def count_runs_for_repo(self, repo_id: int, last_n: int = 50) -> int:
        """Return the count of distinct pipeline runs in the last N window."""
        try:
            return (
                self.db.query(func.count(PipelineRun.id))
                .filter(PipelineRun.repository_id == repo_id)
                .scalar() or 0
            )
        except Exception as e:
            logger.error("Failed to count runs: %s", e)
            raise DatabaseError("Failed to count runs", detail=str(e)) from e

    def get_latest_total_duration(self, repo_id: int) -> int | None:
        """Return total_duration_ms of the most recent completed run."""
        run = (
            self.db.query(PipelineRun)
            .filter(
                PipelineRun.repository_id == repo_id,
                PipelineRun.total_duration_ms.isnot(None),
            )
            .order_by(desc(PipelineRun.created_at))
            .first()
        )
        return run.total_duration_ms if run else None


class CodeIndexRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_repo_and_sha(self, repo_id: int, commit_sha: str) -> CodeIndex | None:
        return (
            self.db.query(CodeIndex)
            .filter(
                CodeIndex.repository_id == repo_id,
                CodeIndex.commit_sha == commit_sha,
            )
            .first()
        )

    def get_latest_for_repo(self, repo_id: int) -> CodeIndex | None:
        return (
            self.db.query(CodeIndex)
            .filter(
                CodeIndex.repository_id == repo_id,
                CodeIndex.status == "completed",
            )
            .order_by(desc(CodeIndex.created_at))
            .first()
        )

    def create(self, code_index: CodeIndex) -> CodeIndex:
        try:
            self.db.add(code_index)
            self.db.commit()
            self.db.refresh(code_index)
            return code_index
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to create code index: %s", e)
            raise DatabaseError("Failed to create code index", detail=str(e)) from e

    def update_status(
        self, index_id: int, status: str, error_message: str | None = None,
        completed_at=None, total_functions: int = 0, total_log_calls: int = 0,
        language_breakdown: dict | None = None,
    ):
        try:
            idx = self.db.get(CodeIndex, index_id)
            if idx:
                idx.status = status
                idx.error_message = error_message
                idx.completed_at = completed_at
                idx.total_functions = total_functions
                idx.total_log_calls = total_log_calls
                if language_breakdown:
                    idx.language_breakdown = json.dumps(language_breakdown)
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to update code index status: %s", e)
            raise DatabaseError("Failed to update code index", detail=str(e)) from e

    def save_functions_and_log_calls(
        self, index_id: int,
        functions: list[IndexedFunction],
        log_calls: list[IndexedLogCall],
    ):
        try:
            for f in functions:
                f.code_index_id = index_id
                self.db.add(f)
            for lc in log_calls:
                lc.code_index_id = index_id
                self.db.add(lc)
            self.db.commit()
            logger.info(
                "Saved %d functions and %d log calls for index %d",
                len(functions), len(log_calls), index_id,
            )
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to save index data: %s", e)
            raise DatabaseError("Failed to save index data", detail=str(e)) from e

    def load_index_data(self, code_index: CodeIndex):
        """Load functions and log_calls for a CodeIndex (eager)."""
        _ = code_index.functions
        _ = code_index.log_calls
        return code_index


class AnalysisRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, analysis_id: int) -> Analysis:
        analysis = (
            self.db.query(Analysis)
            .options(joinedload(Analysis.suggestions))
            .filter(Analysis.id == analysis_id)
            .first()
        )
        if not analysis:
            raise AnalysisNotFoundError(
                f"Analysis with id={analysis_id} not found"
            )
        return analysis

    def get_latest_for_run(self, run_id: int) -> Analysis | None:
        return (
            self.db.query(Analysis)
            .options(joinedload(Analysis.suggestions))
            .filter(
                Analysis.pipeline_run_id == run_id,
                Analysis.status == "completed",
            )
            .order_by(desc(Analysis.created_at))
            .first()
        )

    def get_all_for_repo(self, repo_id: int) -> list[Analysis]:
        return (
            self.db.query(Analysis)
            .options(joinedload(Analysis.suggestions))
            .filter(
                Analysis.repository_id == repo_id,
                Analysis.status == "completed",
            )
            .order_by(desc(Analysis.created_at))
            .all()
        )

    def create(self, analysis: Analysis) -> Analysis:
        try:
            self.db.add(analysis)
            self.db.commit()
            self.db.refresh(analysis)
            return analysis
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to create analysis: %s", e)
            raise DatabaseError("Failed to create analysis", detail=str(e)) from e

    def update_completed(
        self, analysis_id: int, root_cause: str, primary_bottleneck: str,
        anti_patterns_json: str, estimated_total_saving_ms: int,
        raw_llm_response: str, llm_model: str,
        llm_prompt_tokens: int, llm_completion_tokens: int,
        completed_at, suggestions: list[AnalysisSuggestion],
    ):
        try:
            a = self.db.get(Analysis, analysis_id)
            if not a:
                return
            a.status = "completed"
            a.root_cause = root_cause
            a.primary_bottleneck = primary_bottleneck
            a.anti_patterns_json = anti_patterns_json
            a.estimated_total_saving_ms = estimated_total_saving_ms
            a.raw_llm_response = raw_llm_response
            a.llm_model = llm_model
            a.llm_prompt_tokens = llm_prompt_tokens
            a.llm_completion_tokens = llm_completion_tokens
            a.completed_at = completed_at
            for s in suggestions:
                s.analysis_id = analysis_id
                self.db.add(s)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to update analysis: %s", e)
            raise DatabaseError("Failed to update analysis", detail=str(e)) from e

    def update_failed(self, analysis_id: int, error_message: str):
        try:
            a = self.db.get(Analysis, analysis_id)
            if a:
                a.status = "failed"
                a.error_message = error_message
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to mark analysis as failed: %s", e)

    def add_feedback(self, feedback: AnalysisFeedback) -> AnalysisFeedback:
        try:
            self.db.add(feedback)
            self.db.commit()
            self.db.refresh(feedback)
            return feedback
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to save feedback: %s", e)
            raise DatabaseError("Failed to save feedback", detail=str(e)) from e

    def get_feedback_summary(self, repo_id: int, limit: int = 15) -> list[dict]:
        """
        Return recent developer feedback for a repository, joined with the
        suggestion and analysis it belongs to.

        Each entry has keys:
          verdict, suggestion_title, anti_pattern, estimated_saving_ms, comment
        """
        rows = (
            self.db.query(
                AnalysisFeedback.verdict,
                AnalysisFeedback.comment,
                AnalysisSuggestion.title,
                AnalysisSuggestion.anti_pattern,
                AnalysisSuggestion.estimated_saving_ms,
            )
            .join(AnalysisSuggestion, AnalysisFeedback.suggestion_id == AnalysisSuggestion.id)
            .join(Analysis, AnalysisFeedback.analysis_id == Analysis.id)
            .filter(Analysis.repository_id == repo_id)
            .order_by(desc(AnalysisFeedback.created_at))
            .limit(limit)
            .all()
        )
        return [
            {
                "verdict": r.verdict,
                "suggestion_title": r.title,
                "anti_pattern": r.anti_pattern or "",
                "estimated_saving_ms": r.estimated_saving_ms,
                "comment": r.comment or "",
            }
            for r in rows
        ]

    def count_past_anti_pattern(self, repo_id: int, anti_pattern: str) -> int:
        """Count how many past analyses flagged a given anti-pattern."""
        rows = (
            self.db.query(Analysis.anti_patterns_json)
            .filter(
                Analysis.repository_id == repo_id,
                Analysis.status == "completed",
                Analysis.anti_patterns_json.isnot(None),
            )
            .all()
        )
        count = 0
        for (ap_json,) in rows:
            try:
                patterns = json.loads(ap_json)
                if anti_pattern in patterns:
                    count += 1
            except (json.JSONDecodeError, TypeError):
                continue
        return count

    def get_feedback_summary_for_app(self, app_name: str, limit: int = 15) -> list[dict]:
        rows = (
            self.db.query(
                AnalysisFeedback.verdict,
                AnalysisFeedback.comment,
                AnalysisSuggestion.title,
                AnalysisSuggestion.anti_pattern,
                AnalysisSuggestion.estimated_saving_ms,
            )
            .join(AnalysisSuggestion, AnalysisFeedback.suggestion_id == AnalysisSuggestion.id)
            .join(Analysis, AnalysisFeedback.analysis_id == Analysis.id)
            .join(AppLogSession, Analysis.app_log_session_id == AppLogSession.id)
            .filter(AppLogSession.app_name == app_name)
            .order_by(desc(AnalysisFeedback.created_at))
            .limit(limit)
            .all()
        )
        return [
            {
                "verdict": r.verdict,
                "suggestion_title": r.title,
                "anti_pattern": r.anti_pattern or "",
                "estimated_saving_ms": r.estimated_saving_ms,
                "comment": r.comment or "",
            }
            for r in rows
        ]
