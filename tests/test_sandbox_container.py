"""Tests for the Docker sandbox runner.

Split into two tiers:

  * Unit tests with mocked subprocess — always run.
  * Integration tests that actually invoke `docker run` — auto-skip when
    Docker isn't available OR when the sandbox image hasn't been built.
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.sandbox import (
    DockerNotAvailableError,
    ImageMissingError,
    SandboxRunner,
    SandboxTimeoutError,
    Workspace,
    docker_available,
    ensure_image_available,
)

# ---------------------------------------------------------------------------
# Unit tests (no Docker)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_argv_includes_network_none_by_default(tmp_path):
    ws = Workspace.create("inv-argv", root=tmp_path)
    runner = SandboxRunner(image="test-image:latest")
    argv = runner._build_docker_argv(
        workspace_host=ws.host_path,
        workdir="/workspace/foo",
        command=["pytest", "-q"],
        allow_network=False,
        env={},
    )
    assert "--network" in argv
    assert argv[argv.index("--network") + 1] == "none"


@pytest.mark.unit
def test_build_argv_allow_network_strips_network_flag(tmp_path):
    ws = Workspace.create("inv-net", root=tmp_path)
    runner = SandboxRunner(image="test-image:latest")
    argv = runner._build_docker_argv(
        workspace_host=ws.host_path,
        workdir="/workspace",
        command=["true"],
        allow_network=True,
        env={},
    )
    assert "--network" not in argv


@pytest.mark.unit
def test_build_argv_carries_caps_and_mount(tmp_path):
    ws = Workspace.create("inv-caps", root=tmp_path)
    runner = SandboxRunner(
        image="x:1", memory_limit="2g", cpus=0.5, default_timeout_s=42,
    )
    argv = runner._build_docker_argv(
        workspace_host=ws.host_path,
        workdir="/workspace",
        command=["echo", "hi"],
        allow_network=False,
        env={"FOO": "bar"},
    )
    assert argv[0] == "docker"
    assert argv[1] == "run"
    assert "--rm" in argv
    assert "2g" in argv          # memory cap
    assert "0.5" in argv         # cpu cap
    assert "--read-only" in argv
    assert any(a.startswith("/tmp:size=") for a in argv)
    assert any(":/workspace:rw" in a for a in argv)
    assert "FOO=bar" in argv
    # Image + command at the end, in that order.
    assert argv[-3:] == ["x:1", "echo", "hi"]


@pytest.mark.unit
def test_run_raises_when_image_missing(tmp_path, monkeypatch):
    ws = Workspace.create("inv-img", root=tmp_path)
    runner = SandboxRunner(image="ghost:nope")

    def raise_missing(_image):
        raise ImageMissingError("ghost:nope not built")

    monkeypatch.setattr("app.sandbox.container.ensure_image_available", raise_missing)
    with pytest.raises(ImageMissingError):
        runner.run(ws, ["true"])


@pytest.mark.unit
def test_run_raises_timeout(tmp_path, monkeypatch):
    ws = Workspace.create("inv-timeout", root=tmp_path)
    runner = SandboxRunner(image="x", default_timeout_s=1)
    monkeypatch.setattr("app.sandbox.container.ensure_image_available", lambda _: None)

    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["docker", "run"], timeout=1)

    monkeypatch.setattr("app.sandbox.container.subprocess.run", fake_run)
    with pytest.raises(SandboxTimeoutError):
        runner.run(ws, ["sleep", "10"])


@pytest.mark.unit
def test_run_raises_when_docker_missing(tmp_path, monkeypatch):
    ws = Workspace.create("inv-nod", root=tmp_path)
    runner = SandboxRunner(image="x")
    monkeypatch.setattr("app.sandbox.container.ensure_image_available", lambda _: None)
    monkeypatch.setattr(
        "app.sandbox.container.subprocess.run",
        MagicMock(side_effect=FileNotFoundError("no docker")),
    )
    with pytest.raises(DockerNotAvailableError):
        runner.run(ws, ["true"])


@pytest.mark.unit
def test_run_returns_result_for_nonzero_exit(tmp_path, monkeypatch):
    """Non-zero exit codes are NOT errors — they're legitimate results."""
    ws = Workspace.create("inv-fail", root=tmp_path)
    runner = SandboxRunner(image="x")
    monkeypatch.setattr("app.sandbox.container.ensure_image_available", lambda _: None)

    class FakeProc:
        returncode = 1
        stdout = "some output"
        stderr = "test failure"

    monkeypatch.setattr("app.sandbox.container.subprocess.run", lambda *a, **k: FakeProc())
    result = runner.run(ws, ["pytest"])
    assert result.exit_code == 1
    assert not result.ok
    assert result.stderr == "test failure"


@pytest.mark.unit
def test_docker_available_is_false_when_cli_missing(monkeypatch):
    monkeypatch.setattr("app.sandbox.container.shutil.which", lambda _: None)
    assert docker_available() is False


# ---------------------------------------------------------------------------
# Integration tests (skipped when Docker / image missing)
# ---------------------------------------------------------------------------


def _image_ready() -> bool:
    if not docker_available():
        return False
    try:
        ensure_image_available(settings.sandbox_image)
    except ImageMissingError:
        return False
    return True


needs_sandbox = pytest.mark.skipif(
    not _image_ready(),
    reason="Docker not available or sandbox image not built (`python -m app.sandbox build`)",
)


@pytest.mark.integration
@needs_sandbox
def test_sandbox_echoes_back(tmp_path):
    """Smoke: spawn the container, run a benign command, get output back."""
    ws = Workspace.create("inv-echo", root=tmp_path)
    runner = SandboxRunner()
    result = runner.run(ws, ["echo", "hello-from-sandbox"], timeout_s=30)
    assert result.ok
    assert "hello-from-sandbox" in result.stdout


@pytest.mark.integration
@needs_sandbox
def test_sandbox_blocks_network_by_default(tmp_path):
    """The default --network=none should make outbound connections fail."""
    ws = Workspace.create("inv-blocked", root=tmp_path)
    runner = SandboxRunner()
    result = runner.run(
        ws,
        [
            "python",
            "-c",
            "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)",
        ],
        timeout_s=20,
    )
    # We expect this to fail — non-zero exit, error in stderr.
    assert result.exit_code != 0
    assert any(
        marker in result.stderr.lower()
        for marker in ("network is unreachable", "no route", "name or service", "errno")
    )
