"""Per-investigation workspace directories.

A workspace is a host-side scratch dir into which we clone a target repo
and that we mount into the sandbox container as `/workspace`. Each
investigation gets its own dir, named by investigation id, so concurrent
investigations don't step on each other.

The clone happens on the HOST (not in the sandbox) because:
  - the host already has git + network + (if needed) auth configured,
  - the threat model is "untrusted *test* code", not "untrusted git
    transport", so isolating the clone step buys very little,
  - it's faster and simpler.

Lifecycle:
    with Workspace.create("inv-123") as ws:
        ws.clone("acme/widget", ref="main")
        # ... sandbox runs against ws.host_path ...
    # auto-cleanup on exit; or ws.cleanup() manually.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import structlog

from app.core.config import settings
from app.sandbox.exceptions import CloneError, WorkspaceError

log = structlog.get_logger(__name__)

# `inv-<uuid>` shape we tolerate as a directory name. Reject anything that
# could traverse out of the workspace root.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

# Shallow clone — we don't need history for patch + test runs, and a fresh
# clone of e.g. CPython at full depth is gigabytes.
_GIT_CLONE_DEPTH = 1


@dataclass(frozen=True)
class Workspace:
    """Handle for an investigation's host-side scratch dir.

    Construct via `Workspace.create(id)`, not the dataclass directly, so the
    sanitization + mkdir invariants are enforced.
    """

    investigation_id: str
    host_path: Path

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        investigation_id: str,
        *,
        root: Path | None = None,
        exist_ok: bool = False,
    ) -> Self:
        """Create a fresh workspace dir under the configured root.

        `exist_ok=False` is the default because reusing a workspace from a
        prior failed run would let stale files leak into the new run; tests
        and the smoke script pass `exist_ok=True` when they want to reuse.
        """
        if not _SAFE_ID_RE.match(investigation_id):
            raise WorkspaceError(
                f"investigation_id {investigation_id!r} contains unsafe chars",
            )

        root_dir = (root or Path(settings.sandbox_workspace_root)).resolve()
        root_dir.mkdir(parents=True, exist_ok=True)

        host_path = root_dir / investigation_id
        if host_path.exists():
            if not exist_ok:
                raise WorkspaceError(
                    f"workspace already exists at {host_path} "
                    "(pass exist_ok=True or clean it up first)",
                )
        else:
            host_path.mkdir()

        log.info(
            "sandbox_workspace_created",
            investigation_id=investigation_id,
            path=str(host_path),
        )
        return cls(investigation_id=investigation_id, host_path=host_path)

    def cleanup(self) -> None:
        """Remove the workspace dir and everything inside it."""
        if not self.host_path.exists():
            return
        # `ignore_errors` because Windows occasionally holds file handles
        # open just a beat after subprocesses exit; we don't want cleanup
        # to mask a real failure upstream.
        shutil.rmtree(self.host_path, ignore_errors=True)
        log.info(
            "sandbox_workspace_cleaned",
            investigation_id=self.investigation_id,
            path=str(self.host_path),
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info) -> None:
        self.cleanup()

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def clone(self, repo: str, *, ref: str | None = None, depth: int = _GIT_CLONE_DEPTH) -> Path:
        """Shallow-clone `<owner>/<repo>` into the workspace.

        Returns the path of the cloned repo (i.e. `host_path / repo_name`).
        """
        if "/" not in repo:
            raise CloneError(f"repo {repo!r} must be in 'owner/name' form")

        url = f"https://github.com/{repo}.git"
        target = self.host_path / repo.split("/", 1)[1]

        if target.exists():
            raise CloneError(f"clone target already exists: {target}")

        # `--no-tags` shaves a noticeable amount on big repos; we don't need
        # them for patch+test work. `--single-branch` always — we're shallow.
        cmd: list[str] = [
            "git", "clone", "--depth", str(depth), "--no-tags", "--single-branch",
        ]
        if ref:
            cmd += ["--branch", ref]
        cmd += [url, str(target)]

        log.info("sandbox_clone_start", repo=repo, ref=ref, target=str(target))
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                # 10 minutes — Windows + Defender scanning each extracted
                # file makes the checkout phase noticeably slower than
                # macOS/Linux. Most clones finish in <30s; this is just
                # headroom for medium-large repos (~1k files+) on slow
                # storage.
                timeout=600,
            )
        except subprocess.TimeoutExpired as e:
            raise CloneError(f"git clone timed out after {e.timeout}s") from e
        except FileNotFoundError as e:
            raise CloneError("`git` not found on PATH") from e

        if proc.returncode != 0:
            # 130 / 143 = process was killed by SIGINT/SIGTERM — not a real
            # git failure. Most common cause on Windows: antivirus killing
            # the checkout, or accidental Ctrl+C in the host terminal.
            hint = ""
            if proc.returncode in (130, 143):
                hint = (
                    " (killed externally — likely antivirus interference "
                    "or accidental Ctrl+C; retry usually works)"
                )
            raise CloneError(
                f"git clone {repo} failed (exit {proc.returncode}){hint}: "
                f"{proc.stderr.strip()[:500]}",
            )

        log.info("sandbox_clone_done", repo=repo, target=str(target))
        return target
