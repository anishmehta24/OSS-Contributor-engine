"""Unit tests for the workspace manager. No Docker, no network."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.sandbox.exceptions import CloneError, WorkspaceError
from app.sandbox.workspace import Workspace


@pytest.mark.unit
def test_create_makes_dir_under_root(tmp_path):
    ws = Workspace.create("inv-abc", root=tmp_path)
    assert ws.host_path == (tmp_path / "inv-abc").resolve()
    assert ws.host_path.is_dir()


@pytest.mark.unit
def test_create_rejects_unsafe_ids(tmp_path):
    for bad in ("../etc", "with space", "tab\there", "slash/in/id"):
        with pytest.raises(WorkspaceError, match="unsafe chars"):
            Workspace.create(bad, root=tmp_path)


@pytest.mark.unit
def test_create_rejects_existing_by_default(tmp_path):
    Workspace.create("inv-dup", root=tmp_path)
    with pytest.raises(WorkspaceError, match="already exists"):
        Workspace.create("inv-dup", root=tmp_path)


@pytest.mark.unit
def test_create_reuses_with_exist_ok(tmp_path):
    Workspace.create("inv-dup", root=tmp_path)
    ws = Workspace.create("inv-dup", root=tmp_path, exist_ok=True)
    assert ws.host_path.is_dir()


@pytest.mark.unit
def test_cleanup_removes_workspace(tmp_path):
    ws = Workspace.create("inv-cleanme", root=tmp_path)
    (ws.host_path / "sentinel").write_text("x")
    ws.cleanup()
    assert not ws.host_path.exists()


@pytest.mark.unit
def test_context_manager_auto_cleans(tmp_path):
    path: Path
    with Workspace.create("inv-ctx", root=tmp_path) as ws:
        path = ws.host_path
        (path / "f").write_text("x")
        assert path.exists()
    assert not path.exists()


@pytest.mark.unit
def test_cleanup_is_idempotent(tmp_path):
    ws = Workspace.create("inv-double", root=tmp_path)
    ws.cleanup()
    ws.cleanup()  # should not raise


@pytest.mark.unit
def test_clone_rejects_bad_repo_format(tmp_path):
    ws = Workspace.create("inv-bad", root=tmp_path)
    with pytest.raises(CloneError, match="owner/name"):
        ws.clone("not-a-slash")


@pytest.mark.unit
def test_clone_refuses_existing_target(tmp_path):
    ws = Workspace.create("inv-conflict", root=tmp_path)
    (ws.host_path / "repo").mkdir()
    with pytest.raises(CloneError, match="already exists"):
        ws.clone("acme/repo")


@pytest.mark.unit
def test_clone_uses_shallow_and_correct_url(tmp_path):
    """Validate the git invocation without actually running git."""
    ws = Workspace.create("inv-cmd", root=tmp_path)

    class FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    with patch("app.sandbox.workspace.subprocess.run", return_value=FakeProc()) as mrun:
        ws.clone("acme/widget", ref="dev")

    called_argv = mrun.call_args.args[0]
    assert called_argv[0] == "git"
    assert called_argv[1] == "clone"
    assert "--depth" in called_argv
    assert "--branch" in called_argv
    assert "dev" in called_argv
    assert "https://github.com/acme/widget.git" in called_argv


@pytest.mark.unit
def test_clone_surfaces_git_error(tmp_path):
    ws = Workspace.create("inv-err", root=tmp_path)

    class FakeProc:
        returncode = 128
        stdout = ""
        stderr = "fatal: repository not found"

    with (
        patch("app.sandbox.workspace.subprocess.run", return_value=FakeProc()),
        pytest.raises(CloneError, match="repository not found"),
    ):
        ws.clone("acme/missing")
