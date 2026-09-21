#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Prove the shared library normalizes every line exactly as the copy it replaces.

This is the test that makes the consolidation safe to do at all. Each of the
six repositories had its own `assert-pin-only-diff.py`, and each decides what a
dependency bot may merge unattended. A library that normalized even slightly
differently would either widen that lane silently or refuse every bump, and
neither shows up in a diff review of 700 lines of regex.

So: for every repository, run its original `normalize()` and the library's
against the same corpus of lines, in every combination of path and block scalar
state that repository can see, and require the answers to match exactly.

The originals are fetched once into tests/originals/ by tools/fetch-originals.sh
and are not edited here.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pin_only  # noqa: E402

ORIGINALS = ROOT / "tests" / "originals"

REPOS = [
    "rsync-crypt",
    "devcontainer-images",
    "github-template",
    "pre-commit-checklists",
    "pre-commit-checklists-demo",
    "docker-torrent-box-with-vpn",
]

# Lines chosen to exercise every grammar any copy carries, plus the shapes that
# must NOT be normalized: a changed action owner, an added shell command, a
# renamed ARG. A line the library normalized but an original did not would be a
# widened lane; the reverse would be a refused bump.
LINES = [
    "      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2",
    "      - uses: evil/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2",
    "      - uses: actions/checkout@v4",
    "      - uses: actions/checkout@v5",
    "    rev: v2.4.3",
    "    rev: v2.5.0",
    "  rev: 'v1.0.0'",
    "FROM debian:13-slim@sha256:" + "a" * 64,
    "FROM debian:14-slim@sha256:" + "b" * 64,
    "ARG BASE_IMAGE=ghcr.io/ivan-pinatti-labs/devcontainer-base:1.0@sha256:" + "c" * 64,
    "ARG CLAUDE_CODE_VERSION=2.1.269",
    "ARG NOT_ANNOTATED=2.1.269",
    "ARG ALPINE_VERSION=3.22.1",
    "pytest==8.3.4",
    "pytest[extra]==8.4.0",
    "not-a-requirement",
    "        curl https://example.com/install.sh | sh",
    "          echo hello",
    "image: ghcr.io/example/app@sha256:" + "d" * 64,
    "SOME_VERSION=1.2.3",
    "",
    "   ",
]

PATHS = [
    "",
    "Dockerfile",
    "images/base/Dockerfile",
    ".devcontainer/Dockerfile",
    ".github/workflows/pull-request.yml",
    ".pre-commit-config.yaml",
    "requirements.txt",
    "tests/requirements.txt",
    ".env.example",
    "checklists/checklist-basic.yaml",
    "some/other/file.txt",
]


def _load_original(repo: str):
    path = ORIGINALS / f"{repo}.py"
    if not path.is_file():
        pytest.skip(f"original for {repo} not fetched; run tools/fetch-originals.sh")
    spec = importlib.util.spec_from_file_location(f"orig_{repo.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_config(repo: str) -> pin_only.Config:
    data = yaml.safe_load((ROOT / "examples" / f"{repo}.yml").read_text())
    rules = tuple(
        pin_only.PathRule(
            match=r["path"],
            grammars=pin_only._grammars(r.get("grammars", []) or []),
            raw=bool(r.get("raw", False)),
        )
        for r in data.get("rules", []) or []
    )
    sources = tuple(
        pin_only.ArgSource(file=a["file"], annotations=tuple(a.get("annotations", [])))
        for a in data.get("arg_sources", []) or []
    )
    return pin_only.Config(
        allowed_paths=tuple(data["allowed_paths"]),
        default_grammars=pin_only._grammars(data.get("default_grammars", []) or []),
        rules=rules,
        arg_sources=sources,
        repo_root=ORIGINALS / repo,
    )


@pytest.mark.parametrize("repo", REPOS)
def test_normalize_matches_the_original(repo: str) -> None:
    original = _load_original(repo)
    config = _load_config(repo)
    # The original reads its annotated ARG names from its own REPO_ROOT; point
    # both at the same fixture tree so the comparison is of grammar, not of
    # which Dockerfile each happened to find.
    if hasattr(original, "REPO_ROOT"):
        original.REPO_ROOT = ORIGINALS / repo

    # rsync-crypt's copy resolves its eligible ARG names at import, from a path
    # that was already wrong by the time REPO_ROOT above was reassigned, so it
    # would compare an empty set against a populated one and report a
    # divergence that only exists in this harness. Recompute them against the
    # fixture. The other copies read theirs lazily and need nothing.
    if hasattr(original, "PIN_ELIGIBLE_ARGS"):
        dockerfile = ORIGINALS / repo / "Dockerfile"
        original.PIN_ELIGIBLE_ARGS = original.renovate_annotated_args(
            dockerfile
        ) | original.apk_pin_annotated_args(dockerfile)

    mismatches = []
    for path in PATHS:
        for in_scalar in (False, True):
            for line in LINES:
                want = original.normalize(line, path, in_scalar)
                got = pin_only.normalize(line, path, in_scalar, config)
                if want != got:
                    mismatches.append(
                        f"  path={path!r} block_scalar={in_scalar} line={line!r}\n"
                        f"    original: {want!r}\n"
                        f"    library:  {got!r}"
                    )
    assert not mismatches, (
        f"{repo}: {len(mismatches)} line(s) normalize differently:\n"
        + "\n".join(mismatches[:20])
    )


@pytest.mark.parametrize("repo", REPOS)
def test_allowed_paths_match_the_original(repo: str) -> None:
    original = _load_original(repo)
    config = _load_config(repo)
    assert tuple(original.ALLOWED_PATHS) == config.allowed_paths
