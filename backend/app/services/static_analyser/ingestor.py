from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from app.config import get_settings

TARGET_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx"}
RISKY_DEPENDENCY_MARKERS = {
    "event-stream",
    "left-pad",
    "request",
    "node-serialize",
    "serialize-javascript",
    "pyyaml",
    "pickle",
}


def _discover_language(files: list[str]) -> str:
    counts: dict[str, int] = {}
    for path in files:
        ext = Path(path).suffix.lower()
        key = ext.lstrip(".")
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda x: x[1])[0]


def _dependency_risks(root: Path) -> list[str]:
    risks: list[str] = []
    package_json = root / "package.json"
    requirements = root / "requirements.txt"
    if package_json.exists():
        text = package_json.read_text(encoding="utf-8", errors="ignore").lower()
        for marker in RISKY_DEPENDENCY_MARKERS:
            if marker in text:
                risks.append(f"package:{marker}")
    if requirements.exists():
        text = requirements.read_text(encoding="utf-8", errors="ignore").lower()
        for marker in RISKY_DEPENDENCY_MARKERS:
            if marker in text:
                risks.append(f"python:{marker}")
    return sorted(set(risks))


def ingest_repository(repo_url: str) -> dict:
    settings = get_settings()
    job_id = str(uuid4())
    temp_root = Path(settings.STATIC_ANALYSIS_TEMP_DIR).resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    clone_path = temp_root / job_id

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(clone_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )

    target_files: list[str] = []
    for path in clone_path.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        if path.suffix.lower() in TARGET_EXTENSIONS:
            target_files.append(str(path.relative_to(clone_path)))

    return {
        "repo_url": repo_url,
        "job_id": job_id,
        "local_path": str(clone_path),
        "target_files": target_files[: settings.STATIC_ANALYSIS_MAX_FILES],
        "primary_language": _discover_language(target_files),
        "dependency_risks": _dependency_risks(clone_path),
    }


def cleanup_repository(local_path: str) -> None:
    try:
        shutil.rmtree(local_path, ignore_errors=True)
    except Exception:
        pass
