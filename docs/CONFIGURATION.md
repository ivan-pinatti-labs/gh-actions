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
  - .devcontainer/l2/Dockerfile

# Grammars applied to a changed line when no rule below matches its path.
default_grammars:
  - action_sha
  - bare_action_version
  - rev_pin

# Per path overrides. The first matching rule wins, in order, so a specific
# path can sit above a directory prefix.
rules:
  # An exact path.
  - path: .devcontainer/l2/Dockerfile
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

  # A requirements file locked with hashes is graded whole, and its new
  # hashes are checked against PyPI. See GRAMMARS.md, "The file level
  # grammar".
  - path: tests/requirements.txt
    grammars: [hash_locked_requirements]

  # A suffix, when the value starts with `*`.
  - path: "*requirements.txt"
    grammars: [requirement_line]

  # `raw: true` grades the file by exact text: nothing is normalized, so any
  # edit at all is a mismatch. The strictest setting, not the loosest.
  - path: LICENSE.md
    raw: true

# Files whose annotated `ARG` names become pin eligible, for the
# `annotated_arg`, `arg_pin` and `arg_tag_commit` grammars, and whose
# annotated shell `NAME=` assignments do, for `shell_image_pin`. Read from the
# checkout, so a pull request cannot introduce its own annotation and be
# graded against it.
arg_sources:
  - file: Dockerfile
    annotations:
      - '^#\s*renovate:'

# Refuse an image pin bump whose new image was built before the one it
# replaces. Off by default in the library; `--image-age`, the reusable gate
# (`pin_only_image_age`, default true) and the composite action (`image-age`,
# default "true") turn it on. See "Image age" below.
image_age: true
```

## Image age

The line grammars prove a diff changes nothing but versions. They cannot tell
a release from a decoy: an image's tag history can hold a tag that orders above
the real version line and is an old build from another line. A dependency bot
offered `docker.io/linuxserver/qbittorrent` `5.2.2 -> 20.04.1`, a build from
2021 that passed a whole integration suite, and `docker.io/linuxserver/mylar3`
`v0.11.0-ls277 -> 3ea9b997-ls249`, an older build from another branch.

With the check on, every image pin a pin-only diff moves to another digest is
looked up in its registry, both sides, and the bump is refused when the new
image's `created` date (linux/amd64, to the second) is before the old one's.
The image is read from the line (`[registry/]name[:tag]@sha256:...`), or, for
a bare `NAME=tag@sha256:...`, from a `# renovate: ... depName=<image>`
annotation on the line directly above it.

It fails closed: a registry that cannot be reached, an image with no build date
(reproducible builds stamp the Unix epoch), or a pin whose image cannot be told
is refused, which only means the pull request waits for a person. It runs last,
and only on a diff that is otherwise pin-only, so a refused diff spends no
registry requests. Registries are asked anonymously, through the bearer
challenge Docker Hub, GHCR, GCR and Quay all answer, and a registry's token is
never sent on to the storage host its blobs redirect to.

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
