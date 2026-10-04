# Security Policy

## Supported Versions

This is a template repository, so there is no released version of its own
to support. Once a project is created from this template, replace this
section with the versions of that project that receive security fixes, for
example:

| Version | Supported |
| ------- | --------- |
| 1.x     | Yes       |
| < 1.0   | No        |

## Reporting a Vulnerability

Please do not open a public issue for a security vulnerability. Instead,
use GitHub's private
[report a vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
feature on this repository, if enabled, or contact the maintainer listed in
[.github/CODEOWNERS](.github/CODEOWNERS) through their GitHub profile.

Please include as much detail as possible: steps to reproduce, affected
versions, and the potential impact. Expect an initial response within a
reasonable time, though as an individually maintained project there is no
guaranteed response window.

## What scans what

| Code | Scanned by | Where |
| --- | --- | --- |
| Python under `src/`, `tools/` and `tests/` | ruff and the rest of `checklist-dev-python` | pre-commit, every commit |
| `.github/workflows/*` | actionlint (with shellcheck over the `run:` blocks), zizmor | `checklist-github-actions`, every commit |
| Shell | shellcheck, shfmt, shebang checks | `checklist-dev-shell`, every commit |
| `Makefile` | checkmake | `checklist-dev-make`, every commit |
| Everything | detect-secrets | `checklist-security-credentials`, every commit |
| Everything SonarQube Cloud has an analyzer for: the Python, `tools/fetch-originals.sh`, the L2 `Dockerfile`, YAML, `.github/workflows/*`, secrets | SonarQube Cloud, Sonar way quality gate, plus 100% coverage through `make coverage` | `sonarqube.yml`, every pull request targeting `main` from a branch of this repository and every push to `main` |

Two layers, deliberately. The pre-commit hooks fail before anything is
pushed; SonarQube Cloud reads the whole repository at once on every pull
request targeting `main` from a branch of this repository (a fork's pull
request cannot receive its token, so its `SonarQube` check fails without a
scan and a maintainer pushes the branch here). Neither replaces the other:
Sonar's rules differ from the hooks' rules, they are not a superset of them.

SonarQube Cloud replaced CodeQL here. CodeQL only ever analyzed the Python,
and it cannot read shell or a `Dockerfile` at all. Its old alerts in the
Security tab stop updating; they are history, not current findings.

The quality gate is the Free plan's built-in "Sonar way", which cannot be
edited. It judges new code only, and fails the pull request when that new
code:

- is rated below A for reliability or security, which any new bug or any new
  vulnerability does;
- is rated below A for maintainability, which code smells do only once their
  estimated fix effort passes the A threshold (a technical debt ratio of 5%),
  not one by one;
- adds a security hotspot nobody has reviewed in SonarQube Cloud;
- duplicates more than 3% of its lines; or
- has less than 80% of its lines covered.

On a change under 20 new lines SonarQube Cloud skips the coverage and
duplication conditions; the 100% gate below still applies.

This repository holds its own code well above that floor: `make coverage`, run
by the same job, requires 100% of the lines and branches of the Python under
`src/` and `tools/` and 100% of the lines of every shell script outside
`tests/` (found by the Makefile, today `tools/fetch-originals.sh`), and
fails the job otherwise.
