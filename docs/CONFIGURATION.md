# Configuring the pin-only check

What a dependency bot may change in your repository without a person reading
the diff. Two surfaces, both read from the default branch and never from the
pull request being graded, so a bot cannot widen its own lane:

- a YAML file, `.github/pin-only.yml` by default
- the caller's action or workflow inputs

Both are read. An input wins over the file, key by key. A repository may use
either alone.

## Why the file is not in its own allowlist

`allowed_paths` should not list the configuration file. A bump that edits it is
then not a pin-only diff, so it fails the check and waits for a person, which
is the point: widening the lane is a decision, not a dependency update.

## Schema

```yaml
# Path prefixes a bot may touch at all. A diff naming anything else is
# refused outright, before any line is compared. Required.
allowed_paths:
  - .pre-commit-config.yaml
  - .github/workflows/
  - .devcontainer/Dockerfile

# Grammars applied to a changed line when no rule below matches its path.
default_grammars:
  - action_sha
  - bare_action_version
  - rev_pin

# Per path overrides. The first matching rule wins, in order, so a specific
# path can sit above a directory prefix.
rules:
  # An exact path.
  - path: .devcontainer/Dockerfile
    grammars: [image_digest]

  # A directory prefix, when the value ends in `/`.
  - path: .github/workflows/
    grammars:
      # `when: outside_block_scalar` skips this grammar inside a `run: |`
      # block, where the content is shell rather than YAML.
      - name: action_sha
        when: outside_block_scalar
      - name: rev_pin
        when: outside_block_scalar

  # A suffix, when the value starts with `*`.
  - path: "*requirements.txt"
    grammars: [requirement_line]

  # `raw: true` grades the file by exact text: nothing is normalized, so any
  # edit at all is a mismatch. The strictest setting, not the loosest.
  - path: LICENSE.md
    raw: true

# Files whose annotated `ARG` names become pin eligible, for the
# `annotated_arg` and `arg_pin` grammars. Read from the checkout, so a pull
# request cannot introduce its own annotation and be graded against it.
arg_sources:
  - file: Dockerfile
    annotations:
      - '^#\s*renovate:'
```

## Inputs

Equivalent to the file, for a repository that would rather keep it in the
workflow. Newline separated.

```yaml
- uses: ivan-pinatti-labs/gh-actions/pin-only@<sha>
  with:
    config: .github/pin-only.yml
    allowed-paths: |
      .pre-commit-config.yaml
      .github/workflows/
    grammars: |
      action_sha
      rev_pin
```

## Failure modes, deliberately loud

- **No `allowed_paths`** is an error, not an empty allowlist. An empty one
  would refuse every diff, which looks like a working check and is not one.
- **An unknown grammar name** is an error, not a silent no-op. A typo would
  otherwise stop grading the thing it was meant to grade, which fails open.
- **A configuration named explicitly but missing** is an error. A missing
  *default* configuration is allowed, since a repository may pass everything
  by input.

## See also

[GRAMMARS.md](GRAMMARS.md) for what each named grammar matches.
