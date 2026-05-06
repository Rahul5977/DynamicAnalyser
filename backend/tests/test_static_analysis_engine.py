"""Unit tests for static analysis helpers."""

from app.services.static_analysis_engine import (
    classify_domain,
    resolve_github_target,
)


def test_classify_domain_frontend_extension():
    assert classify_domain("src/App.tsx") == "frontend"


def test_classify_domain_database():
    assert classify_domain("backend/prisma/schema.prisma") == "database"


def test_resolve_github_target_full_name():
    assert resolve_github_target(None, "octo/Hello") == "octo/Hello"


def test_resolve_github_target_url():
    assert (
        resolve_github_target("https://github.com/octo/World", None) == "octo/World"
    )
