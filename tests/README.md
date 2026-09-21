# Tests

`test_equivalence.py` is the one that made this consolidation safe to attempt.

Each of the six repositories carried its own `assert-pin-only-diff.py`, and
each decides what a dependency bot may merge unattended. A shared library that
normalized even slightly differently would either widen that lane silently or
refuse every bump, and neither is visible in a review of 700 lines of regex.

So the test runs each original's `normalize()` and this library's against the
same corpus, across every path and block scalar state that repository can see,
and requires the answers to match exactly.

Run `tools/fetch-originals.sh` first; it downloads the six originals into
`tests/originals/`, which is gitignored. The test skips rather than fails when
they are absent, so a fresh clone is not blocked on network access.

## What it caught on the first run

Two real divergences, both in `docker-torrent-box-with-vpn`, and both invisible
to reading:

- its `_normalize_action_sha` **strips** the `@<sha>` pin, where every other
  copy substitutes a placeholder for it
- its digest grammar **removes** `@sha256:...` outright, where the others
  replace it

Folding those into the other repositories' grammars would have changed which
diffs count as pin-only. They are kept as separately named grammars
(`action_sha_strip`, `bare_action_version_strip`, `digest_strip`) for exactly
that reason.

It also caught a bug in itself: `rsync-crypt`'s copy resolves its eligible ARG
names at import time, so pointing it at a fixture tree afterwards left it
comparing an empty set against a populated one. That is a harness fault, not a
library one, and the harness now recomputes them.
