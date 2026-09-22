# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Diff-shape verdicts for the pin-only check, ported from pre-commit-checklists.

pre-commit-checklists carried its own 541 line guard over the same grammar,
written as a standalone script that `tests/run_tests.sh` ran as a phase. It
recorded, shape by shape, what that repository's gate actually did, measured
before the expectations were written down. Adopting the shared library there
would have deleted it with the script, so it moved here instead.

Two things make it worth keeping alongside the suite ported from rsync-crypt
rather than folding into it. It is graded with examples/pre-commit-checklists.yml,
which allows a different set of pin surfaces (`checklists/`, an `arg_pin` on
the development container Dockerfile), so the same shapes are judged under a
different configuration. And its block scalar matrix covers openers the other
suite does not: a `run:` whose indicator sits on the next line, a sequence item
split from its indicator, and a comment ending in `: |` above a real opener.

`REFUSE` here means the gate sends the pull request to a person, which for an
ambiguous shape is the safe verdict rather than a bug.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "pre-commit-checklists.yml"
SCRIPT = ROOT / "src" / "pin_only.py"
# The arg_pin grammar reads its eligible ARG names from the file this
# configuration names, so the cases that do not build their own repository are
# rooted at the fetched fixture that holds pre-commit-checklists' copy.
FIXTURE_ROOT = ROOT / "tests" / "originals" / "pre-commit-checklists"

# A 40 character hex string, the shape of a GitHub Actions commit pin.
SHA = "a" * 40
OTHER_SHA = "b" * 40

WORKFLOW = ".github/workflows/pull-request.yml"
CHECKLIST = "checklists/checklist-github-actions.yaml"
DOCS = "docs/hook-catalogue.md"
DEVCONTAINER = ".devcontainer/Dockerfile"

BASE_IMAGE = "ghcr.io/ivan-pinatti-labs/devcontainer-base"
DIGEST = "4" * 64
OTHER_DIGEST = "7" * 64

ACCEPT = 0
REFUSE = 1


def _git(repo, *args: str) -> str:
    # S603/S607: git resolved from PATH, with arguments this module writes,
    # against a throwaway repository pytest created. Nothing here comes from
    # outside the test, and pinning an absolute git path would make the suite
    # depend on where the container installed it.
    return subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _grade(diff: str, repo_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(CONFIG),
            "--repo-root",
            str(repo_root),
        ],
        input=diff,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _diff(path: str, body: str) -> str:
    """Wrap changed lines in the headers a real `gh pr diff` would carry."""
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,3 +1,3 @@\n"
        f"{body}"
    )


def _in_repo(
    tmp_path,
    path: str,
    before: str,
    after: str,
    *,
    base: str | None = None,
    strip_index: bool = False,
) -> subprocess.CompletedProcess:
    """Commit `before`, diff it against `after`, grade that diff.

    The checkout the gate reads holds `base`, which defaults to `before`. A
    real `git diff` is used rather than a hand written one so the `index`
    line, which is how the gate proves the base it read is the base the diff
    was taken against, is a real blob id.

    `strip_index` removes that line, which is how a pull request diff arrives
    when the gate cannot tie it to a checkout, and forces the fallback that
    judges a pin from its diff context alone.
    """
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    # The arg_pin grammar reads eligible ARG names from the file this
    # configuration names, so the throwaway repository needs that fixture.
    fixture = FIXTURE_ROOT / DEVCONTAINER
    if path != DEVCONTAINER and fixture.exists():
        devcontainer = tmp_path / DEVCONTAINER
        devcontainer.parent.mkdir(parents=True, exist_ok=True)
        devcontainer.write_bytes(fixture.read_bytes())
    _git(tmp_path, "init", "-q")
    target.write_text(before)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    target.write_text(after)
    diff = _git(tmp_path, "diff")
    target.write_text(before if base is None else base)
    if strip_index:
        diff = "".join(
            line + "\n" for line in diff.splitlines() if not line.startswith("index ")
        )
    return _grade(diff, tmp_path)


# ---------------------------------------------------------------------------
# Shapes judged from a hand written diff, on surfaces other than a workflow
# ---------------------------------------------------------------------------

DIFF_ONLY_CASES = [
    pytest.param(
        REFUSE,
        _diff(
            WORKFLOW,
            f"-        uses: actions/checkout@{SHA} # v7\n"
            f"+        uses: actions/checkout@{OTHER_SHA} # v7\n",
        ),
        id="a pin graded from the diff alone, with no base behind it",
    ),
    pytest.param(
        REFUSE,
        _diff(
            CHECKLIST,
            "        language: python\n"
            '-        additional_dependencies: ["zizmor==1.29.0"]\n'
            '+        additional_dependencies: ["zizmor==1.30.1"]\n',
        ),
        id="the zizmor pin, which has no safe anchor and waits for a person",
    ),
    pytest.param(
        REFUSE,
        _diff(DOCS, " prose\n-pinned v1.29.0\n+pinned v1.30.1\n"),
        id="a file that is not a pin surface at all",
    ),
    pytest.param(
        ACCEPT,
        _diff(
            DEVCONTAINER,
            " # comment\n"
            f"-ARG BASE_IMAGE={BASE_IMAGE}@sha256:{DIGEST}\n"
            f"+ARG BASE_IMAGE={BASE_IMAGE}@sha256:{OTHER_DIGEST}\n",
        ),
        id="the development container base image digest moving",
    ),
    pytest.param(
        REFUSE,
        _diff(
            DEVCONTAINER,
            " # comment\n"
            f"-ARG BASE_IMAGE={BASE_IMAGE}@sha256:{DIGEST}\n"
            f"+ARG BASE_IMAGE=ghcr.io/attacker/devcontainer-base"
            f"@sha256:{OTHER_DIGEST}\n",
        ),
        id="that digest moving while the image itself is swapped",
    ),
    pytest.param(
        REFUSE,
        _diff(
            DEVCONTAINER,
            " # comment\n"
            "-RUN apt-get install -y curl\n"
            "+RUN apt-get install -y curl ca-certificates\n",
        ),
        id="an unrelated line in the development container Dockerfile",
    ),
]


@pytest.mark.parametrize(("expected", "diff"), DIFF_ONLY_CASES)
def test_diff_only_shape(expected, diff):
    result = _grade(diff, FIXTURE_ROOT)
    assert result.returncode == expected, result.stdout


# ---------------------------------------------------------------------------
# Workflow shapes, rebuilt against a real base so the file is read whole
# ---------------------------------------------------------------------------

WORKFLOW_CASES = [
    pytest.param(
        ACCEPT,
        "       - name: Checkout\n"
        f"-        uses: actions/checkout@{SHA} # v4.37.9\n"
        f"+        uses: actions/checkout@{OTHER_SHA} # v4.38.0\n",
        id="a SHA bump whose trailing release comment moves with it",
    ),
    pytest.param(
        ACCEPT,
        "       - name: Checkout\n"
        "-        uses: actions/checkout@v7\n"
        f"+        uses: actions/checkout@{SHA} # v7\n",
        id="a first time pin, its comment appearing with the SHA",
    ),
    pytest.param(
        ACCEPT,
        "     steps:\n"
        "-      - uses: actions/checkout@v7\n"
        f"+      - uses: actions/checkout@{SHA} # v7\n",
        id="a first time pin written as a bare YAML list item",
    ),
    pytest.param(
        ACCEPT,
        "       - name: Checkout\n"
        "-        uses: actions/checkout@v7\n"
        f"+        uses: actions/checkout@{SHA.upper()} # v7\n",
        id="a first time pin whose SHA is uppercase",
    ),
    pytest.param(
        REFUSE,
        "       - name: Checkout\n"
        "-        uses: actions/checkout@v7\n"
        f"+        uses: actions/checkout@{SHA}\n",
        id="a first time pin arriving with no release comment",
    ),
    pytest.param(
        REFUSE,
        "       - name: Checkout\n"
        f"-        uses: actions/checkout@{SHA} # v7 keep\n"
        f"+        uses: actions/checkout@{OTHER_SHA} # v8 changed\n",
        id="trailing text changing beside an otherwise real SHA bump",
    ),
]


@pytest.mark.parametrize(("expected", "body"), WORKFLOW_CASES)
def test_workflow_shape(tmp_path, expected, body):
    before = after = ""
    for line in body.splitlines():
        tag, text = line[:1], line[1:]
        if tag in (" ", "-"):
            before += text + "\n"
        if tag in (" ", "+"):
            after += text + "\n"
    result = _in_repo(tmp_path, WORKFLOW, before, after)
    assert result.returncode == expected, result.stdout


# ---------------------------------------------------------------------------
# Block scalar openers, judged from the whole file
# ---------------------------------------------------------------------------

STEP_WITH_COMMENT = (
    "jobs:\n"
    "  scan:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - name: Upload the scan\n"
    "        # A comment between the step's name and its uses: line, long\n"
    "        # enough that three lines of diff context above the pin never\n"
    "        # reach anything shallower than it.\n"
    "        uses: github/codeql-action/upload-sarif@{sha} # v4\n"
    "        with:\n"
    "          sarif_file: scan.sarif\n"
)
NESTED_IN_RUN = (
    "jobs:\n"
    "  build:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - name: Build\n"
    "        run: |\n"
    "          if true; then\n"
    "            uses: fake/action@{sha} # v4\n"
    "          fi\n"
)
ANCHORED_RUN = (
    "jobs:\n"
    "  build:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - name: Build\n"
    "        run: {props} |2-\n"
    "            uses: fake/action@{sha} # v4\n"
)
DASH_NAME_SIBLING = (
    "jobs:\n"
    "  scan:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - name: |\n"
    "          Upload the scan\n"
    "        uses: github/codeql-action/upload-sarif@{sha} # v4\n"
)
PROPERTIES_ON_STEP = (
    "jobs:\n"
    "  scan:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - {props} name: |\n"
    "          Upload the scan\n"
    "        uses: github/codeql-action/upload-sarif@{sha} # v4\n"
)
SPLIT_INDICATOR_RUN = (
    "jobs:\n"
    "  build:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - name: Build\n"
    "        run: {props}\n"
    "          |\n"
    "          uses: fake/action@{sha} # v4\n"
)
SEQUENCE_ITEM_SPLIT = (
    "jobs:\n"
    "  build:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - name: Build\n"
    "        run:\n"
    "          {item}\n"
    "            |\n"
    "            uses: fake/action@{sha} # v4\n"
)
COMMENT_BEFORE_OPENER = (
    "jobs:\n"
    "  build:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - name: Build\n"
    "        # note: |\n"
    "        run: &body |-\n"
    "          uses: fake/action@{sha} # v4\n"
)


def _shape_cases():
    """(expected, template, fields, base_suffix, strip_index, id)."""
    cases = []
    for props in ("&body", "!!str"):
        for strip in (False, True):
            how = "from context" if strip else "whole file"
            cases.append(
                pytest.param(
                    REFUSE,
                    ANCHORED_RUN,
                    {"props": props},
                    "",
                    strip,
                    id=f"a uses: line inside a `run: {props} |2-` block, {how}",
                )
            )
    for props in ("&step", "!!map"):
        cases.append(
            pytest.param(
                ACCEPT,
                PROPERTIES_ON_STEP,
                {"props": props},
                "",
                False,
                id=f"a step's uses: beside `- {props} name: |` is its sibling",
            )
        )
    for props in ("&body", "!!str", ""):
        for strip in (False, True):
            how = "from context" if strip else "whole file"
            cases.append(
                pytest.param(
                    REFUSE,
                    SPLIT_INDICATOR_RUN,
                    {"props": props},
                    "",
                    strip,
                    id=f"a uses: line under `run: {props}` then a lone `|`, {how}",
                )
            )
    for item in ("- &body", "- !!str", "- run:"):
        cases.append(
            pytest.param(
                REFUSE,
                SEQUENCE_ITEM_SPLIT,
                {"item": item},
                "",
                False,
                id=f"a uses: line under `{item}` then a lone `|`, whole file",
            )
        )
    cases += [
        pytest.param(
            REFUSE,
            COMMENT_BEFORE_OPENER,
            {},
            "",
            False,
            id="a comment ending in `: |` above `run: &body |-`, whole file",
        ),
        pytest.param(
            REFUSE,
            NESTED_IN_RUN,
            {},
            "",
            True,
            id="a uses: line nested inside a run: block, with no base to read",
        ),
        pytest.param(
            REFUSE,
            NESTED_IN_RUN,
            {},
            "# moved on main\n",
            False,
            id="a uses: line nested inside a run: block, main has moved the file",
        ),
        pytest.param(
            REFUSE,
            NESTED_IN_RUN,
            {},
            "",
            False,
            id="a uses: line nested deep inside a run: block, whole file",
        ),
        pytest.param(
            ACCEPT,
            DASH_NAME_SIBLING,
            {},
            "",
            False,
            id="a step's uses: beside a `- name: |` block is its sibling",
        ),
        pytest.param(
            ACCEPT,
            STEP_WITH_COMMENT,
            {},
            "",
            False,
            id="a pin whose step name sits above a comment, whole file",
        ),
        pytest.param(
            REFUSE,
            STEP_WITH_COMMENT,
            {},
            "# moved on main\n",
            False,
            id="the #105 shape when main has moved the file",
        ),
    ]
    return cases


@pytest.mark.parametrize(
    ("expected", "template", "fields", "base_suffix", "strip_index"),
    _shape_cases(),
)
def test_block_scalar_shape(
    tmp_path, expected, template, fields, base_suffix, strip_index
):
    before = template.format(sha=SHA, **fields)
    after = template.format(sha=OTHER_SHA, **fields)
    result = _in_repo(
        tmp_path,
        WORKFLOW,
        before,
        after,
        base=(before + base_suffix) if base_suffix else None,
        strip_index=strip_index,
    )
    assert result.returncode == expected, result.stdout
