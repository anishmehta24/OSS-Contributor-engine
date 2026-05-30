"""Project-type detector tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.test_runner.detector import detect_project


def _touch(p: Path, contents: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contents, encoding="utf-8")


@pytest.mark.unit
def test_detects_python_via_pyproject(tmp_path):
    _touch(tmp_path / "pyproject.toml", "[project]\nname = 'x'\n")
    info = detect_project(tmp_path)
    assert info.language == "python"
    assert info.subdir == ""
    assert info.marker == "pyproject.toml"


@pytest.mark.unit
def test_detects_python_via_setup_py(tmp_path):
    _touch(tmp_path / "setup.py", "from setuptools import setup; setup()\n")
    assert detect_project(tmp_path).language == "python"


@pytest.mark.unit
def test_detects_python_via_requirements_txt(tmp_path):
    _touch(tmp_path / "requirements.txt", "")
    assert detect_project(tmp_path).language == "python"


@pytest.mark.unit
def test_detects_javascript_via_package_json(tmp_path):
    _touch(tmp_path / "package.json", '{"name":"x"}')
    info = detect_project(tmp_path)
    assert info.language == "javascript"


@pytest.mark.unit
def test_detects_go_via_go_mod(tmp_path):
    _touch(tmp_path / "go.mod", "module x\n")
    assert detect_project(tmp_path).language == "go"


@pytest.mark.unit
def test_detects_rust_via_cargo_toml(tmp_path):
    _touch(tmp_path / "Cargo.toml", "[package]\nname='x'\n")
    assert detect_project(tmp_path).language == "rust"


@pytest.mark.unit
def test_unknown_when_no_markers(tmp_path):
    _touch(tmp_path / "README.md", "")
    info = detect_project(tmp_path)
    assert info.language == "unknown"
    assert info.subdir == ""
    assert info.marker is None


@pytest.mark.unit
def test_returns_unknown_for_missing_dir(tmp_path):
    info = detect_project(tmp_path / "does-not-exist")
    assert info.language == "unknown"


@pytest.mark.unit
def test_python_wins_over_javascript_at_root(tmp_path):
    """When a project has both, pick Python (we only support it today)."""
    _touch(tmp_path / "pyproject.toml", "")
    _touch(tmp_path / "package.json", "{}")
    info = detect_project(tmp_path)
    assert info.language == "python"


@pytest.mark.unit
def test_looks_one_dir_deep_for_monorepo(tmp_path):
    _touch(tmp_path / "README.md", "")  # no root marker
    _touch(tmp_path / "backend" / "pyproject.toml", "[project]\nname='x'\n")
    info = detect_project(tmp_path)
    assert info.language == "python"
    assert info.subdir == "backend"


@pytest.mark.unit
def test_skips_noise_dirs_when_descending(tmp_path):
    _touch(tmp_path / "README.md", "")
    _touch(tmp_path / "tests" / "pyproject.toml", "")  # would be misleading
    _touch(tmp_path / "node_modules" / "fake" / "package.json", "{}")
    # No real project marker outside the noise dirs.
    info = detect_project(tmp_path)
    assert info.language == "unknown"
