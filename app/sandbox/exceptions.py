"""Sandbox-specific errors. Kept narrow so callers can react to each kind."""


class SandboxError(Exception):
    """Base class — never raised directly."""


class DockerNotAvailableError(SandboxError):
    """`docker` CLI missing or daemon not reachable."""


class ImageMissingError(SandboxError):
    """Sandbox image hasn't been built yet. Run `python -m app.sandbox build`."""


class WorkspaceError(SandboxError):
    """Problem creating or interacting with the per-investigation workspace."""


class CloneError(WorkspaceError):
    """Repo clone failed (network, auth, ref not found, …)."""


class SandboxRunError(SandboxError):
    """Container run failed for a reason other than a non-zero exit code."""


class SandboxTimeoutError(SandboxRunError):
    """Container exceeded the configured wall-clock deadline."""
