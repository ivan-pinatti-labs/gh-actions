# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""The arg_tag_commit grammar: a release pinned with the commit it must be.

devcontainer-airlock pins agent-policy as `ARG AGENT_POLICY_REF=<tag>@<commit>`
and its build refuses a tag that moved. Renovate bumps both halves in one
line, which no other grammar reads, so the bump went to a person.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "pin_only.py"
DOCKERFILE = "images/workbench/Dockerfile"

OLD = "v0.2.0@" + "a" * 40
NEW = "v0.6.12@" + "b" * 40

CONFIG = f"""\
allowed_paths:
  - {DOCKERFILE}
arg_sources:
  - file: {DOCKERFILE}
    annotations:
      - '^#\\s*renovate:'
rules:
  - path: "*Dockerfile"
    grammars: [arg_tag_commit]
"""

BASE = f"""\
FROM scratch
# renovate: datasource=github-tags depName=ivan-pinatti-labs/agent-policy
ARG AGENT_POLICY_REF={OLD}
ARG UNANNOTATED_REF={OLD}
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
    target = tmp_path / DOCKERFILE
    target.parent.mkdir(parents=True)
    (tmp_path / "pin-only.yml").write_text(CONFIG)
    _git(tmp_path, "init", "-q")
    target.write_text(BASE)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    assert old_line in BASE
    target.write_text(BASE.replace(old_line, new_line))
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


def test_accepts_a_bump_of_tag_and_commit(tmp_path):
    result = _grade(tmp_path, f"AGENT_POLICY_REF={OLD}", f"AGENT_POLICY_REF={NEW}")
    assert result.returncode == 0, result.stdout


def test_refuses_an_arg_no_annotation_made_eligible(tmp_path):
    result = _grade(tmp_path, f"UNANNOTATED_REF={OLD}", f"UNANNOTATED_REF={NEW}")
    assert result.returncode == 1, result.stdout


def test_refuses_dropping_the_commit(tmp_path):
    result = _grade(tmp_path, f"AGENT_POLICY_REF={OLD}", "AGENT_POLICY_REF=v0.6.12")
    assert result.returncode == 1, result.stdout


def test_refuses_a_short_commit(tmp_path):
    result = _grade(
        tmp_path, f"AGENT_POLICY_REF={OLD}", "AGENT_POLICY_REF=v0.6.12@bbbbbbb"
    )
    assert result.returncode == 1, result.stdout


def test_refuses_a_branch_in_place_of_a_release(tmp_path):
    result = _grade(
        tmp_path, f"AGENT_POLICY_REF={OLD}", "AGENT_POLICY_REF=main@" + "b" * 40
    )
    assert result.returncode == 1, result.stdout


def test_refuses_a_payload_after_the_commit(tmp_path):
    result = _grade(
        tmp_path, f"AGENT_POLICY_REF={OLD}", f"AGENT_POLICY_REF={NEW} $(payload)"
    )
    assert result.returncode == 1, result.stdout


def test_refuses_a_renamed_arg(tmp_path):
    result = _grade(tmp_path, f"ARG AGENT_POLICY_REF={OLD}", f"ARG OTHER_REF={NEW}")
    assert result.returncode == 1, result.stdout
