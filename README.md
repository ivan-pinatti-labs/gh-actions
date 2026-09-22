# gh-actions

[![License](https://img.shields.io/github/license/ivan-pinatti-labs/gh-actions?logo=Github&style=for-the-badge)](LICENSE.md)
[![GitHub issues](https://img.shields.io/github/issues-raw/ivan-pinatti-labs/gh-actions?logo=Github&style=for-the-badge)](https://github.com/ivan-pinatti-labs/gh-actions/issues)
[![GitHub Sponsors](https://img.shields.io/github/sponsors/ivan-pinatti?logo=Github&style=for-the-badge)](https://github.com/sponsors/ivan-pinatti)
[![GitHub Repo stars](https://img.shields.io/github/stars/ivan-pinatti-labs/gh-actions?logo=Github&style=for-the-badge)](https://github.com/ivan-pinatti-labs/gh-actions)
[![GitHub forks](https://img.shields.io/github/forks/ivan-pinatti-labs/gh-actions?logo=Github&style=for-the-badge)](https://github.com/ivan-pinatti-labs/gh-actions/forks)
[![CodeRabbit Pull Request Reviews](https://img.shields.io/coderabbit/prs/github/ivan-pinatti-labs/gh-actions?utm_source=oss&utm_medium=github&utm_campaign=ivan-pinatti-labs%2Fgh-actions&labelColor=171717&color=FF570A&label=CodeRabbit+Reviews&style=for-the-badge)](https://coderabbit.ai)

Shared GitHub Actions and reusable workflows for the `ivan-pinatti-labs` merge
pipeline.

## Why this exists

Six repositories each carried their own copy of `assert-pin-only-diff.py` and
seven carried `coderabbit-review-verdict.py`: roughly 14800 lines maintained in
parallel, six distinct variants of one 700 line script, and **only two of the
six tested it at all**. The other four ran an untested script whose verdict is
a required status check that can merge a dependency bump with nobody looking.

The cost was not theoretical. In one week, a fix to the allowlist landed in one
repository and not the other five; a grammar orphaned by another change stayed
behind in a single copy; one mechanical edit produced three different defects
across siblings; and a wrong claim reached `main` in two repositories.

## What it provides

| Piece | Kind | Consumer holds |
| --- | --- | --- |
| `pin-only` | composite action | `.github/pin-only.yml`, or inputs |
| `review-verdict` | composite action | nothing |
| `reusable-coderabbit-gate.yml` | reusable workflow | a thin caller with its own triggers |

```yaml
jobs:
  gate:
    uses: ivan-pinatti-labs/gh-actions/.github/workflows/reusable-coderabbit-gate.yml@<sha>
    permissions:
      contents: read
      pull-requests: read
      statuses: write
```

## How a fix reaches you

Pin a SHA. Renovate bumps it, and because bumping a pinned `uses:` is itself a
pin-only diff, `Pin Only` passes and the bot lane approves and merges it with
no person involved. A fix here propagates on its own.

Pin a SHA rather than a tag, always. A floating tag would resolve at run time,
so pinning the workflow would no longer pin the code that grades your merges.

## Why this is safer than a script in your repository

A repository's own gate has to check out the default branch to be sure it is
running the reviewed copy of the script, because a pull request could otherwise
rewrite the very check that decides whether it merges unattended. An action
pinned by SHA lives outside the repository entirely, so a pull request cannot
reach it at all.

The reusable workflow reads the library through `job.workflow_sha`, its own
commit, so pinning the workflow pins its grading code with it.

## Configuration

`allowed_paths` says which files a dependency bot may touch. Named grammars say
what a changed line in each of them may differ by. See
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

Both the configuration file and the caller's inputs are read from the default
branch, never from the pull request being graded, so a bot cannot widen its own
lane. The configuration file is deliberately not in its own `allowed_paths`.

## Contributing

Nothing runs on the host. `make test` builds the development container and runs
the equivalence suite inside it; `make shell` opens a shell in the same
container.

Two rules specific to this repository, both in [AGENTS.md](AGENTS.md):

- It gates seven other repositories' merges, so a change here affects all of
  them.
- Do not converge two grammars because they look alike. They decide what merges
  unattended, and `examples/` plus `tests/test_equivalence.py` exist to prove
  each consumer's behaviour is unchanged.
