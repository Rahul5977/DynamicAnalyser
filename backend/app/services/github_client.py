import io
import zipfile
from dataclasses import dataclass
from datetime import datetime

from github import Github, GithubException, RateLimitExceededException

from app.config import get_settings
from app.core.exceptions import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubRateLimitError,
)
from app.core.logging import logger


@dataclass
class WorkflowRunInfo:
    run_id: int
    run_number: int
    workflow_name: str
    status: str
    conclusion: str | None
    head_branch: str
    head_sha: str
    created_at: datetime


class GitHubClient:
    def __init__(self, token: str | None = None):
        self._token = token or get_settings().GITHUB_TOKEN
        if not self._token:
            raise GitHubAuthError(
                "GitHub token is not configured",
                detail="Set GITHUB_TOKEN in your .env file",
            )
        try:
            self._client = Github(
                self._token, timeout=get_settings().GITHUB_API_TIMEOUT
            )
            # Validate token immediately
            self._client.get_user().login
        except GithubException as e:
            raise GitHubAuthError(
                "GitHub authentication failed",
                detail=f"Status {e.status}: {e.data.get('message', str(e))}",
            ) from e

    def _get_repo(self, repo_full_name: str):
        try:
            return self._client.get_repo(repo_full_name)
        except GithubException as e:
            if e.status == 404:
                raise GitHubNotFoundError(
                    f"Repository '{repo_full_name}' not found",
                    detail="Check the repository name and your token permissions",
                ) from e
            raise self._wrap_exception(e) from e

    def get_workflow_runs(
        self, repo_full_name: str, limit: int = 20
    ) -> list[WorkflowRunInfo]:
        try:
            repo = self._get_repo(repo_full_name)
            runs = repo.get_workflow_runs()
            result = []
            for run in runs[:limit]:
                result.append(
                    WorkflowRunInfo(
                        run_id=run.id,
                        run_number=run.run_number,
                        workflow_name=run.name,
                        status=run.status,
                        conclusion=run.conclusion,
                        head_branch=run.head_branch,
                        head_sha=run.head_sha,
                        created_at=run.created_at,
                    )
                )
            logger.info(
                "Fetched %d workflow runs for %s", len(result), repo_full_name
            )
            return result
        except (GitHubNotFoundError, GitHubAuthError):
            raise
        except RateLimitExceededException as e:
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded",
                detail="Wait before retrying or use a token with higher limits",
            ) from e
        except GithubException as e:
            raise self._wrap_exception(e) from e

    def get_workflow_run_by_id(
        self, repo_full_name: str, run_id: int
    ) -> WorkflowRunInfo:
        """Fetch a single workflow run directly by its GitHub run ID."""
        try:
            repo = self._get_repo(repo_full_name)
            run = repo.get_workflow_run(run_id)
            return WorkflowRunInfo(
                run_id=run.id,
                run_number=run.run_number,
                workflow_name=run.name,
                status=run.status,
                conclusion=run.conclusion,
                head_branch=run.head_branch,
                head_sha=run.head_sha,
                created_at=run.created_at,
            )
        except (GitHubNotFoundError, GitHubAuthError):
            raise
        except RateLimitExceededException as e:
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded",
                detail="Wait before retrying or use a token with higher limits",
            ) from e
        except GithubException as e:
            if e.status == 404:
                raise GitHubNotFoundError(
                    f"Workflow run {run_id} not found in {repo_full_name}",
                    detail="The run may not exist or the run ID may be incorrect",
                ) from e
            raise self._wrap_exception(e) from e

    def get_run_logs(self, repo_full_name: str, run_id: int) -> str:
        try:
            repo = self._get_repo(repo_full_name)
            run = repo.get_workflow_run(run_id)
            logs_url = run.logs_url

            import requests

            headers = {"Authorization": f"token {self._token}"}
            response = requests.get(
                logs_url, headers=headers, timeout=get_settings().GITHUB_API_TIMEOUT
            )
            response.raise_for_status()

            log_texts = []
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                for name in sorted(zf.namelist()):
                    if name.endswith(".txt"):
                        content = zf.read(name).decode("utf-8", errors="replace")
                        log_texts.append(f"=== {name} ===\n{content}")

            combined = "\n".join(log_texts)
            logger.info(
                "Downloaded logs for run %d (%d bytes)", run_id, len(combined)
            )
            return combined

        except (GitHubNotFoundError, GitHubAuthError):
            raise
        except RateLimitExceededException as e:
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded",
                detail="Wait before retrying or use a token with higher limits",
            ) from e
        except zipfile.BadZipFile as e:
            raise GitHubAPIError(
                f"Invalid log archive for run {run_id}",
                detail="The downloaded log file is not a valid zip archive",
            ) from e
        except GithubException as e:
            raise self._wrap_exception(e) from e
        except requests.RequestException as e:
            raise GitHubAPIError(
                f"Failed to download logs for run {run_id}",
                detail=str(e),
            ) from e

    def get_file_contents(
        self, repo_full_name: str, path: str, ref: str | None = None
    ) -> str:
        try:
            repo = self._get_repo(repo_full_name)
            kwargs = {"path": path}
            if ref:
                kwargs["ref"] = ref
            content_file = repo.get_contents(**kwargs)
            if isinstance(content_file, list):
                raise GitHubAPIError(
                    f"Path '{path}' is a directory, not a file",
                    detail="Provide a path to a specific file",
                )
            return content_file.decoded_content.decode("utf-8", errors="replace")
        except (GitHubNotFoundError, GitHubAuthError, GitHubAPIError):
            raise
        except GithubException as e:
            if e.status == 404:
                raise GitHubNotFoundError(
                    f"File '{path}' not found in '{repo_full_name}'",
                    detail=f"ref={ref}" if ref else "default branch",
                ) from e
            raise self._wrap_exception(e) from e

    def list_repos(self) -> list[str]:
        try:
            user = self._client.get_user()
            return [repo.full_name for repo in user.get_repos(sort="updated")]
        except RateLimitExceededException as e:
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded",
                detail="Wait before retrying or use a token with higher limits",
            ) from e
        except GithubException as e:
            raise self._wrap_exception(e) from e

    def post_pr_comment(
        self, repo_full_name: str, pr_number: int, body: str
    ) -> None:
        try:
            repo = self._get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            pr.create_issue_comment(body)
            logger.info(
                "Posted comment on PR #%d in %s", pr_number, repo_full_name
            )
        except (GitHubNotFoundError, GitHubAuthError):
            raise
        except GithubException as e:
            raise self._wrap_exception(e) from e

    def list_tree(self, repo_full_name: str, sha: str) -> list[dict]:
        """Fetch the full file tree for a repo at a given commit SHA.

        Uses the Git Trees API with recursive=True.
        Returns list of dicts with keys: path, type, sha, size (blobs only).
        """
        try:
            repo = self._get_repo(repo_full_name)
            tree = repo.get_git_tree(sha, recursive=True)
            return [
                {
                    "path": item.path,
                    "type": item.type,
                    "sha": item.sha,
                    "size": item.size,
                }
                for item in tree.tree
                if item.type == "blob"
            ]
        except (GitHubNotFoundError, GitHubAuthError):
            raise
        except RateLimitExceededException as e:
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded",
                detail="Wait before retrying or use a token with higher limits",
            ) from e
        except GithubException as e:
            raise self._wrap_exception(e) from e

    @staticmethod
    def _wrap_exception(e: GithubException) -> GitHubAPIError:
        message = e.data.get("message", str(e)) if isinstance(e.data, dict) else str(e)
        return GitHubAPIError(
            f"GitHub API error (HTTP {e.status})",
            detail=message,
        )
