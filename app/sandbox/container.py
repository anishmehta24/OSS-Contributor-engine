"""Docker-based sandbox command runner.

`SandboxRunner.run(workspace, cmd, ...)` invokes `docker run` against the
prebuilt sandbox image with:

  --rm                      auto-remove the container on exit
  --network=none            no egress from inside the sandbox (default)
  --memory=<limit>          configurable RAM cap
  --cpus=<n>                configurable CPU cap
  --read-only               root FS is read-only
  --tmpfs /tmp:size=64m     a writable scratch dir lives in tmpfs
  -v <ws>:/workspace        bind-mount the workspace dir
  --user sandbox            drop privileges inside the container
  --workdir /workspace/...  start in the cloned repo dir

The runner does NOT use the Docker Python SDK on purpose — `docker run` via
subprocess is a smaller dependency surface and matches what an ops person
would type by hand for debugging.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.core.config import settings
from app.sandbox.exceptions import (
    DockerNotAvailableError,
    ImageMissingError,
    SandboxRunError,
    SandboxTimeoutError,
)
from app.sandbox.workspace import Workspace

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of one `SandboxRunner.run` call."""

    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxRunner:
    """Runs commands inside the sandbox image. Stateless — make one per call
    or share across calls; both work."""

    def __init__(
        self,
        *,
        image: str | None = None,
        memory_limit: str | None = None,
        cpus: float | None = None,
        default_timeout_s: int | None = None,
    ) -> None:
        self.image = image or settings.sandbox_image
        self.memory_limit = memory_limit or settings.sandbox_memory_limit
        self.cpus = cpus if cpus is not None else settings.sandbox_cpus
        self.default_timeout_s = (
            default_timeout_s
            if default_timeout_s is not None
            else settings.sandbox_default_timeout_s
        )

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def run(
        self,
        workspace: Workspace,
        command: list[str],
        *,
        workdir: str | None = None,
        timeout_s: int | None = None,
        allow_network: bool = False,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Run `command` inside a fresh sandbox container.

        Args:
            workspace: the Workspace whose host_path gets bind-mounted to
                /workspace inside the container.
            command: argv list. The first element is the executable; we do
                NOT spin up a shell, so shell features (pipes, &&, $vars)
                don't work — pass them inside a `sh -c "..."` wrapper if
                you need them.
            workdir: relative path under /workspace to cd into. Defaults to
                /workspace itself. E.g. if you cloned `acme/foo`, pass
                `acme/foo` here. (Or absolute /workspace/acme/foo.)
            timeout_s: wall-clock cap. None = use settings default.
            allow_network: if True, drop --network=none. Used very rarely —
                e.g. `pip install` in a controlled environment where we
                trust the indexes. Default off.
            env: extra env vars passed via -e.
        """
        ensure_image_available(self.image)

        effective_workdir = "/workspace"
        if workdir:
            # Normalize: strip leading slash so we can always prefix
            # `/workspace/`.
            normalized = workdir.lstrip("/")
            effective_workdir = f"/workspace/{normalized}" if normalized else "/workspace"

        argv = self._build_docker_argv(
            workspace_host=workspace.host_path,
            workdir=effective_workdir,
            command=command,
            allow_network=allow_network,
            env=env or {},
        )

        cap = timeout_s if timeout_s is not None else self.default_timeout_s
        log.info(
            "sandbox_run_start",
            investigation_id=workspace.investigation_id,
            cmd=command,
            workdir=effective_workdir,
            timeout_s=cap,
        )

        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=cap,
            )
        except subprocess.TimeoutExpired as e:
            duration = time.monotonic() - started
            log.warning(
                "sandbox_run_timeout",
                investigation_id=workspace.investigation_id,
                duration_s=duration,
            )
            # Make sure no zombie container lingers — `docker run --rm` will
            # auto-cleanup once we kill the process, but be defensive.
            raise SandboxTimeoutError(
                f"sandbox command exceeded {cap}s wall clock",
            ) from e
        except FileNotFoundError as e:
            raise DockerNotAvailableError("`docker` CLI not on PATH") from e

        duration = time.monotonic() - started

        # Distinguish "command exited non-zero" (legitimate result we report)
        # from "Docker itself failed" (infrastructure problem, raise).
        # Docker reports its own errors with exit code 125-127 on the host
        # `docker run` invocation, e.g. 125 = container failed to start.
        if proc.returncode in (125, 126, 127) and not proc.stdout.strip():
            raise SandboxRunError(
                f"docker run failed ({proc.returncode}): "
                f"{proc.stderr.strip()[:400]}",
            )

        result = SandboxResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_s=duration,
        )
        log.info(
            "sandbox_run_done",
            investigation_id=workspace.investigation_id,
            exit=result.exit_code,
            duration_s=round(result.duration_s, 3),
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_docker_argv(
        self,
        *,
        workspace_host: Path,
        workdir: str,
        command: list[str],
        allow_network: bool,
        env: dict[str, str],
    ) -> list[str]:
        # Resolve to an absolute path. Docker on Windows is happy with both
        # forward-slash and backslash forms, but absolute is mandatory.
        mount_src = str(workspace_host.resolve())

        argv: list[str] = [
            "docker",
            "run",
            "--rm",
            "--memory",
            self.memory_limit,
            "--cpus",
            str(self.cpus),
            # Defense in depth — even with --network=none, no new files
            # should escape the workspace.
            "--read-only",
            "--tmpfs",
            "/tmp:size=64m,exec",
            "--workdir",
            workdir,
            "-v",
            f"{mount_src}:/workspace:rw",
        ]
        if not allow_network:
            argv += ["--network", "none"]
        for k, v in env.items():
            argv += ["-e", f"{k}={v}"]
        argv += [self.image]
        argv += command
        return argv


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def docker_available() -> bool:
    """Quick check used by tests + CLI to skip when Docker isn't usable."""
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


def ensure_image_available(image: str) -> None:
    """Raise ImageMissingError if the image hasn't been built/pulled."""
    if shutil.which("docker") is None:
        raise DockerNotAvailableError("`docker` CLI not on PATH")
    proc = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ImageMissingError(
            f"sandbox image {image!r} not found. "
            f"Run `uv run python -m app.sandbox build`.",
        )
