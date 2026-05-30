# Base image for the Autonomous Contribution Pilot sandbox.
#
# What runs in here:
#   - Cloned target repos
#   - Patch-application commands (`git apply`, file edits)
#   - The target project's test suite (pytest / npm test / etc.)
#
# Design constraints:
#   - Pre-bake the toolchains we need so per-run startup is < 1s
#   - Non-root user — defense in depth even with --network=none
#   - No SSH, no networking tools, no shell history
#   - Slim base to keep image pull/push cheap
#
# Build (idempotent):
#   uv run python -m app.sandbox build
#
# Run (handled by app/sandbox/container.py — don't `docker run` by hand):
#   docker run --rm --network=none --memory=1g --cpus=1.0 \
#       -v ./workspace:/workspace -u sandbox \
#       oss-engine-sandbox:latest <cmd>

FROM python:3.12-slim-bookworm

# Versions baked into the image; bump explicitly so builds are reproducible.
ARG NODE_MAJOR=20

# 1) System packages — git for repo ops, build-essential for native Python
#    extensions (numpy, lxml, …) that real OSS test suites pull in,
#    curl + ca-certificates for the Node install.
# 2) Node (NodeSource setup script), so JS/TS projects work too.
# 3) Aggressive cleanup — every MB shows up in `docker images`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         git \
         build-essential \
         ca-certificates \
         curl \
         gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y --auto-remove gnupg \
    && rm -rf /var/lib/apt/lists/* /root/.npm

# Common test runners that 90% of Python projects expect to find.
# Installed at the system level so a freshly-cloned repo can run tests
# without `pip install -e .` first.
RUN pip install --no-cache-dir \
        pytest \
        pytest-asyncio \
        pip-tools \
    && rm -rf /root/.cache/pip

# Non-root user. UID/GID 1000 matches the typical host user on Linux,
# which makes bind-mount file permissions Just Work.
ARG SANDBOX_UID=1000
ARG SANDBOX_GID=1000
RUN groupadd --gid ${SANDBOX_GID} sandbox \
    && useradd --uid ${SANDBOX_UID} --gid sandbox --shell /bin/bash --create-home sandbox

# Where the host mounts the workspace.
WORKDIR /workspace

# Drop privileges. Any RUN/CMD/ENTRYPOINT after this runs as `sandbox`.
USER sandbox

# Default command is a no-op so `docker run … image` without a CMD just
# exits cleanly (handy for image-readiness checks).
CMD ["true"]
