#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Read CodeRabbit's latest report on a commit, as the description
`review_verdict.py` grades.

Read a JSON object on stdin, `{"statuses": [...], "check_runs": [...]}`, the
commit's statuses and its `CodeRabbit` check runs as the GitHub API lists
them, and print `description=<text>` on stdout, in the shape
`>> "$GITHUB_OUTPUT"` expects. The text is empty when CodeRabbit has reported
nothing yet.

CodeRabbit reports in two ways, and a commit can carry both. Until late
October 2026 every review posted a `CodeRabbit` commit status, whose
description says what happened ("Review in progress", "Review completed",
"Review rate limited"). Since then a review reports as a `CodeRabbit` check
run instead, measured on devcontainer-airlock#195: an automatic review and
one asked for with `@coderabbitai review` alike published a check run and no
status, so a gate reading statuses alone waited for a review that had
already happened. The check run carries the same words: its title while it
runs ("Review in progress"), and the first line of its summary once it ends
("Result: Success - Review completed", "Result: Rate limited - Review rate
limited"). So both are read, and the newer report wins.

Only reports CodeRabbit itself made count. A status whose creator is not
`coderabbitai[bot]`, or a check run whose app is not `coderabbitai`, is
ignored, since anything else with `statuses: write` or `checks: write` on the
repository could call itself `CodeRabbit`. An app's slug is GitHub's own and
unique, so no other app can carry it. A report this cannot read (an unknown
shape, a summary with no `Result:` line) yields its raw title, which the
verdict does not recognize and so grades as a failure: this fails closed, the
same as the verdict does.
"""

import json
import re
import sys

STATUS_CREATOR = "coderabbitai[bot]"
APP_SLUG = "coderabbitai"
NAME = "CodeRabbit"
# "Result: Success - Review completed": the outcome, then the same words the
# commit status used to carry.
RESULT_LINE = re.compile(r"^Result: [^-]+ - (.+)$")


def _status_reports(statuses: list) -> list[tuple[str, str]]:
    reports = []
    for status in statuses:
        if not isinstance(status, dict) or status.get("context") != NAME:
            continue
        if (status.get("creator") or {}).get("login") != STATUS_CREATOR:
            continue
        reports.append(
            (str(status.get("created_at") or ""), str(status.get("description") or ""))
        )
    return reports


def _check_run_description(run: dict) -> str:
    output = run.get("output") or {}
    title = str(output.get("title") or "")
    if run.get("status") != "completed":
        # Queued or running: the title is the state ("Review in progress").
        return title
    summary = str(output.get("summary") or "")
    match = RESULT_LINE.match(summary.split("\n", 1)[0].strip())
    if not match:
        return title
    text = match.group(1).strip()
    # The words and the outcome have to agree: a completed review that did
    # not conclude `success` is not one to pass on its words alone.
    if run.get("conclusion") != "success" and text == "Review completed":
        return f"{text}, concluded {run.get('conclusion')}"
    return text


def _check_run_reports(check_runs: list) -> list[tuple[str, str]]:
    reports = []
    for run in check_runs:
        if not isinstance(run, dict) or run.get("name") != NAME:
            continue
        if (run.get("app") or {}).get("slug") != APP_SLUG:
            continue
        # A finished run reports when it finished; one still going, when it
        # started.
        when = run.get("completed_at") or run.get("started_at") or ""
        reports.append((str(when), _check_run_description(run)))
    return reports


def describe(data: dict) -> str:
    """CodeRabbit's newest report on the commit, or "" when it made none."""
    statuses = data.get("statuses", [])
    check_runs = data.get("check_runs", [])
    if not isinstance(statuses, list) or not isinstance(check_runs, list):
        raise ValueError("statuses and check_runs are lists")
    reports = _status_reports(statuses) + _check_run_reports(check_runs)
    if not reports:
        return ""
    # ISO 8601 times in UTC sort as text. On a tie the check run wins, since
    # it is the way CodeRabbit reports now.
    return max(enumerate(reports), key=lambda r: (r[1][0], r[0]))[1][1]


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
        if not isinstance(data, dict):
            raise ValueError("stdin JSON was not an object")
        description = describe(data)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    # One line: a newline in a GITHUB_OUTPUT value would let the rest be read
    # as a further output.
    print(f"description={' '.join(description.split())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
