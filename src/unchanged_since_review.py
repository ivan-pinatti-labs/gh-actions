#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Whether a pull request's own changes are the same now as at the commit
CodeRabbit last finished reviewing.

Read a JSON object on stdin, `{"reviewed": <compare>, "head": <compare>}`, two
answers of GitHub's compare API, `repos/{repo}/compare/{base}...{sha}` for the
reviewed commit and for the head, and print `unchanged=<true|false>` and
`reason=<text>` on stdout, in the shape `>> "$GITHUB_OUTPUT"` expects.

Why this exists. CodeRabbit reviews incrementally, and changes that arrive by
merging the base branch into a pull request are not the pull request's own,
so after such a merge it reports `No files to review`. The gate cannot pass
that on its words alone: a push whose only changes are in files CodeRabbit
ignores reports the same thing, and has not been reviewed. What does tell
them apart is the pull request's own diff. Three dot compare is the diff of a
commit against its merge base with the base branch, which is exactly the
pull request's own change, base branch merges excluded. If it is the same at
the head as at the reviewed commit, the only thing that moved is the base,
which was reviewed in its own pull requests. If anything of the pull
request's own changed, an ignored file included, it differs, and the gate
keeps failing closed.

"The same" is compared on what a reviewer reads, not on bytes that move by
themselves: for each file, its status, its previous name for a rename, and
the lines the diff adds and removes, in order. Hunk headers and context lines
are left out, since a base branch change elsewhere in the same file shifts
both without the pull request's change moving. A file GitHub sends without a
patch (binary, or too large) is compared by the blob it ends up as instead.
Anything this cannot read fully (a compare at GitHub's 300 file limit, a
malformed answer) is `unchanged=false`: it fails closed, like the verdict.
"""

import json
import sys

# GitHub's compare API lists at most this many files; at the limit there may
# be more it did not send.
COMPARE_FILE_LIMIT = 300


def _changes(compare: dict) -> dict:
    files = compare.get("files")
    if not isinstance(files, list):
        raise ValueError("the compare answer has no files list")
    if len(files) >= COMPARE_FILE_LIMIT:
        raise ValueError(
            f"the compare answer is at GitHub's {COMPARE_FILE_LIMIT} file limit"
        )
    changes = {}
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("filename"), str):
            raise ValueError("a file entry has no filename")
        patch = entry.get("patch")
        if isinstance(patch, str):
            body = tuple(line for line in patch.split("\n") if line[:1] in ("+", "-"))
        else:
            # No patch: binary or too large. The blob it ends up as stands in,
            # and without one there is nothing to compare at all.
            sha = entry.get("sha")
            if not isinstance(sha, str) or not sha:
                raise ValueError(f"{entry['filename']} has neither a patch nor a blob")
            body = ("blob", sha)
        changes[entry["filename"]] = (
            entry.get("status"),
            entry.get("previous_filename"),
            body,
        )
    return changes


def compare_changes(data: dict) -> tuple[bool, str]:
    """(unchanged, reason) for the reviewed and head compare answers."""
    reviewed = data.get("reviewed")
    head = data.get("head")
    if not isinstance(reviewed, dict) or not isinstance(head, dict):
        raise ValueError("reviewed and head are compare answers")
    before, now = _changes(reviewed), _changes(head)
    if before.keys() != now.keys():
        added = sorted(now.keys() - before.keys())
        dropped = sorted(before.keys() - now.keys())
        named = ", ".join(added + dropped)
        return False, f"the files the pull request changes are not the same ({named})"
    for name in sorted(now):
        if before[name] != now[name]:
            return False, f"the pull request's own change to {name} is not the same"
    return True, f"the pull request's own changes to {len(now)} file(s) are the same"


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
        if not isinstance(data, dict):
            raise ValueError("stdin JSON was not an object")
        unchanged, reason = compare_changes(data)
    except ValueError as exc:
        unchanged, reason = False, f"cannot compare: {exc}"
    print(f"unchanged={'true' if unchanged else 'false'}")
    print(f"reason={' '.join(reason.split())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
