# Wringer in a box.
#
# One OCI image that runs `wring` against a repository mounted at /workspace.
# It exists because `.wringer.yaml` is code: `wring verify` runs the commands
# a repository declares, through a shell, with your privileges (SECURITY.md).
# v0.1 does not sandbox gates, so the container is the honest answer to "how
# do I run a stranger's gates?" — the isolation is the runtime's, not a claim
# Wringer makes about itself.
#
# Build. Everything installed here is either a Debian package or a pure-Python
# wheel (wringer is py3-none-any; PyYAML publishes x86_64 and aarch64 wheels),
# so there is no per-architecture branch and no compiler in the image:
#
#   docker buildx build --platform linux/amd64,linux/arm64 -t wringer:0.1.0 .
#
# Run (Docker syntax; apple/container on macOS 26 and Kubernetes consume the
# same image — this is a standard OCI image with no runtime-specific parts):
#
#   docker run --rm -v "$PWD:/workspace" wringer:0.1.0 verify
#
# The mount must be read-write: Wringer writes its evidence bundle to
# .wringer/ inside the repo, so a `:ro` mount fails late and confusingly.
#
# NOT IN THIS IMAGE: any coding agent, from any vendor. Wringer never ships a
# worker — the worker is a command you declare and Wringer spawns. Baking a
# vendor's CLI in here would make "vendor-neutral" true only in the prose.
# The consequence is real and worth knowing up front: a loop command run
# inside this image only works if the worker you declared is itself reachable
# from the container — a script in your mounted workspace, or an image built
# FROM this one that adds the agent you chose.

FROM python:3.12-slim

# Tag, not digest. A manifest-list digest would pin the base reproducibly but
# has to be updated by hand on every base rebuild; if reproducible builds
# become a requirement, that is the line to change.

# The published version to install. The image installs from PyPI rather than
# from this source tree on purpose: what runs in the container is then the
# same artifact `pip install wringer` gives anyone else, so the image proves
# the release instead of a working copy. Override with
# `--build-arg WRINGER_VERSION=x.y.z` — the pinned version is exactly the
# command surface available inside the container.
ARG WRINGER_VERSION=0.1.0

LABEL org.opencontainers.image.title="wringer" \
      org.opencontainers.image.description="Runs a repository's declared gates and leaves an evidence bundle" \
      org.opencontainers.image.version="${WRINGER_VERSION}" \
      org.opencontainers.image.source="https://github.com/marcoakes/wringer" \
      org.opencontainers.image.url="https://github.com/marcoakes/wringer" \
      org.opencontainers.image.documentation="https://github.com/marcoakes/wringer/blob/main/QUICKSTART.md" \
      org.opencontainers.image.licenses="Apache-2.0"

# Unbuffered so the ✓/✗ lines arrive while the run is happening rather than in
# one lump when the container exits. Gates inherit this variable too, which is
# harmless: their output is captured through a pipe either way.
ENV PYTHONUNBUFFERED=1

# git, because Wringer records which commit was verified — without it every
# run exits 2 before a gate runs. --no-install-recommends keeps out the docs,
# Perl extras and mail transports that `git` otherwise suggests.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

# Into the system Python, with no venv: the container is already the isolation
# boundary, and a venv inside it would only add a PATH to get wrong.
# `wring --version` runs at build time so a broken entry point fails here
# rather than on somebody's first command.
RUN pip install --no-cache-dir "wringer==${WRINGER_VERSION}" \
 && wring --version

# Non-root by default. uid/gid 1000 is the first ordinary user on Debian and
# the usual uid of a single-user host account, so a bind-mounted repo often
# lands owned by exactly this user.
#
# The `safe.directory` lines are not optional decoration. A mounted repo
# carries whatever uid it has on the host, which is usually not this
# container's; git then refuses it as "dubious ownership" and `wring verify`
# exits 2 having proven nothing. The trust is scoped to the mount point and
# repositories directly under it — deliberately not `safe.directory=*`, which
# would trust every path in the filesystem. System config is used because git
# only honours this setting from protected scopes.
RUN groupadd --gid 1000 wring \
 && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash wring \
 && mkdir -p /workspace \
 && chown wring:wring /workspace \
 && git config --system --add safe.directory /workspace \
 && git config --system --add safe.directory '/workspace/*'

USER wring

# Where the user's repository gets mounted. Nothing is copied in at build
# time — the workspace is the user's, at run time, or it is empty.
WORKDIR /workspace

# `wring` as the entrypoint so `docker run … verify` reads as the command it
# is: everything after the image name is wring's own argv.
ENTRYPOINT ["wring"]

# No arguments prints the help. Defaulting to `verify` would run whatever
# happens to be mounted, which is a surprising default for a tool whose point
# is that nothing runs unless somebody asked for it.
CMD ["--help"]
