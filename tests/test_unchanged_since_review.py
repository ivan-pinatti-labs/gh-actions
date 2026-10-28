# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Tests for src/unchanged_since_review.py, and the verdict it feeds.

The base case is real: ivan-pinatti-labs/github-template#144, where CodeRabbit
completed a review at 744a683, `main` was then merged in (973f720) because it
had moved the same workflow file, and CodeRabbit reported `No files to
review`. GitHub's three dot compare of `main` against each commit is below,
trimmed to the workflow file: the pull request's own lines are the same, the
blob is not, since the merge brought `main`'s pin bump into that file.
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "unchanged_since_review.py"
sys.path.insert(0, str(ROOT / "src"))
# E402: the imports have to follow the sys.path line above.
import review_verdict  # noqa: E402
import unchanged_since_review  # noqa: E402

GATE = ".github/workflows/coderabbit-gate.yml"
PATCH = (
    "@@ -35,6 +35,11 @@ name: CodeRabbit Gate\n"
    "   pull_request_target: # zizmor: ignore[dangerous-triggers]\n"
    "     types: [opened, synchronize, reopened, ready_for_review,"
    " converted_to_draft]\n"
    "   status:\n"
    "+  # CodeRabbit reports a review as a check run, with no status, since late\n"
    "+  # October 2026, so a finished review re-grades from here rather than at the\n"
    "+  # next event or sweep. The shared gate reads it with no extra permission.\n"
    "+  check_run:\n"
    "+    types: [completed]\n"
    "   schedule:\n"
    "     # Unchanged from this repository's own previous schedule.\n"
    '     - cron: "53 * * * *"'
)


def entry(name=GATE, patch=PATCH, sha="06a843de", status="modified", previous=None):
    return {
        "filename": name,
        "status": status,
        "previous_filename": previous,
        "sha": sha,
        "patch": patch,
    }


REVIEWED_BLOB = "06a843de36d1fbc2bfac0c91eca3118c619e4133"  # pragma: allowlist secret
REVIEWED = {"files": [entry(sha=REVIEWED_BLOB)]}
# The same own change after merging main: another blob, the same lines.
HEAD_BLOB = "40814f309cd4855c22e8beb0224e3a68ada6fbec"  # pragma: allowlist secret
HEAD = {"files": [entry(sha=HEAD_BLOB)]}


def run(data) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=data if isinstance(data, str) else json.dumps(data),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return dict(line.partition("=")[::2] for line in result.stdout.splitlines())


def test_a_merge_of_the_base_branch_leaves_the_change_unchanged():
    out = run({"reviewed": REVIEWED, "head": HEAD})
    assert out["unchanged"] == "true"
    assert "1 file(s) are the same" in out["reason"]


def test_hunk_positions_and_context_moving_do_not_count():
    """A base branch change elsewhere in the file shifts the hunk and its
    context, not the pull request's own lines."""
    moved = PATCH.replace("@@ -35,6 +35,11 @@", "@@ -40,6 +40,11 @@").replace(
        "53 * * * *", "11 * * * *"
    )
    out = run({"reviewed": REVIEWED, "head": {"files": [entry(patch=moved)]}})
    assert out["unchanged"] == "true"


@pytest.mark.parametrize(
    ("head", "why"),
    [
        # A push touching only a file CodeRabbit ignores: CodeRabbit says
        # `No files to review`, and this must not pass it.
        (
            {
                "files": [
                    entry(),
                    entry(name=".secrets.baseline", patch="@@ -1 +1 @@\n-a\n+b"),
                ]
            },
            "not the same (.secrets.baseline)",
        ),
        # A line of the pull request's own changed.
        (
            {
                "files": [
                    entry(patch=PATCH.replace("[completed]", "[completed, created]"))
                ]
            },
            "own change to .github/workflows/coderabbit-gate.yml",
        ),
        # A line of its own removed, or one more removed line.
        (
            {"files": [entry(patch=PATCH + "\n-  extra: removed")]},
            "own change to .github/workflows/coderabbit-gate.yml",
        ),
        # A file of its own dropped from the change.
        ({"files": []}, "not the same (.github/workflows/coderabbit-gate.yml)"),
        # The same lines under another status or another previous name.
        ({"files": [entry(status="renamed", previous="old.yml")]}, "own change to"),
    ],
)
def test_any_change_of_the_pull_requests_own_fails_closed(head, why):
    out = run({"reviewed": REVIEWED, "head": head})
    assert out["unchanged"] == "false"
    assert why in out["reason"]


@pytest.mark.parametrize(("sha", "unchanged"), [("abc", "true"), ("def", "false")])
def test_a_file_without_a_patch_is_compared_by_its_blob(sha, unchanged):
    binary = {"filename": "logo.png", "status": "added", "sha": "abc"}
    head = {"files": [dict(binary, sha=sha)]}
    out = run({"reviewed": {"files": [binary]}, "head": head})
    assert out["unchanged"] == unchanged


@pytest.mark.parametrize(
    ("data", "why"),
    [
        ("not json", "cannot compare"),
        ("[]", "not an object"),
        ({"reviewed": REVIEWED}, "are compare answers"),
        ({"reviewed": {}, "head": HEAD}, "no files list"),
        (
            {"reviewed": REVIEWED, "head": {"files": [{"status": "added"}]}},
            "no filename",
        ),
        ({"reviewed": REVIEWED, "head": {"files": ["x"]}}, "no filename"),
        # No patch and no blob on both sides would otherwise compare equal.
        (
            {
                "reviewed": {"files": [{"filename": "a.bin", "status": "added"}]},
                "head": {"files": [{"filename": "a.bin", "status": "added"}]},
            },
            "a.bin has neither a patch nor a blob",
        ),
        # An empty blob, and one that is not a string.
        (
            {"reviewed": REVIEWED, "head": {"files": [entry(patch=None, sha="")]}},
            "neither a patch nor a blob",
        ),
        (
            {"reviewed": REVIEWED, "head": {"files": [entry(patch=None, sha=1)]}},
            "neither a patch nor a blob",
        ),
        (
            {
                "reviewed": REVIEWED,
                "head": {"files": [entry(name=f"f{i}") for i in range(300)]},
            },
            "300 file limit",
        ),
    ],
)
def test_what_cannot_be_compared_fails_closed(data, why):
    out = run(data)
    assert out["unchanged"] == "false"
    assert why in out["reason"]


def test_main_in_process(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"reviewed": REVIEWED, "head": HEAD}))
    )
    assert unchanged_since_review.main() == 0
    assert capsys.readouterr().out.startswith("unchanged=true\n")


@pytest.mark.parametrize(
    ("description", "state"),
    [
        # The gate's own words, written only after the comparison above.
        (review_verdict.UNCHANGED_SINCE_REVIEW, "success"),
        # CodeRabbit's alone still fail: an ignored file push says the same.
        ("No files to review", "failure"),
    ],
)
def test_the_verdict_passes_only_the_checked_wording(description, state):
    data = {
        "author": "someone",
        "is_fork": False,
        "coderabbit_description": description,
    }
    assert review_verdict.decide(data)[0] == state
