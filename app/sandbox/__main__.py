"""Sandbox CLI.

Usage:
    uv run python -m app.sandbox build           # build image (idempotent)
    uv run python -m app.sandbox build --force   # rebuild from scratch
    uv run python -m app.sandbox info            # show image + Docker status
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from app.core.config import settings
from app.core.logging import configure_logging
from app.sandbox.container import docker_available, ensure_image_available
from app.sandbox.exceptions import ImageMissingError

DOCKERFILE = Path(__file__).parent / "Dockerfile"


def cmd_build(args: argparse.Namespace) -> int:
    if shutil.which("docker") is None:
        print("ERROR: `docker` not on PATH. Install Docker Desktop first.", file=sys.stderr)
        return 1
    if not docker_available():
        print("ERROR: Docker daemon not reachable.", file=sys.stderr)
        return 1

    image = settings.sandbox_image
    if not args.force:
        try:
            ensure_image_available(image)
        except ImageMissingError:
            pass
        else:
            print(f"Image {image} already built. Pass --force to rebuild.")
            return 0

    argv = [
        "docker",
        "build",
        "-t",
        image,
        "-f",
        str(DOCKERFILE),
        str(DOCKERFILE.parent),
    ]
    if args.force:
        argv.insert(2, "--no-cache")
    print(f"$ {' '.join(argv)}\n")
    proc = subprocess.run(argv)
    return proc.returncode


def cmd_info(_: argparse.Namespace) -> int:
    print(f"Configured image: {settings.sandbox_image}")
    print(f"Workspace root:   {settings.sandbox_workspace_root}")
    print(f"Memory limit:     {settings.sandbox_memory_limit}")
    print(f"CPU limit:        {settings.sandbox_cpus}")
    print(f"Default timeout:  {settings.sandbox_default_timeout_s}s")
    print()

    if not docker_available():
        print("Docker:           NOT AVAILABLE (CLI missing or daemon down)")
        return 1

    proc = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
    )
    print(f"Docker daemon:    {proc.stdout.strip() or '(no version)'}")

    try:
        ensure_image_available(settings.sandbox_image)
        proc = subprocess.run(
            ["docker", "image", "inspect", settings.sandbox_image, "--format", "{{.Id}} {{.Size}}B"],
            capture_output=True,
            text=True,
        )
        print(f"Image:            built — {proc.stdout.strip()}")
    except ImageMissingError as e:
        print(f"Image:            NOT BUILT — {e}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.sandbox")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--force", action="store_true", help="rebuild from scratch (--no-cache)")
    p_build.set_defaults(func=cmd_build)

    sub.add_parser("info").set_defaults(func=cmd_info)
    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
