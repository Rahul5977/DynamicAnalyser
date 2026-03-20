from fastapi import HTTPException, status


class DynamicAnalyserError(Exception):
    """Base exception for DynamicAnalyser."""

    def __init__(self, message: str, detail: str | None = None):
        self.message = message
        self.detail = detail
        super().__init__(self.message)


class GitHubAPIError(DynamicAnalyserError):
    """Raised when a GitHub API call fails."""


class GitHubAuthError(GitHubAPIError):
    """Raised when GitHub authentication fails."""


class GitHubRateLimitError(GitHubAPIError):
    """Raised when GitHub rate limit is exceeded."""


class GitHubNotFoundError(GitHubAPIError):
    """Raised when a GitHub resource is not found."""


class LogParseError(DynamicAnalyserError):
    """Raised when log parsing fails."""


class LogFormatError(LogParseError):
    """Raised when log format is unrecognised."""


class IngestionError(DynamicAnalyserError):
    """Raised when the ingestion pipeline fails."""


class DatabaseError(DynamicAnalyserError):
    """Raised when a database operation fails."""


class RepositoryNotFoundError(DynamicAnalyserError):
    """Raised when a tracked repository is not found."""


class RunNotFoundError(DynamicAnalyserError):
    """Raised when a pipeline run is not found."""


def to_http_exception(error: DynamicAnalyserError) -> HTTPException:
    """Map domain exceptions to HTTP exceptions."""
    status_map = {
        GitHubAuthError: status.HTTP_401_UNAUTHORIZED,
        GitHubRateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,
        GitHubNotFoundError: status.HTTP_404_NOT_FOUND,
        GitHubAPIError: status.HTTP_502_BAD_GATEWAY,
        LogParseError: status.HTTP_422_UNPROCESSABLE_ENTITY,
        LogFormatError: status.HTTP_422_UNPROCESSABLE_ENTITY,
        IngestionError: status.HTTP_500_INTERNAL_SERVER_ERROR,
        DatabaseError: status.HTTP_500_INTERNAL_SERVER_ERROR,
        RepositoryNotFoundError: status.HTTP_404_NOT_FOUND,
        RunNotFoundError: status.HTTP_404_NOT_FOUND,
    }
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    for exc_type, code in status_map.items():
        if isinstance(error, exc_type):
            status_code = code
            break
    return HTTPException(
        status_code=status_code,
        detail={"error": error.message, "detail": error.detail},
    )
