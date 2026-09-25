# This repository's L2 image: where its hooks and its test suite run, with no
# network and no credentials (see docs/LAYERS.md in devcontainer-images).
# pytest, pytest-cov and PyYAML are what the equivalence tests need; the
# fixtures they compare against are fetched with gh, in the workbench, by
# tools/fetch-originals.sh, since L2 never gets GitHub access.
ARG L2_IMAGE=localhost/devcontainer-l2:local
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
