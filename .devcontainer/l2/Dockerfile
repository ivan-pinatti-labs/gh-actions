# This repository's L2 image: where its hooks run, with no network and no
# credentials (see docs/LAYERS.md in devcontainer-airlock). The test suite
# does not run here: `make test` runs it in the pinned Python image, through
# the L2 engine, so this image carries nothing for it.
ARG L2_IMAGE=ghcr.io/ivan-pinatti-labs/airlock-l2@sha256:7d48b06dc3f9a2d72623479ca13044a601c3f45fd633e7361c43469d8c1d1f0a
# hadolint ignore=DL3006
FROM ${L2_IMAGE}
# The base image already ends as the unprivileged workbench user; say so here
# too, so this image never silently runs as root if the base changes.
USER 1000:1000
