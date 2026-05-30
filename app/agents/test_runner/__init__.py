"""Test Runner agent (v3 — Autonomous Contribution Pilot).

Public surface:
    from app.agents.test_runner import run_tests, TestRunResult, PhaseResult
"""
from app.agents.test_runner.detector import ProjectInfo, detect_project
from app.agents.test_runner.runner import run_tests
from app.agents.test_runner.schemas import (
    Classification,
    Language,
    PhaseResult,
    TestRunResult,
)

__all__ = [
    "Classification",
    "Language",
    "PhaseResult",
    "ProjectInfo",
    "TestRunResult",
    "detect_project",
    "run_tests",
]
