"""Sandbox infrastructure for the Autonomous Contribution Pilot (v3).

Public surface:
    from app.sandbox import Workspace, SandboxRunner, SandboxResult
    from app.sandbox import docker_available, ensure_image_available
"""
from app.sandbox.container import (
    SandboxResult,
    SandboxRunner,
    docker_available,
    ensure_image_available,
)
from app.sandbox.exceptions import (
    CloneError,
    DockerNotAvailableError,
    ImageMissingError,
    SandboxError,
    SandboxRunError,
    SandboxTimeoutError,
    WorkspaceError,
)
from app.sandbox.workspace import Workspace

__all__ = [
    "CloneError",
    "DockerNotAvailableError",
    "ImageMissingError",
    "SandboxError",
    "SandboxResult",
    "SandboxRunError",
    "SandboxRunner",
    "SandboxTimeoutError",
    "Workspace",
    "WorkspaceError",
    "docker_available",
    "ensure_image_available",
]
