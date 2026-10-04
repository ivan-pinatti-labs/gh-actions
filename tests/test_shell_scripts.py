# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""The Makefile finds the shell scripts `make coverage` measures by itself.

SHELL_SCRIPTS is discovered, not listed: every file git would commit that
ends in .sh or .bash, or whose first line is a shebang running sh, bash or
dash, minus tests/ (the tests themselves, left out the same way .coveragerc
leaves out tests/) and SHELL_EXCLUDE, plus SHELL_EXTRA. A hand list let a new
script be linted by checklist-dev-shell and then never measured, while the
figure kept reading 100%.

These tests run where `make coverage` runs them too, in a container with no
.git and no git, so they apply the same rule in Python over the tree, check
that the Makefile still carries the discovery (so a hand list cannot creep
back), and run the Makefile's own filter and awk program over sample files to
prove the two rules agree.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Scripts this repository is known to have. Discovery must find each one.
KNOWN = {"tools/fetch-originals.sh"}

_SHEBANG = re.compile(rb"^#!\s*(?:\S*/)?(?:env\s+(?:-\S+\s+)*)?(?:ba|da)?sh(?:\s|$)")


def _files() -> list[str]:
    """The files git would commit, by path relative to the root.

    `make coverage` runs this suite in a container that gets the tree as a tar
    stream of exactly those files and no .git, so there the tree itself is
    the list.
    """
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
    except OSError:  # no git at all
        listed = None
    if listed is None or listed.returncode != 0:
        return [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()]
    return [name for name in listed.stdout.decode().split("\0") if name]


def _is_shell(root: Path, path: str) -> bool:
    file = root / path
    # Only a regular file with a first line is a script. A path git still
    # lists but the tree no longer has is not in the archive `make coverage`
    # measures, a dangling link has nothing to run, and an empty file has no
    # line to measure (the Makefile's awk never sees a first line of one).
    if not file.is_file():
        return False
    with file.open("rb") as handle:
        first = handle.readline()
    if not first:
        return False
    return path.endswith((".sh", ".bash")) or bool(_SHEBANG.match(first))


def _makefile() -> str:
    return (ROOT / "Makefile").read_text().replace("\\\n", " ")


def _assignment(name: str) -> str:
    match = re.search(rf"^{name}\s*:?=(.*)$", _makefile(), re.MULTILINE)
    assert match, f"the Makefile no longer sets {name}"
    return match.group(1).strip()


def _pipeline() -> str:
    """The shell between `git ls-files` and the tests/ filter, `$$` undone."""
    match = re.search(
        r"--exclude-standard \| (xargs -0 .*) 2>/dev/null \| grep",
        _assignment("SHELL_SCRIPTS"),
    )
    assert match, "SHELL_SCRIPTS no longer filters and runs the awk discovery"
    return match.group(1).replace("$$", "$")


def discovered() -> set[str]:
    """SHELL_SCRIPTS as the Makefile's rule computes it, applied in Python."""
    exclude = set(_assignment("SHELL_EXCLUDE").split())
    extra = set(_assignment("SHELL_EXTRA").split())
    found = {p for p in _files() if not p.startswith("tests/") and _is_shell(ROOT, p)}
    return (found - exclude) | extra


def test_shebang_detection():
    assert _SHEBANG.match(b"#!/usr/bin/env bash\n")
    assert _SHEBANG.match(b"#!/bin/sh -e\n")
    assert _SHEBANG.match(b"#!/bin/dash")
    assert _SHEBANG.match(b"#! /bin/bash\n")
    assert _SHEBANG.match(b"#!/usr/bin/env -S bash -eu\n")
    assert _SHEBANG.match(b"#!/usr/local/bin/bash\n")
    assert not _SHEBANG.match(b"#!/usr/local/bin/python3\n")
    assert not _SHEBANG.match(b"#!/usr/bin/env python3\n")
    assert not _SHEBANG.match(b"#!/usr/bin/env bashful\n")
    assert not _SHEBANG.match(b"#!/bin/zsh\n")


def test_the_makefile_discovers_the_scripts():
    rule = _assignment("SHELL_SCRIPTS")
    for part in (
        "git ls-files -z --cached --others --exclude-standard",
        "xargs -0 awk",
        "grep -v '^tests/'",
        "$(filter-out $(SHELL_EXCLUDE),",
        "$(SHELL_EXTRA)",
    ):
        assert part in rule, f"SHELL_SCRIPTS no longer has {part!r}: {rule}"
    # The coverage recipe measures and grades exactly that set.
    recipe = _makefile()
    assert "$(addprefix /tmp/w/,$(SHELL_SCRIPTS))" in recipe
    assert "/out/shell.xml $(SHELL_SCRIPTS)" in recipe


def test_discovery_finds_the_known_scripts_and_no_tests():
    scripts = discovered()
    assert scripts >= KNOWN, f"discovery missed {sorted(KNOWN - scripts)}"
    assert not [p for p in scripts if p.startswith("tests/")]


def test_a_deleted_path_is_not_a_script():
    assert not _is_shell(ROOT, "tools/no-such-script.sh")


def test_the_makefile_rule_matches_the_python_rule(tmp_path):
    samples = {
        "a.sh": b"echo a\n",
        "b.bash": b"echo b\n",
        "c": b"#!/bin/sh -e\necho c\n",
        "d": b"#!/usr/bin/env -S bash -eu\n",
        "e": b"#!/bin/dash\n",
        "f": b"#! /usr/local/bin/bash\n",
        "g": b"#!/usr/bin/env python3\n",
        "h": b"#!/usr/bin/env bashful\n",
        "i.py": b"print()\n",
        "j": b"no shebang\n",
        "k.sh": b"",
    }
    for name, body in samples.items():
        (tmp_path / name).write_bytes(body)
    (tmp_path / "dir.sh").mkdir()
    (tmp_path / "dangling.sh").symlink_to("nowhere")
    # Listed first, as git lists a tracked path deleted from the tree: an awk
    # that stops at a file it cannot open would then miss everything after.
    names = ["missing.sh", "dangling.sh", "dir.sh", *sorted(samples)]
    ran = subprocess.run(
        ["sh", "-c", f"printf '%s\\0' \"$@\" | {_pipeline()}", "sh", *names],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    by_makefile = set(ran.stdout.decode().split())
    by_python = {n for n in names if _is_shell(tmp_path, n)}
    assert by_makefile == by_python == {"a.sh", "b.bash", "c", "d", "e", "f"}
