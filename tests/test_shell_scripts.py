# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Every shell script this repository ships is held to the shell coverage.

`make coverage` measures only the scripts named in the Makefile's
SHELL_SCRIPTS, under kcov. A new script that is not added there is linted by
checklist-dev-shell and then never measured at all, and the 100% figure keeps
reading 100. This fails instead.

A shell script is a file ending in .sh or .bash, or one whose shebang runs sh,
bash or dash. Scripts under tests/ are the tests themselves, not the thing
under test, and are left out the same way .coveragerc leaves out tests/.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SHEBANG = re.compile(rb"^#!\s*(?:/usr)?/bin/(?:env\s+)?(?:sh|bash|dash)(?:\s|$)")


def _files() -> list[str]:
    """The files git would commit, by path relative to the root.

    `make coverage` runs this suite in a container that gets the tree as a tar
    stream of exactly those files and no .git, so there the tree itself is
    the list.
    """
    # No try around this: ruff's py314 target rewrites a tuple `except` into
    # the unparenthesized form, which the 3.12 coverage image cannot parse.
    listed = None
    if shutil.which("git"):
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
    if listed is None or listed.returncode != 0:
        return [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()]
    return [name for name in listed.stdout.decode().split("\0") if name]


def _is_shell(path: str) -> bool:
    if path.endswith((".sh", ".bash")):
        return True
    file = ROOT / path
    if file.is_symlink() or not file.is_file():
        return False
    with file.open("rb") as handle:
        return bool(_SHEBANG.match(handle.readline()))


def _shell_scripts_in_makefile() -> set[str]:
    text = (ROOT / "Makefile").read_text().replace("\\\n", " ")
    match = re.search(r"^SHELL_SCRIPTS\s*:?=(.*)$", text, re.MULTILINE)
    assert match, "the Makefile no longer sets SHELL_SCRIPTS"
    return set(match.group(1).split())


def test_shebang_detection():
    assert _SHEBANG.match(b"#!/usr/bin/env bash\n")
    assert _SHEBANG.match(b"#!/bin/sh -e\n")
    assert _SHEBANG.match(b"#!/bin/dash")
    assert not _SHEBANG.match(b"#!/usr/bin/env python3\n")
    assert not _SHEBANG.match(b"#!/usr/bin/env bashful\n")


def test_every_shell_script_is_measured():
    scripts = {p for p in _files() if not p.startswith("tests/") and _is_shell(p)}
    assert scripts, "found no shell scripts, so the detection itself is broken"
    missing = sorted(scripts - _shell_scripts_in_makefile())
    assert not missing, (
        "not in the Makefile's SHELL_SCRIPTS, so `make coverage` never measures"
        f" them: {missing}"
    )
