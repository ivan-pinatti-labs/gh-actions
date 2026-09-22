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

An unknown grammar name is a hard error, so a typo in a configuration fails
loudly rather than silently grading nothing.
