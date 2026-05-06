import os
import subprocess

import pytest

from app.core.local_repo import git_head_sha, resolve_local_repo_path
from app.core.exceptions import LocalRepoPathError


def test_resolve_disabled_when_root_empty(monkeypatch):
    monkeypatch.setenv("AST_INDEX_LOCAL_ROOT", "")
    # Reload settings cache if needed — get_settings is lru_cached
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(LocalRepoPathError, match="disabled"):
            resolve_local_repo_path("/tmp/foo")
    finally:
        get_settings.cache_clear()


def test_resolve_rejects_escape(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("AST_INDEX_LOCAL_ROOT", str(allowed))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(LocalRepoPathError, match="not under"):
            resolve_local_repo_path(str(outside))
    finally:
        get_settings.cache_clear()


def test_resolve_accepts_nested_clone(monkeypatch, tmp_path):
    allowed = tmp_path / "src"
    allowed.mkdir()
    clone = allowed / "myrepo"
    clone.mkdir()
    init = subprocess.run(
        ["git", "init"],
        cwd=clone,
        capture_output=True,
        text=True,
    )
    if init.returncode != 0:
        pytest.skip(f"git init unavailable: {init.stderr or init.stdout}")
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=clone,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=clone,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=clone,
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("AST_INDEX_LOCAL_ROOT", str(allowed))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        got = resolve_local_repo_path(str(clone))
        assert os.path.samefile(got, clone)
        sha = git_head_sha(got)
        assert len(sha) >= 40
    finally:
        get_settings.cache_clear()
