"""Detect what kind of project a workspace contains.

Scope for Batch 31: Python only. Detector still returns the right
`Language` label for JS/Go/Rust so the runner can emit a useful
"unsupported language" message, but it doesn't try to run anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.agents.test_runner.schemas import Language

# Files that mark a Python project, in rough priority order.
_PYTHON_MARKERS: tuple[str, ...] = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "tox.ini",
)
_JS_MARKERS: tuple[str, ...] = ("package.json",)
_GO_MARKERS: tuple[str, ...] = ("go.mod",)
_RUST_MARKERS: tuple[str, ...] = ("Cargo.toml",)


@dataclass(frozen=True)
class ProjectInfo:
    """What `detect_project` finds.

    `subdir` is the path *relative to repo_path* where the project lives —
    usually "" (repo root). Set to e.g. "backend" when a monorepo has the
    Python project in a sub-directory. We don't dig deeper than one level.
    """
    language: Language
    subdir: str
    marker: str | None  # which file we matched, or None for "unknown"


def detect_project(repo_path: Path) -> ProjectInfo:
    """Look in `repo_path` and (one level down) for a project marker."""
    if not repo_path.is_dir():
        return ProjectInfo(language="unknown", subdir="", marker=None)

    # Pass 1: root.
    found = _first_marker(repo_path)
    if found:
        return ProjectInfo(language=found[0], subdir="", marker=found[1])

    # Pass 2: each immediate child directory. Helps for monorepos like
    # `apache/airflow/airflow-core/` or `<repo>/<project>/pyproject.toml`.
    # We don't recurse further to avoid scoring on docs/examples that
    # have their own pyproject.toml.
    for child in sorted(repo_path.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in (
            "node_modules", "vendor", "venv", "tests", "docs", "examples",
        ):
            continue
        found = _first_marker(child)
        if found:
            return ProjectInfo(
                language=found[0], subdir=child.name, marker=found[1],
            )

    return ProjectInfo(language="unknown", subdir="", marker=None)


def _first_marker(directory: Path) -> tuple[Language, str] | None:
    """Return (language, marker_filename) for the first match, else None."""
    for marker in _PYTHON_MARKERS:
        if (directory / marker).is_file():
            return "python", marker
    for marker in _JS_MARKERS:
        if (directory / marker).is_file():
            return "javascript", marker
    for marker in _GO_MARKERS:
        if (directory / marker).is_file():
            return "go", marker
    for marker in _RUST_MARKERS:
        if (directory / marker).is_file():
            return "rust", marker
    return None
