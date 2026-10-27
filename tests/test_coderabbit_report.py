# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Tests for src/coderabbit_report.py: CodeRabbit's newest report on a commit,
from its commit statuses and its check runs.

The shapes below are CodeRabbit's own, read from devcontainer-airlock#194
(statuses, before the change) and #195 (check runs, after it). They drive the
real command line over stdin, the interface the gate uses, and then the
description it prints through review_verdict.py, so each case also shows the
verdict a pull request would get.
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "src" / "coderabbit_report.py"
VERDICT = ROOT / "src" / "review_verdict.py"
sys.path.insert(0, str(ROOT / "src"))
# E402: the import has to follow the sys.path line above.
import coderabbit_report  # noqa: E402


def status(description, at, creator="coderabbitai[bot]", context="CodeRabbit"):
    return {
        "context": context,
        "description": description,
        "created_at": at,
        "creator": {"login": creator},
    }


def run(
    title,
    summary,
    at,
    status_="completed",
    slug="coderabbitai",
    name="CodeRabbit",
    conclusion="success",
):
    finished = status_ == "completed"
    return {
        "name": name,
        "status": status_,
        "conclusion": conclusion if finished else None,
        "started_at": at,
        "completed_at": at if finished else None,
        "app": {"slug": slug},
        "output": {"title": title, "summary": summary},
    }


COMPLETED = run(
    "Finished",
    "Result: Success - Review completed\nRun ID: `2bfe923d`\n| Step | Status |",
    "2026-10-27T02:40:38Z",
)
RATE_LIMITED = run(
    "Review rate limited",
    "Result: Rate limited - Review rate limited\nRun ID: `2c7035a3`",
    "2026-10-27T01:31:26Z",
    conclusion="neutral",
)
IN_PROGRESS = run(
    "Review in progress",
    "Review in progress\nRun ID: `23ae6327`",
    "2026-10-27T03:35:00Z",
    status_="in_progress",
)


def report(data) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPORT)],
        input=data if isinstance(data, str) else json.dumps(data),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def description(data) -> str:
    result = report(data)
    assert result.returncode == 0, result.stderr
    key, _, value = result.stdout.strip().partition("=")
    assert key == "description"
    return value


def verdict(text: str) -> str:
    payload = {"author": "someone", "is_fork": False, "coderabbit_description": text}
    result = subprocess.run(
        [sys.executable, str(VERDICT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return dict(line.partition("=")[::2] for line in result.stdout.splitlines())[
        "state"
    ]


@pytest.mark.parametrize(
    ("data", "text", "state"),
    [
        # #195 after the change: check runs only, no status.
        (
            {"statuses": [], "check_runs": [COMPLETED, RATE_LIMITED]},
            "Review completed",
            "success",
        ),
        (
            {"statuses": [], "check_runs": [RATE_LIMITED]},
            "Review rate limited",
            "failure",
        ),
        (
            {"statuses": [], "check_runs": [IN_PROGRESS]},
            "Review in progress",
            "pending",
        ),
        # #194 before it: statuses only, as the gate always read them.
        (
            {
                "statuses": [
                    status("Review completed", "2026-10-26T20:56:30Z"),
                    status("Review in progress", "2026-10-26T20:49:43Z"),
                    status(
                        "Review skipped: draft pull request", "2026-10-26T19:55:20Z"
                    ),
                ],
                "check_runs": [],
            },
            "Review completed",
            "success",
        ),
        # Both: a rate limited status, then a review that reported as a check
        # run (#195 at 99029e8). The newer report wins, either way round.
        (
            {
                "statuses": [status("Review rate limited", "2026-10-27T00:39:17Z")],
                "check_runs": [
                    run(
                        "Finished",
                        "Result: Success - Review completed",
                        "2026-10-27T01:28:15Z",
                    )
                ],
            },
            "Review completed",
            "success",
        ),
        (
            {
                "statuses": [status("Review rate limited", "2026-10-27T03:00:00Z")],
                "check_runs": [COMPLETED],
            },
            "Review rate limited",
            "failure",
        ),
        # Nothing yet.
        ({"statuses": [], "check_runs": []}, "", "pending"),
        ({}, "", "pending"),
    ],
)
def test_the_newest_report_is_the_one_graded(data, text, state):
    assert description(data) == text
    assert verdict(text) == state


@pytest.mark.parametrize(
    "data",
    [
        # Anything else calling itself CodeRabbit is not CodeRabbit.
        {
            "statuses": [
                status("Review completed", "2026-10-27T05:00:00Z", creator="evil[bot]")
            ]
        },
        {
            "check_runs": [
                run(
                    "Finished",
                    "Result: Success - Review completed",
                    "2026-10-27T05:00:00Z",
                    slug="evil",
                )
            ]
        },
        {
            "check_runs": [
                run(
                    "Finished",
                    "Result: Success - Review completed",
                    "2026-10-27T05:00:00Z",
                    slug=None,
                )
            ]
        },
        # Other contexts and check runs are not CodeRabbit's report.
        {
            "statuses": [
                status("Review completed", "2026-10-27T05:00:00Z", context="Pin Only")
            ]
        },
        {
            "check_runs": [
                run(
                    "Finished",
                    "Result: Success - Review completed",
                    "2026-10-27T05:00:00Z",
                    name="SonarQube",
                )
            ]
        },
        {"statuses": ["not an object"], "check_runs": [7]},
    ],
)
def test_a_report_from_anyone_else_is_ignored(data):
    assert description(data) == ""


def test_an_impostor_cannot_outrank_coderabbit():
    data = {
        "statuses": [
            status("Review completed", "2026-10-27T05:00:00Z", creator="evil[bot]")
        ],
        "check_runs": [RATE_LIMITED],
    }
    assert description(data) == "Review rate limited"


@pytest.mark.parametrize(
    ("summary", "text"),
    [
        # A summary with no Result line yields the title, which the verdict
        # does not know, so it fails closed.
        ("Something new\nRun ID: x", "Finished"),
        ("", "Finished"),
        (None, "Finished"),
    ],
)
def test_a_finished_run_this_cannot_read_fails_closed(summary, text):
    data = {"check_runs": [run("Finished", summary, "2026-10-27T05:00:00Z")]}
    assert description(data) == text
    assert verdict(text) == "failure"


def test_a_run_with_no_output_or_times_reads_as_nothing_said():
    bare = {"name": "CodeRabbit", "status": "queued", "app": {"slug": "coderabbitai"}}
    assert description({"check_runs": [bare]}) == ""


@pytest.mark.parametrize("conclusion", ["neutral", "failure", "skipped", None])
def test_completed_words_without_a_success_conclusion_fail_closed(conclusion):
    finished = run(
        "Finished",
        "Result: Success - Review completed",
        "2026-10-27T05:00:00Z",
        conclusion=conclusion,
    )
    text = description({"check_runs": [finished]})
    assert text == f"Review completed, concluded {conclusion}"
    assert verdict(text) == "failure"


@pytest.mark.parametrize(
    ("title", "conclusion", "text", "state"),
    [
        # No Result line: the title stands in, under the same conclusion check.
        (
            "Review completed",
            "neutral",
            "Review completed, concluded neutral",
            "failure",
        ),
        ("Review completed", "success", "Review completed", "success"),
        ("Review rate limited", "neutral", "Review rate limited", "failure"),
    ],
)
def test_the_title_fallback_passes_the_conclusion_check(title, conclusion, text, state):
    finished = run(
        title, "no result line", "2026-10-27T05:00:00Z", conclusion=conclusion
    )
    assert description({"check_runs": [finished]}) == text
    assert verdict(text) == state


def test_on_a_tie_the_check_run_wins():
    at = "2026-10-27T05:00:00Z"
    data = {
        "statuses": [status("Review rate limited", at)],
        "check_runs": [run("Finished", "Result: Success - Review completed", at)],
    }
    assert description(data) == "Review completed"


def test_a_newline_cannot_forge_a_second_output():
    forged = status("Review in progress\nstate=success", "2026-10-27T05:00:00Z")
    result = report({"statuses": [forged]})
    assert result.stdout == "description=Review in progress state=success\n"


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("not json", "Expecting value"),
        ("[]", "not an object"),
        ('{"statuses": {}}', "are lists"),
        ('{"check_runs": "x"}', "are lists"),
    ],
)
def test_input_outside_its_form_is_refused(raw, why):
    result = report(raw)
    assert result.returncode == 1
    assert why in result.stderr
    assert result.stdout == ""


def test_main_in_process(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"check_runs": [COMPLETED]}))
    )
    assert coderabbit_report.main() == 0
    assert capsys.readouterr().out == "description=Review completed\n"
