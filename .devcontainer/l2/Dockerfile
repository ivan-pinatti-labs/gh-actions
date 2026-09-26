# This repository's L2 image: where its hooks and its test suite run, with no
# network and no credentials (see docs/LAYERS.md in devcontainer-airlock).
# pytest, pytest-cov and PyYAML are what the equivalence tests need; the
# fixtures they compare against are public files that
# tools/fetch-originals.sh downloads without a token, so `make test` runs the
# whole thing in L2 with `l2 --net`.
ARG L2_IMAGE=ghcr.io/ivan-pinatti-labs/airlock-l2@sha256:fc340eb19b1c98dd346d4ef79c0f739668e464b40a0150ad704b6f5cb2069a43
# hadolint ignore=DL3006
FROM ${L2_IMAGE}
USER 0:0
# hadolint ignore=DL3008
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    python3-pytest \
    python3-pytest-cov \
    python3-yaml \
  && rm -rf /var/lib/apt/lists/*
USER 1000:1000
