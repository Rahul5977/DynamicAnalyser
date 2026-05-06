"""Validate local git clone paths and read HEAD for indexing."""

import os
import subprocess

from app.config import get_settings
from app.core.exceptions import LocalRepoPathError


def resolve_local_repo_path(user_path: str) -> str:
    """
    Return realpath to an existing directory that lies under AST_INDEX_LOCAL_ROOT.

    Raises LocalRepoPathError if local indexing is disabled or the path is unsafe.
    """
    settings = get_settings()
    root = (settings.AST_INDEX_LOCAL_ROOT or "").strip()
    if not root:
        raise LocalRepoPathError(
            "Local repository indexing is disabled",
            detail="Set AST_INDEX_LOCAL_ROOT in the environment to an absolute "
            "directory; only clones inside that directory may be indexed.",
        )

    expanded = os.path.expanduser(user_path.strip())
    if not expanded:
        raise LocalRepoPathError("local_repo_path is empty", detail=None)

    abs_path = os.path.realpath(os.path.abspath(expanded))
    root_real = os.path.realpath(os.path.abspath(os.path.expanduser(root)))

    try:
        common = os.path.commonpath([abs_path, root_real])
    except ValueError:
        raise LocalRepoPathError(
            "Invalid local repository path",
            detail="Path could not be compared to AST_INDEX_LOCAL_ROOT.",
        ) from None

    if common != root_real:
        raise LocalRepoPathError(
            "Local repository path is not under AST_INDEX_LOCAL_ROOT",
            detail=f"Resolved clone: {abs_path}; allowed root: {root_real}",
        )

    if not os.path.isdir(abs_path):
        raise LocalRepoPathError(
            "Local repository path is not a directory",
            detail=abs_path,
        )

    return abs_path


def git_head_sha(repo_dir: str) -> str:
    """Return full SHA for HEAD in a local git working tree."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LocalRepoPathError(
            "Failed to run git rev-parse",
            detail=str(e),
        ) from e

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise LocalRepoPathError(
            "Directory is not a git clone or git rev-parse failed",
            detail=err[:500],
        )

    sha = proc.stdout.strip()
    if len(sha) < 7:
        raise LocalRepoPathError("git rev-parse returned an invalid SHA", detail=sha)
    return sha
