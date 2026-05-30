"""End-to-end sandbox smoke.

Proves:
  1. Docker is reachable.
  2. The sandbox image is built.
  3. We can clone a real public repo into a workspace.
  4. We can run an arbitrary command inside the sandbox against that repo.
  5. The sandbox actually blocks network egress by default.

Run with:
    uv run python scripts/sandbox_smoke.py

Exits 0 on success, non-zero on the first failed check.
"""
from __future__ import annotations

import sys
import uuid

from app.core.config import settings
from app.core.logging import configure_logging
from app.sandbox import (
    ImageMissingError,
    SandboxRunner,
    Workspace,
    docker_available,
    ensure_image_available,
)

# A tiny, stable, MIT-licensed public repo we use as a canary. Easy to clone,
# no heavy deps, exists across years so we won't hit a 404 next month.
CANARY_REPO = "octocat/Hello-World"


def main() -> int:
    configure_logging()

    print("=== Sandbox smoke ===")

    # 1. Docker reachable
    print("[1/5] docker available?  ", end="")
    if not docker_available():
        print("NO  (install Docker Desktop and start it)")
        return 1
    print("yes")

    # 2. Image built
    print("[2/5] sandbox image?     ", end="")
    try:
        ensure_image_available(settings.sandbox_image)
    except ImageMissingError as e:
        print(f"NO  ({e})")
        return 1
    print(f"yes ({settings.sandbox_image})")

    inv_id = f"smoke-{uuid.uuid4().hex[:8]}"

    with Workspace.create(inv_id) as ws:
        # 3. Clone
        print(f"[3/5] clone {CANARY_REPO}…  ", end="", flush=True)
        try:
            target = ws.clone(CANARY_REPO)
        except Exception as e:
            print(f"FAIL  ({e})")
            return 1
        print(f"OK   ({target.name}/)")

        runner = SandboxRunner()

        # 4. Run a benign command — list the repo root from inside the sandbox.
        print("[4/5] sandbox ls…        ", end="", flush=True)
        ls = runner.run(ws, ["ls", "-la"], workdir=target.name, timeout_s=20)
        if not ls.ok:
            print(f"FAIL (exit {ls.exit_code})")
            print(ls.stderr[:400])
            return 1
        readme_present = any(line.endswith("README") or "README" in line for line in ls.stdout.splitlines())
        print(f"OK   ({ls.duration_s:.2f}s, README present={readme_present})")

        # 5. Prove network is actually blocked.
        print("[5/5] network blocked?   ", end="", flush=True)
        # `sh -c` so we can use redirection. We expect curl to fail (exit !=0)
        # because --network=none means there's no route to anywhere.
        probe = runner.run(
            ws,
            [
                "sh",
                "-c",
                "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)\" 2>&1",
            ],
            workdir=target.name,
            timeout_s=15,
        )
        if probe.exit_code == 0:
            print("FAIL  (network was reachable — sandbox is leaky!)")
            print(probe.stdout)
            return 1
        print(f"yes  (probe exit {probe.exit_code} as expected)")

    print("\nAll checks passed. Sandbox is wired up correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
