# This repository's L2 image: where its hooks run, with no network and no
# credentials (see docs/LAYERS.md in devcontainer-airlock). The test suite
# does not run here: `make test` runs it in the pinned Python image, through
# the L2 engine, so this image carries nothing for it.
ARG L2_IMAGE=ghcr.io/ivan-pinatti-labs/airlock-l2@sha256:fba17982e637adf923c486e179b51b8fe362db17568a41c6ec668d56e58a0e71
# hadolint ignore=DL3006
FROM ${L2_IMAGE}
# The base image already ends as the unprivileged workbench user; say so here
# too, so this image never silently runs as root if the base changes.
USER 1000:1000
