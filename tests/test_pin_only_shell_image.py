# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""The shell_image_pin grammar: an image pinned by tag and digest in a script.

devcontainer-airlock pins the images its scripts run (trivy, skopeo, a
registry, its mirror backend, gitleaks) as `NAME=image:tag@sha256:<digest>`
under a `# renovate:` annotation, and Renovate moves the tag and the digest
together. No other grammar reads a shell assignment, so every one of those
bumps went to a person.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "pin_only.py"
TARGET = "scripts/build.sh"

OLD = "docker.io/aquasec/trivy:0.74.0@sha256:" + "a" * 64
NEW = "docker.io/aquasec/trivy:0.76.0@sha256:" + "b" * 64

CONFIG = f"""\
allowed_paths:
  - {TARGET}
arg_sources:
  - file: {TARGET}
    annotations:
      - '^#\\s*renovate:'
rules:
  - path: {TARGET}
    grammars: [shell_image_pin]
"""

BASE = f"""\
#!/bin/bash
# renovate: datasource=docker depName=docker.io/aquasec/trivy
TRIVY_IMAGE={OLD}
# renovate: datasource=docker depName=docker.io/aquasec/trivy
QUOTED_IMAGE="{OLD}"
UNANNOTATED_IMAGE={OLD}
# renovate: datasource=docker depName=docker.io/aquasec/trivy
ARG TRIVY_ARG={OLD}
"""


def _git(repo: Path, *args: str) -> str:
    # S603/S607: git from PATH, with arguments written here, in a throwaway
    # repository pytest created.
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _grade(tmp_path: Path, old_line: str, new_line: str) -> subprocess.CompletedProcess:
    """Commit BASE, replace one line, and grade the real diff against BASE."""
    target = tmp_path / TARGET
    target.parent.mkdir(parents=True)
    (tmp_path / "pin-only.yml").write_text(CONFIG)
    _git(tmp_path, "init", "-q")
    target.write_text(BASE)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    assert old_line in BASE
    target.write_text(BASE.replace(old_line, new_line, 1))
    diff = _git(tmp_path, "diff")
    target.write_text(BASE)
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(tmp_path / "pin-only.yml"),
            "--repo-root",
            str(tmp_path),
        ],
        input=diff,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_accepts_a_bump_of_tag_and_digest(tmp_path):
    result = _grade(tmp_path, f"TRIVY_IMAGE={OLD}", f"TRIVY_IMAGE={NEW}")
    assert result.returncode == 0, result.stdout


def test_accepts_a_quoted_bump(tmp_path):
    result = _grade(tmp_path, f'QUOTED_IMAGE="{OLD}"', f'QUOTED_IMAGE="{NEW}"')
    assert result.returncode == 0, result.stdout


def test_accepts_a_digest_only_bump(tmp_path):
    result = _grade(
        tmp_path,
        f"TRIVY_IMAGE={OLD}",
        "TRIVY_IMAGE=docker.io/aquasec/trivy:0.74.0@sha256:" + "c" * 64,
    )
    assert result.returncode == 0, result.stdout


def test_refuses_an_assignment_no_annotation_made_eligible(tmp_path):
    result = _grade(tmp_path, f"UNANNOTATED_IMAGE={OLD}", f"UNANNOTATED_IMAGE={NEW}")
    assert result.returncode == 1, result.stdout


def test_refuses_an_arg_line(tmp_path):
    # An annotated ARG is not a shell assignment, and this grammar does not
    # stand in for docker_image_pin.
    result = _grade(tmp_path, f"ARG TRIVY_ARG={OLD}", f"ARG TRIVY_ARG={NEW}")
    assert result.returncode == 1, result.stdout


def test_refuses_another_image(tmp_path):
    result = _grade(
        tmp_path,
        f"TRIVY_IMAGE={OLD}",
        "TRIVY_IMAGE=docker.io/evil/trivy:0.76.0@sha256:" + "b" * 64,
    )
    assert result.returncode == 1, result.stdout


def test_refuses_dropping_the_digest(tmp_path):
    result = _grade(
        tmp_path, f"TRIVY_IMAGE={OLD}", "TRIVY_IMAGE=docker.io/aquasec/trivy:0.76.0"
    )
    assert result.returncode == 1, result.stdout


def test_refuses_a_short_digest(tmp_path):
    result = _grade(
        tmp_path,
        f"TRIVY_IMAGE={OLD}",
        "TRIVY_IMAGE=docker.io/aquasec/trivy:0.76.0@sha256:bbbbbbb",
    )
    assert result.returncode == 1, result.stdout


def test_refuses_adding_quotes(tmp_path):
    result = _grade(tmp_path, f"TRIVY_IMAGE={OLD}", f'TRIVY_IMAGE="{NEW}"')
    assert result.returncode == 1, result.stdout


def test_refuses_a_payload_after_the_digest(tmp_path):
    result = _grade(tmp_path, f"TRIVY_IMAGE={OLD}", f"TRIVY_IMAGE={NEW}; payload")
    assert result.returncode == 1, result.stdout


def test_refuses_an_expansion_in_the_tag(tmp_path):
    result = _grade(
        tmp_path,
        f"TRIVY_IMAGE={OLD}",
        "TRIVY_IMAGE=docker.io/aquasec/trivy:$(payload)@sha256:" + "b" * 64,
    )
    assert result.returncode == 1, result.stdout


def test_refuses_a_renamed_variable(tmp_path):
    result = _grade(tmp_path, f"TRIVY_IMAGE={OLD}", f"OTHER_IMAGE={NEW}")
    assert result.returncode == 1, result.stdout
