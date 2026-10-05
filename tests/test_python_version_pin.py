# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Keep every copy of "which Python" in this repository on the same version.

`ruff.toml`'s `target-version` decides which idioms `UP` rewrites to. The
`python-version` given to actions/setup-python decides which interpreter runs
the tests here and, in .github/workflows/reusable-coderabbit-gate.yml, which
one runs the library inside every consumer's CI. The Makefile's python images
run `make coverage`, `sonar.python.version` is what SonarQube Cloud judges the
code against, and each hash lock is resolved for one `--python-version`.

Nothing derives one of these from another, so they drift silently, and the
failure is quiet in the worse direction: ruff targeting a newer Python than an
interpreter that runs the code rewrites it into syntax that interpreter cannot
parse. That happened here once, with ruff on py314 and the coverage image on
3.12. Renovate does not watch the setup-python input (.github/renovate.json5
disables `uses-with` on purpose) and moves the Makefile images by digest only,
so every Python bump is a hand edit across several files. This test is the
reminder. Same idea as ivan-pinatti-labs/rsync-crypt's test of the same name.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
GATE = WORKFLOWS / "reusable-coderabbit-gate.yml"
RUFF_CONFIG = ROOT / "ruff.toml"
SONAR_PROPERTIES = ROOT / "sonar-project.properties"
MAKEFILE = ROOT / "Makefile"
LOCKS = (ROOT / "tests/requirements.txt", ROOT / "src/requirements.txt")

# `python-version: "3.14"`, quoted, as actions/setup-python is given it. YAML
# reads a bare 3.10 as the float 3.1, so an unquoted value is a bug to fail
# on, which the count check below does by not finding it.
WORKFLOW_PYTHON = re.compile(r'^\s*python-version:\s*"(\d+\.\d+)"\s*$', re.MULTILINE)
SETUP_PYTHON = re.compile(r"^\s*uses:\s*actions/setup-python@", re.MULTILINE)
RUFF_TARGET = re.compile(r'^target-version\s*=\s*"py(\d)(\d+)"\s*$', re.MULTILINE)
SONAR_PYTHON = re.compile(r"^sonar\.python\.version=(\d+\.\d+)\s*$", re.MULTILINE)
# Any python image the Makefile pins, `python:3.14-trixie@sha256:...` and the
# like, whatever variable holds it.
MAKEFILE_IMAGE = re.compile(r"/python:(\d+\.\d+)-[\w.-]+@sha256:[0-9a-f]{64}")
LOCK_HEADER = re.compile(r"^#\s+uv pip compile .*--python-version=(\d+\.\d+)\b", re.M)


def _ruff() -> str:
    found = RUFF_TARGET.search(RUFF_CONFIG.read_text())
    assert found, f"no target-version in {RUFF_CONFIG.name}"
    return f"{found.group(1)}.{found.group(2)}"


def test_every_setup_python_is_given_the_ruff_target():
    ruff = _ruff()
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        text = workflow.read_text()
        versions = WORKFLOW_PYTHON.findall(text)
        assert len(versions) == len(SETUP_PYTHON.findall(text)), (
            f"{workflow.name}: every actions/setup-python step needs a quoted "
            f"python-version, found {versions}"
        )
        for version in versions:
            assert version == ruff, (
                f"{workflow.name} runs Python {version} but {RUFF_CONFIG.name} "
                f"targets {ruff}. Both have to move together."
            )


def test_the_gate_runs_the_library_on_the_ruff_target():
    """The runner's own python3 is whatever the image ships, not ours."""
    assert WORKFLOW_PYTHON.findall(GATE.read_text()) == [_ruff()], (
        f"{GATE.name} must set up exactly one Python, the {RUFF_CONFIG.name} "
        "target, before it runs the library in a consumer's CI"
    )


def test_sonar_analyzes_as_the_ruff_target():
    found = SONAR_PYTHON.search(SONAR_PROPERTIES.read_text())
    assert found, f"no sonar.python.version in {SONAR_PROPERTIES.name}"
    assert found.group(1) == _ruff()


def test_every_makefile_python_image_is_the_ruff_target():
    images = MAKEFILE_IMAGE.findall(MAKEFILE.read_text())
    assert images, f"no digest pinned python image in {MAKEFILE.name}"
    assert set(images) == {_ruff()}, (
        f"{MAKEFILE.name} pins python images {images} but {RUFF_CONFIG.name} "
        f"targets {_ruff()}"
    )


def test_every_lock_is_resolved_for_the_ruff_target():
    for lock in LOCKS:
        found = LOCK_HEADER.findall(lock.read_text())
        assert found == [_ruff()], (
            f"{lock.relative_to(ROOT)} is compiled for {found}, not {_ruff()}"
        )
