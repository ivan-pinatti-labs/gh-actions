# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Grade whole diffs through parse(), not just single lines through normalize().

test_equivalence.py compares `normalize()` against each original's, which is
where the grammars live and where the interesting differences were. It never
exercised `parse()`, so it could not see how `parse()` decides the
`in_block_scalar` argument it passes in, and a bug in exactly that decision got
through review: for any path outside `.github/workflows/`, absent block scalar
marks were read as "assume a block scalar" rather than "this file has none", so
a configuration whose grammars are all `outside_block_scalar` normalized
nothing and refused a plain pin bump.

These tests grade a real unified diff for every shipped configuration, which is
the level the bug was visible at.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = sorted(p.name[:-4] for p in (ROOT / "examples").glob("*.yml"))

# The diffs live in tests/fixtures/ rather than inline. They are data, not
# code, and a unified diff carries its own leading spaces and tabs that a
# Python string literal cannot hold without tripping the repository's
# editorconfig rules over indentation it has no say in.
FIXTURES = Path(__file__).parent / "fixtures"
REV_BUMP = (FIXTURES / "rev-bump.diff").read_text()
SMUGGLED_COMMAND = (FIXTURES / "smuggled-command.diff").read_text()
CHANGED_ACTION_OWNER = (FIXTURES / "changed-action-owner.diff").read_text()
OUTSIDE_THE_ALLOWLIST = (FIXTURES / "outside-allowlist.diff").read_text()


def _run(config: str, diff: str) -> subprocess.CompletedProcess:
    # S603: the command is this interpreter and paths from this repository,
    # with the diff arriving on stdin. Nothing here comes from a caller.
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(ROOT / "src" / "pin_only.py"),
            "--config",
            str(ROOT / "examples" / f"{config}.yml"),
            "--repo-root",
            str(ROOT),
        ],
        input=diff,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("config", CONFIGS)
def test_a_plain_rev_bump_is_accepted(config: str) -> None:
    """Every configuration allows .pre-commit-config.yaml and a `rev:` bump.

    This is the case the block scalar default broke, and it broke it for only
    some configurations, which is why it needs asserting for all of them.
    """
    result = _run(config, REV_BUMP)
    assert result.returncode == 0, (
        f"{config} refused a plain rev bump:\n{result.stdout}{result.stderr}"
    )


@pytest.mark.parametrize("config", CONFIGS)
def test_a_smuggled_command_is_refused(config: str) -> None:
    result = _run(config, SMUGGLED_COMMAND)
    assert result.returncode != 0, f"{config} accepted an added shell command"


@pytest.mark.parametrize("config", CONFIGS)
def test_a_changed_action_owner_is_refused(config: str) -> None:
    """The case the line comparison exists for, rather than the allowlist."""
    result = _run(config, CHANGED_ACTION_OWNER)
    assert result.returncode != 0, f"{config} accepted a changed action owner"


@pytest.mark.parametrize("config", CONFIGS)
def test_a_path_outside_the_allowlist_is_refused(config: str) -> None:
    result = _run(config, OUTSIDE_THE_ALLOWLIST)
    assert result.returncode != 0, f"{config} accepted an edit to Makefile"


@pytest.mark.parametrize("config", CONFIGS)
def test_an_empty_diff_is_refused(config: str) -> None:
    """Nothing to read is not a clean bill of health."""
    assert _run(config, "").returncode != 0


@pytest.mark.parametrize("config", CONFIGS)
def test_a_diff_with_no_file_header_is_refused(config: str) -> None:
    assert _run(config, "some truncated output\n").returncode != 0
