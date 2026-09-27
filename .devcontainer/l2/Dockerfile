# This repository's L2 image: where its hooks and its test suite run, with no
# network and no credentials (see docs/LAYERS.md in devcontainer-airlock).
# pytest, pytest-cov and PyYAML are what the equivalence tests need; the
# fixtures they compare against are public files that
# tools/fetch-originals.sh downloads without a token, so `make test` runs the
# whole thing in L2 with `l2 --net`.
ARG L2_IMAGE=ghcr.io/ivan-pinatti-labs/airlock-l2@sha256:d6762ad87c96d66723996814ef677fb3a617db6b37cae2b6d4ae1401632ffc34
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
