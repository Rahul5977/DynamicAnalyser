"""Demo data seeder: generates realistic pipeline runs for demos."""

import json
import random
import datetime

from sqlalchemy.orm import Session

from app.config import get_settings
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
)


class DemoSeeder:
    """Seeds the database with realistic demo data."""

    REPO_NAME = "demo-org/sample-api"
    STEP_CONFIGS = [
        ("Checkout", 800, 200, "stable"),
        ("Install dependencies", 4500, 800, "increasing"),
        ("Run migrations", 3200, 600, "increasing"),
        ("Run tests", 5000, 1000, "stable"),
        ("Build Docker image", 2800, 400, "stable"),
        ("Deploy to staging", 1500, 300, "stable"),
    ]
    ANTI_PATTERNS = [
        "No dependency caching",
        "Sequential test execution",
        "Unindexed DB queries",
    ]

    def __init__(self, db: Session):
        self.db = db

    def seed(self) -> dict:
        """Seed the database and return counts."""
        # Create repo
        repo = self._get_or_create_repo()
        runs = self._create_runs(repo, count=20)
        code_idx = self._create_code_index(repo)
        analyses = self._create_analyses(repo, runs)

        return {
            "repos_created": 1,
            "runs_created": len(runs),
            "analyses_created": len(analyses),
        }

    def _get_or_create_repo(self) -> TrackedRepository:
        existing = (
            self.db.query(TrackedRepository)
            .filter(TrackedRepository.full_name == self.REPO_NAME)
            .first()
        )
        if existing:
            return existing

        repo = TrackedRepository(
            full_name=self.REPO_NAME,
            owner="demo-org",
            name="sample-api",
            default_branch="main",
        )
        self.db.add(repo)
        self.db.flush()
        return repo

    def _create_runs(self, repo: TrackedRepository, count: int) -> list[PipelineRun]:
        # Check if runs already exist for this repo
        existing = (
            self.db.query(PipelineRun)
            .filter(PipelineRun.repository_id == repo.id)
            .order_by(PipelineRun.created_at)
            .all()
        )
        if existing:
            return existing

        runs = []
        base_time = datetime.datetime(2024, 3, 1, 8, 0, 0)

        for i in range(count):
            # Generate step durations with realistic variation
            steps_data = []
            total = 0
            for step_name, base_dur, variance, trend in self.STEP_CONFIGS:
                # Apply trend
                if trend == "increasing":
                    drift = int(i * (base_dur * 0.02))  # 2% increase per run
                else:
                    drift = 0
                dur = max(100, base_dur + drift + random.randint(-variance, variance))
                total += dur
                steps_data.append((step_name, dur))

            sha = f"demo{i:04d}{'abcdef0123456789'[i % 16] * 8}"
            run = PipelineRun(
                repository_id=repo.id,
                github_run_id=10000 + i,
                run_number=i + 1,
                workflow_name="CI/CD Pipeline",
                status="completed",
                conclusion="success" if random.random() > 0.1 else "failure",
                head_branch="main" if i % 3 != 0 else f"feature/task-{i}",
                head_sha=sha[:16],
                total_duration_ms=total,
                created_at=base_time + datetime.timedelta(hours=i * 4),
            )
            self.db.add(run)
            self.db.flush()

            for step_num, (step_name, dur) in enumerate(steps_data, 1):
                self.db.add(StepTiming(
                    pipeline_run_id=run.id,
                    step_name=step_name,
                    step_number=step_num,
                    duration_ms=dur,
                    status="success",
                    log_excerpt=f"Running {step_name.lower()}...",
                ))

            runs.append(run)

        self.db.commit()
        return runs

    def _create_code_index(self, repo: TrackedRepository) -> CodeIndex:
        existing = (
            self.db.query(CodeIndex)
            .filter(CodeIndex.repository_id == repo.id, CodeIndex.status == "completed")
            .first()
        )
        if existing:
            return existing

        code_idx = CodeIndex(
            repository_id=repo.id,
            commit_sha="demo0019abcdef01",
            status="completed",
            total_functions=8,
            total_log_calls=5,
            language_breakdown=json.dumps({"py": 6, "js": 2}),
            completed_at=datetime.datetime.utcnow(),
        )
        self.db.add(code_idx)
        self.db.flush()

        functions = [
            ("install_deps", "build.install_deps", "build/setup.py", 10, 25, "py"),
            ("run_migrations", "db.run_migrations", "db/migrate.py", 5, 30, "py"),
            ("execute_sql", "db.execute_sql", "db/migrate.py", 32, 45, "py"),
            ("run_test_suite", "tests.run_test_suite", "tests/runner.py", 8, 40, "py"),
            ("build_image", "docker.build_image", "docker/build.py", 5, 20, "py"),
            ("deploy_staging", "deploy.deploy_staging", "deploy/staging.py", 10, 35, "py"),
            ("installPackages", "build.installPackages", "src/build.js", 3, 15, "js"),
            ("runLinter", "lint.runLinter", "src/lint.js", 5, 20, "js"),
        ]
        for name, qname, fp, ln, eln, lang in functions:
            self.db.add(IndexedFunction(
                code_index_id=code_idx.id,
                function_name=name,
                qualified_name=qname,
                file_path=fp,
                line_number=ln,
                end_line_number=eln,
                language=lang,
            ))

        log_calls = [
            ("Installing dependencies", "build/setup.py", 12, "install_deps", "info", "py"),
            ("Running database migrations", "db/migrate.py", 8, "run_migrations", "warning", "py"),
            ("Executing SQL statements", "db/migrate.py", 35, "execute_sql", "info", "py"),
            ("Starting test suite", "tests/runner.py", 10, "run_test_suite", "info", "py"),
            ("Building Docker image", "docker/build.py", 8, "build_image", "info", "py"),
        ]
        for log_str, fp, ln, fn, level, lang in log_calls:
            self.db.add(IndexedLogCall(
                code_index_id=code_idx.id,
                log_string=log_str,
                file_path=fp,
                line_number=ln,
                function_name=fn,
                log_level=level,
                language=lang,
            ))

        self.db.commit()
        return code_idx

    def _create_analyses(
        self, repo: TrackedRepository, runs: list[PipelineRun]
    ) -> list[Analysis]:
        """Create pre-computed analyses for the last 3 runs."""
        existing = (
            self.db.query(Analysis)
            .filter(Analysis.repository_id == repo.id, Analysis.status == "completed")
            .all()
        )
        if existing:
            return existing

        analyses = []
        analysis_templates = [
            {
                "root_cause": "The Install dependencies step lacks pip/npm caching, causing full re-downloads on every run. Combined with unindexed database queries in the migration step, the pipeline consistently exceeds the 15s target.",
                "primary_bottleneck": "install_deps",
                "anti_patterns": ["No dependency caching", "Unindexed DB queries"],
                "suggestions": [
                    ("Add pip cache to CI workflow", "Configure GitHub Actions cache for pip packages to avoid re-downloading on every run.", "install_deps", "build/setup.py", 3500, "low", "No dependency caching"),
                    ("Add database index for migrations", "The run_migrations function executes queries on non-indexed columns. Add a migration to create indexes.", "run_migrations", "db/migrate.py", 2000, "medium", "Unindexed DB queries"),
                    ("Parallelize test execution", "Run pytest with -n auto to distribute tests across CPU cores.", "run_test_suite", "tests/runner.py", 1800, "low", "Sequential test execution"),
                ],
                "total_saving": 7300,
            },
            {
                "root_cause": "Sequential test execution is the primary bottleneck. The test suite runs single-threaded, and combined with increasing migration times from new ALTER TABLE statements, the pipeline is degrading over time.",
                "primary_bottleneck": "run_test_suite",
                "anti_patterns": ["Sequential test execution", "Unindexed DB queries"],
                "suggestions": [
                    ("Use pytest-xdist for parallel tests", "Install pytest-xdist and run with -n auto flag.", "run_test_suite", "tests/runner.py", 3000, "low", "Sequential test execution"),
                    ("Optimize migration SQL queries", "Add composite index on frequently queried columns.", "execute_sql", "db/migrate.py", 1500, "medium", "Unindexed DB queries"),
                ],
                "total_saving": 4500,
            },
            {
                "root_cause": "Dependency installation without caching remains the top bottleneck. The Docker build step also lacks layer caching, rebuilding from scratch each time.",
                "primary_bottleneck": "install_deps",
                "anti_patterns": ["No dependency caching", "No build cache"],
                "suggestions": [
                    ("Enable npm/pip cache in workflow", "Add cache: action with package-lock/requirements hash.", "install_deps", "build/setup.py", 4000, "low", "No dependency caching"),
                    ("Add Docker layer caching", "Use docker/build-push-action with cache-from/cache-to.", "build_image", "docker/build.py", 1800, "medium", "No build cache"),
                ],
                "total_saving": 5800,
            },
        ]

        for idx, run in enumerate(runs[-3:]):
            template = analysis_templates[idx % len(analysis_templates)]

            a = Analysis(
                pipeline_run_id=run.id,
                repository_id=repo.id,
                status="completed",
                root_cause=template["root_cause"],
                primary_bottleneck=template["primary_bottleneck"],
                anti_patterns_json=json.dumps(template["anti_patterns"]),
                estimated_total_saving_ms=template["total_saving"],
                llm_model=get_settings().LLM_MODEL,
                completed_at=run.created_at + datetime.timedelta(minutes=1),
            )
            self.db.add(a)
            self.db.flush()

            for rank, (title, desc, func, fpath, saving, effort, pattern) in enumerate(
                template["suggestions"], 1
            ):
                self.db.add(AnalysisSuggestion(
                    analysis_id=a.id,
                    rank=rank,
                    title=title,
                    description=desc,
                    target_function=func,
                    target_file=fpath,
                    estimated_saving_ms=saving,
                    effort=effort,
                    diff_hint=f"Before: standard {func}()\nAfter: optimized {func}()",
                    confidence_score=round(0.6 + random.random() * 0.3, 2),
                    anti_pattern=pattern,
                ))

            analyses.append(a)

        self.db.commit()
        return analyses
