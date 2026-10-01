# Grammars

A grammar reduces a changed line to everything a version bump may **not**
change. Two lines match when their reductions are identical, so a line whose
structure changed has no counterpart and the diff is refused.

That is what makes the path allowlist a fence rather than a gesture:
`.github/workflows/` and `.pre-commit-config.yaml` are executable surfaces, so
`uses: actions/checkout@<sha>` becoming `uses: evil/checkout@<sha>` has to be
caught by the line comparison, not by the path.

## The catalogue

| Name | Matches | Reduces to |
| --- | --- | --- |
| `rev_pin` | `rev: v1.2.3` | `rev: <version>` |
| `action_sha` | `uses: o/r@<40 hex>` with an optional `# v1` comment | `uses: o/r@<version>`, comment normalized too |
| `bare_action_version` | `uses: o/r@v1`, an unpinned ref | `uses: o/r # <version>` |
| `action_ref_version` | `uses: o/r@<anything>` at end of line | `uses: o/r@<version>` |
| `image_digest` | `@sha256:...` after an image reference | `<digest>` |
| `docker_image_pin` | `FROM img:tag@sha256:...` or `ARG ...BASE_IMAGE=img:tag@sha256:...` | registry and name kept, tag and digest dropped |
| `digest` | a bare `@sha256:...` anywhere | `@sha256:<digest>` |
| `requirement_line` | `pkg==1.2.3`, extras allowed | `pkg==<version>` |
| `annotated_arg` | `ARG NAME=1.2.3` where an annotation made `NAME` eligible | `ARG NAME=<version>` |
| `arg_pin` | the same, with a stricter name and value pattern | `ARG NAME=<version>` |
| `version` | a version after `==`, `>=`, `rev:`, `VERSION=` or a bare `:` | that version only |

## The strip variants

| Name | Differs from | How |
| --- | --- | --- |
| `action_sha_strip` | `action_sha` | removes the `@<sha>` rather than substituting a placeholder |
| `bare_action_version_strip` | `bare_action_version` | same, and leaves a 40 character SHA alone |
| `digest_strip` | `digest` | removes `@sha256:...` outright |

These exist because `docker-torrent-box-with-vpn` behaved that way and the
others did not. **The difference is not cosmetic**: a reduction that removes
text and one that replaces it produce different strings, so the same diff can
match under one and not the other.

They are kept separate rather than converged for that reason. Converging one is
its own change, and `tests/test_equivalence.py` has to be extended to prove it
alters no verdict for any consumer first.

## The file level grammar

| Name | Matches | Grades |
| --- | --- | --- |
| `hash_locked_requirements` | a whole requirements file locked with `--hash=sha256:` lines | both sides read whole, and every new hash checked against PyPI |

A line grammar cannot grade a hash lock. A bump moves the version line and
replaces that package's whole run of hash lines, usually with a different
number of them (a release has as many hashes as it has wheels), so line by
line it is a pile of unmatched hashes. This grammar reads the file on both
sides instead, rebuilt from the checkout and the diff, and passes it only
when:

- the packages are the same, by name, extras and environment marker, in the
  same order: none added, none removed;
- nothing else changed: the header (the command that generated the file),
  option lines such as `--index-url` and blank lines are byte for byte
  identical, and only the indented `# via` comments under each package may
  differ;
- every requirement is pinned with `==` and carries at least one hash;
- for every package whose version or hashes changed, every hash on the new
  side is one PyPI publishes for that exact name and version, read from
  `https://pypi.org/pypi/<name>/<version>/json` (the `digests.sha256` of each
  entry under `urls`). A subset is enough: a lock may leave out wheels for
  platforms it does not resolve for.

Anything else refuses the diff with the reason, and so does a file whose base
cannot be proven to be the diff's own, a comment inside a continued line, and
PyPI being unreachable or answering with something unexpected. That last one
fails closed on purpose: a check that passes when it cannot ask is not a check.

A new transitive dependency is refused even when it is published, because it
is new code rather than a new version of code already reviewed. It waits for
a person, as any other structural change does.

### Where the PyPI lookup runs

Inside `src/pin_only.py`, so wherever the check runs: the reusable gate
workflow's job or the `pin-only` composite action, both on a GitHub hosted
runner with direct access to `pypi.org`. A runner that restricts egress has
to allow `pypi.org:443`. Only packages whose version or hashes changed are
looked up, one request each, and only for files inside `allowed_paths`.

### Configuring it

It grades a whole file, so it goes in a `rules` entry of its own, as that
rule's only grammar and without `raw`. Naming it in `default_grammars` or
beside another grammar is a configuration error. The `.in` file the lock is
compiled from is an ordinary line graded file, with `requirement_line`:

```yaml
allowed_paths:
  - tests/requirements.in
  - tests/requirements.txt

rules:
  - path: tests/requirements.txt
    grammars: [hash_locked_requirements]
  - path: tests/requirements.in
    grammars: [requirement_line]
```

The rules are matched in order, so a lock rule has to sit above any broader
`*requirements.txt` rule that would otherwise claim the same file.

### The lock it expects

Written by `uv pip compile --generate-hashes`, with the header Renovate's
`pip-compile` manager can replay. Renovate reads the command from the second
header line and runs it again with `--upgrade-package`, so the header has to
be a real `uv pip compile` command (not `--custom-compile-command`, which
Renovate refuses as a custom command), every option that takes a value has to
be written with `=`, and only options Renovate allows may appear:

```text
# This file was autogenerated by uv via the following command:
#    uv pip compile --generate-hashes --python-version=3.14 --exclude-newer=P7D --output-file=requirements.txt requirements.in
```

- `--exclude-newer=P7D`, a relative duration, and never a fixed date. Renovate
  replays the header verbatim, so a fixed date would keep excluding every
  release published after it, and each bump would fail to resolve.
- `--only-binary` is not an option Renovate allows in the header. Keep it on
  the install side, `pip install --require-hashes --only-binary=:all: -r
  tests/requirements.txt`, where it matters.

## Choosing between `version` and the specific grammars

`version` is the widest rule here and is opt in. It normalizes a version after
several operators anywhere in a line, which is convenient and correspondingly
blunt. Prefer the specific grammars where they cover the surface; reach for
`version` only where a repository already relied on it.

## Adding one

1. Add the pattern and its entry in `GRAMMARS` in `src/pin_only.py`.
2. Add a line exercising it, and a line that must **not** match it, to `LINES`
   in `tests/test_equivalence.py`.
3. Document it above.

A file level grammar, like `hash_locked_requirements`, is the exception to
step 2: it changes nothing line by line, so the equivalence corpus has
nothing to compare, and its tests live in a suite of their own
(`tests/test_pin_only_hash_locked.py`).

An unknown grammar name is a hard error, so a typo in a configuration fails
loudly rather than silently grading nothing.
