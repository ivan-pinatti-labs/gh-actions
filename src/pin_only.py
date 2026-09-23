#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Refuse a unified diff that changes anything but a dependency pin.

Read a diff on stdin and exit non-zero unless every changed file is one of the
pin surfaces the configuration allows, and every changed line differs from its
counterpart in nothing but a version.

This is the shared implementation of a check that ran as six separate copies
across this organization until 2026-09-21. It exists because approving a bot's
pull request on the strength of its author means the bot identity holds write
access to `main`, and a diff that is not actually pin-only is exactly the shape
a compromised or misconfigured bot would take. A path allowlist alone would not
be much of a fence, since `.github/workflows/` and `.pre-commit-config.yaml`
are executable surfaces on their own; the line comparison below is what makes
it one.

The comparison normalizes both sides and requires them to match line for line
per file, duplicates counted. A line whose structure changed has no counterpart
and the diff is refused, which covers `uses: actions/checkout@v7` becoming
`uses: evil/checkout@v7` as much as it covers an added `curl | sh`. Anything
this refuses is not broken, it just waits for a person.

What it deliberately does not catch: a bump to a version that exists but is
malicious. `alpine:3.24` becoming `alpine:3.25` is the change this file exists
to permit, and no amount of diff reading can tell a good release from a
backdoored one.

## Configuration

Two surfaces that a consumer can never widen from inside a pull request,
because the workflow that runs this reads both from the default branch:

  - a YAML file, by default `.github/pin-only.yml`
  - command line flags, which override the file key by key

Both are read; flags win. See docs/CONFIGURATION.md for the schema and
docs/GRAMMARS.md for what each named grammar matches.
"""

import argparse
import hashlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

RELEASE = r"v?[0-9][0-9A-Za-z.+_-]*"

# A pre-commit hook `rev:`. The prefix is captured and put back, so that a
# pin changing shape rather than value still reads as a difference.
#
# GitHub Actions pins are handled separately below rather than through this
# same released-version grammar: this repository, like the one it was ported
# from, pins every action to a full commit SHA rather than a tag (see any
# `uses:` line in .github/workflows/), so the immutable shape to require
# there is a SHA, not a release number.
REV_PIN = re.compile(r"(?P<prefix>\brev:[ \t]+)" + RELEASE)

# A GitHub Actions pin, always a full 40 character commit SHA in this
# repository (the dependency bot updates it that way), optionally followed
# by a trailing release comment (`# v7`, `# v4.38.0`), which the bot
# rewrites on the same bump whenever the tag it resolves the SHA from
# changes.
#
# Both have to normalize together, and this script did not do that until
# now: it normalized only the SHA and left the comment as ordinary text, so
# an ordinary bump that also moved `# v4.37.9` to `# v4.38.0` compared as
# `@<version> # v4.37.9` against `@<version> # v4.38.0`, read as a
# structural change, and `Pin Only` refused it. Since every Renovate action
# bump rewrites that comment, no action SHA bump could ever be approved
# here: the only four pull requests ever merged unattended in this
# repository were three asdf tool version bumps (from the `.tool-versions`
# file that asdf's removal deleted) and one `.pre-commit-config.yaml` rev
# bump, and #105 is the one that finally
# surfaced it. github-template,
# pre-commit-checklists and pre-commit-checklists-demo have carried the
# fix below for some time; this copy had simply never received it, and its
# own tests pinned `# v7` on both sides of the bump, so nothing caught the
# shape that actually occurs.
#
# The comment is folded into the same placeholder only when it is a release
# token, so a change to unrelated trailing text after the SHA is still
# caught as structural. The negative lookahead stops a
# 40 character prefix of a longer hex run from matching and silently
# swallowing the character that would have made the shapes differ.
#
# Case-insensitive (`[0-9a-fA-F]`, not `[0-9a-f]`): GitHub resolves a
# `uses:` SHA the same way regardless of case, so an uppercase or
# mixed-case SHA is just as real a pin as a lowercase one, and matching
# only lowercase left a gap a CodeRabbit review of BARE_ACTION_VERSION
# below found: an uppercase SHA on a first-time pin's new side fell
# through ACTION_SHA entirely and was accepted by BARE_ACTION_VERSION's
# generic RELEASE grammar instead, which does not check that a
# first-time pin's target is SHA-shaped at all.
#
# Anchored to a genuine `uses:` field at the start of the line, the same
# anchor BARE_ACTION_VERSION uses, rather than a bare `@<sha>` matched
# anywhere: a follow-up CodeRabbit finding on this exact pattern pointed
# out the original, unanchored ACTION_SHA matched a 40 character hex run
# on ANY changed workflow line, `run:` step content included, so a `run:`
# command could change while its normalized form stayed equal, as long as
# the line still ended in something SHA-shaped. `prefix` now captures the
# full `uses: owner/repo@` text, not only `@`, so the dependency name
# stays literal to the left exactly as it already did.
ACTION_SHA = re.compile(
    r"(?P<prefix>^(?:[ \t]*-[ \t]+)?[ \t]*uses:[ \t]+[\w.-]+/[\w./-]+@)"
    r"[0-9a-fA-F]{40}(?![0-9a-fA-F])"
    r"(?P<comment>[ \t]+#[ \t]*" + RELEASE + r")?"
)

BARE_ACTION_VERSION = re.compile(
    r"(?P<action_prefix>^(?:[ \t]*-[ \t]+)?[ \t]*uses:[ \t]+[\w.-]+/[\w./-]+)@"
    r"(?P<bare_version>" + RELEASE + r")$"
)


# way a swapped owner is for a `uses:` pin.
IMAGE_DIGEST = re.compile(
    r"(?P<prefix>^ARG [A-Z0-9_]+=[\w./-]+(?::[\w.-]+)?@)sha256:[0-9a-f]{64}$"
)

FILE_HEADER = re.compile(r"^diff --git a/(?P<old>.+) b/(?P<new>.+)$")
# The blob ids a diff's preamble names for each side, and a hunk's starting
# line and length on each side (a length of one is written by omitting it).
INDEX_LINE = re.compile(
    r"^index (?P<old>[0-9a-f]{7,64})\.\.[0-9a-f]{7,64}(?: [0-7]{6})?$"
)
HUNK_HEADER = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_len>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_len>\d+))? @@"
)

# real step. Confirmed with PyYAML before the fix.
BLOCK_SCALAR_OPENER = re.compile(
    r"(?::|^[ \t]*-)(?:[ \t]+[&!]\S*)*\s*[|>](?:[+-][1-9]?|[1-9][+-]?)?"
    r"(?:[ \t]+#.*)?\s*$"
)
# The sequence markers leading a line, each a dash followed by whitespace,
# and the node properties (anchors, tags) that may lead a node after one.
SEQUENCE_MARKER = re.compile(r"-[ \t]+")
NODE_PROPERTIES = re.compile(r"(?:[&!]\S*(?:[ \t]+|$))*")
# A block scalar indicator alone on its line, optionally after node
# properties: the value of the key on an earlier line. `run: &body` or a
# bare `run:` followed by an indented `|` is as much a block scalar as
# `run: |` (confirmed with PyYAML), and its content may sit at the very
# column of that `|`. A CodeRabbit review found the scan missed it.
STANDALONE_INDICATOR = re.compile(
    r"^[ \t]*(?:[&!]\S*[ \t]+)*[|>](?:[+-][1-9]?|[1-9][+-]?)?"
    r"(?:[ \t]+#.*)?\s*$"
)


# Grammars that only one repository needed until these copies were merged.
# Each is kept as its own named rule rather than folded into a more general
# one, because these decide what a dependency bot is allowed to merge
# unattended: a regex that quietly matches more than its old copy did would
# widen that lane without anyone reading a diff about it. Converging them is a
# later change, with a differential test to prove it changes no verdict.

# A Dockerfile base image pinned by tag and digest together, on a `FROM` or on
# an `ARG ...BASE_IMAGE=`. Both the tag and the digest move on a bump.
DOCKER_IMAGE_PIN = re.compile(
    r"(?P<prefix>^(?:FROM[ \t]+(?:--platform=\S+[ \t]+)?"
    r"|ARG[ \t]+[A-Za-z0-9_]*BASE_IMAGE=)"
    r"[A-Za-z0-9._/-]+:)"
    r"[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}[ \t]*$"
)

# A pip requirement pinned with `==`, optionally carrying extras.
REQUIREMENT_LINE = re.compile(
    r"^(?P<prefix>[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(?:\[[A-Za-z0-9,._-]+\])?==)" + RELEASE + r"[ \t]*$"
)

# An `ARG NAME=<release>` whose name an annotation above it made eligible.
ARG_PIN = re.compile(
    r"^(?P<prefix>ARG[ \t]+(?P<name>[A-Z][A-Z0-9_]*)=)" + RELEASE + r"[ \t]*$"
)

# A bare digest anywhere in the line.
DIGEST = re.compile(r"@sha256:[0-9a-f]{7,}")

# An action ref that is not a SHA pin: a first time pin's unpinned side.
ACTION_REF_VERSION = re.compile(
    r"(?P<prefix>^(?:[ \t]*-[ \t]+)?[ \t]*uses:[ \t]+[\w.-]+/[\w./-]+)"
    r"@[0-9A-Za-z][0-9A-Za-z.+_-]*$"
)

# The broad operator-anchored version grammar docker-torrent-box-with-vpn
# carried. Deliberately the widest rule in this file, and deliberately
# opt-in: it normalizes a version after `==`, `>=`, `rev:`, a `VERSION=`
# assignment, or a bare `:` after a non-space. Nothing enables it unless its
# configuration names it.
VERSION = re.compile(
    r"(?P<prefix>==|>=|(?<=VERSION)=|\brev:[ \t]+|(?<=\S):)"
    r"[0-9A-Za-z][0-9A-Za-z.+_-]*"
)

# `ARG NAME=` lines, and the annotation comment that can precede one.
ARG_LINE = re.compile(r"^ARG (?P<name>[A-Z0-9_]+)=(?P<value>\S*)$")
ARG_VALUE = re.compile(r"(?P<prefix>^ARG [A-Z0-9_]+=)\S*$")


def _normalize_action_pin(match: re.Match[str]) -> str:
    """Collapse a `@<sha>` pin and its optional trailing release comment."""
    normalized = f"{match.group('prefix')}<version>"
    if match.group("comment"):
        normalized += " # <version>"
    return normalized


def _normalize_bare_action_version(match: re.Match[str]) -> str:
    # `# <version>` is appended here too, matching what _normalize_action_pin
    # produces for the pinned side: a first-time pin gains its release
    # comment in the same edit that gains the SHA, so the placeholder has to
    # carry one for the two sides to compare equal.
    if len(match.group("bare_version")) == 40:
        return match.group(0)
    return f"{match.group('action_prefix')}@<version> # <version>"


# A `uses:` reference and the ref it points at, either side of the `@`. Used
# only by the depin check below, which needs the raw ref rather than the
# normalized placeholder the grammars produce.
ACTION_REF = re.compile(r"uses:[ \t]*(?P<action>[\w.-]+/[\w./-]+)@(?P<ref>[^\s'\"#]+)")
SHA_REF = re.compile(r"^[0-9a-fA-F]{40}$")


def _depinned_actions(diff: str) -> list[str]:
    """Actions a diff moves off a commit SHA and onto a mutable ref.

    `bare_action_version` normalizes a bare `@v8` to the same placeholder
    `action_sha` produces for `@<sha> # v8`, and that is deliberate: it is
    what lets Renovate's first-time pin, `@v7` becoming `@<sha> # v7`, grade
    as a pin bump rather than as a structural change.

    Normalization is symmetric, so on its own it accepts that same edit
    backwards. `@<sha> # v7` becoming `@v8` normalizes to the identical
    placeholder on both sides and reads as pin-only, while actually replacing
    an immutable pin with a tag the upstream owner can move at will. The
    line-by-line comparison cannot see direction, because by then both sides
    are placeholders, so direction is checked here on the raw diff instead.

    Reported per action rather than per line: the question is whether a given
    action lost its SHA, not how many lines mention it.
    """
    was_pinned: dict[str, set[str]] = {}
    now_loose: dict[str, set[str]] = {}
    path = ""
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.split(" b/", 1)[-1] if " b/" in line else ""
            continue
        if not line or line[0] not in "+-" or line.startswith(("---", "+++")):
            continue
        match = ACTION_REF.search(line[1:])
        if not match:
            continue
        pinned = bool(SHA_REF.match(match.group("ref")))
        if line[0] == "-" and pinned:
            was_pinned.setdefault(path, set()).add(match.group("action"))
        elif line[0] == "+" and not pinned:
            now_loose.setdefault(path, set()).add(match.group("action"))

    problems = []
    for path in sorted(was_pinned):
        for action in sorted(was_pinned[path] & now_loose.get(path, set())):
            problems.append(
                f"{path}: {action} moved off its commit SHA and onto a "
                f"mutable ref, which is a depin, not a pin bump"
            )
    return problems


def _annotated_arg_names(path: Path, annotation: re.Pattern[str]) -> frozenset[str]:
    """Read the ARG names an annotation comment makes eligible in one file.

    Read from the file rather than from the diff on purpose. The workflow that
    runs this checks out the default branch, so these names come from the
    reviewed copy; letting a pull request introduce its own annotation and then
    be graded against it would let a bump annotate whatever it liked.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    names, annotated = set(), False
    for line in lines:
        if annotation.match(line.strip()):
            annotated = True
            continue
        arg = ARG_LINE.match(line)
        if arg and annotated:
            names.add(arg.group("name"))
        annotated = False
    return frozenset(names)


@dataclass(frozen=True)
class ArgSource:
    """A Dockerfile whose annotated ARG names are pin eligible."""

    file: str
    annotations: tuple[str, ...]


@dataclass(frozen=True)
class Grammar:
    """One grammar in a rule, and when it applies.

    `when` is `always` or `outside_block_scalar`. The second exists because a
    block scalar (`run: |`) holds shell, not YAML, and most repositories do not
    want an action-pin grammar rewriting script text. It is per grammar rather
    than per rule because docker-torrent-box-with-vpn deliberately keeps its
    digest and version grammars running inside block scalars while skipping the
    action ones, and a rule-level flag could not say that.
    """

    name: str
    when: str = "always"

    def applies(self, in_block_scalar: bool) -> bool:
        return not (in_block_scalar and self.when == "outside_block_scalar")


@dataclass(frozen=True)
class PathRule:
    """What to do with a changed line, keyed by the path it is in.

    `match` is an exact path, a prefix when it ends in `/`, or a suffix when it
    starts with `*`. The first matching rule wins, in configuration order, so a
    specific path can sit above a directory prefix.
    """

    match: str
    grammars: tuple[Grammar, ...] = ()
    raw: bool = False

    def matches(self, path: str) -> bool:
        if self.match.endswith("/"):
            return path.startswith(self.match)
        if self.match.startswith("*"):
            return path.endswith(self.match[1:])
        return path == self.match


@dataclass(frozen=True)
class Config:
    """Everything about one repository's pin surfaces."""

    allowed_paths: tuple[str, ...] = ()
    default_grammars: tuple[Grammar, ...] = ()
    rules: tuple[PathRule, ...] = ()
    arg_sources: tuple[ArgSource, ...] = ()
    repo_root: Path = Path(".")

    def rule_for(self, path: str) -> PathRule | None:
        for rule in self.rules:
            if rule.matches(path):
                return rule
        return None


# Every grammar this script knows, by the name a configuration uses for it.
# A name that is not in here is a configuration error rather than a silent
# no-op: a typo in a grammar name would otherwise quietly stop grading the
# thing it was meant to grade, which fails open.
GRAMMARS: dict[str, object] = {
    "rev_pin": lambda line, cfg: REV_PIN.sub(r"\g<prefix><version>", line),
    "action_sha": lambda line, cfg: ACTION_SHA.sub(_normalize_action_pin, line),
    "bare_action_version": lambda line, cfg: BARE_ACTION_VERSION.sub(
        _normalize_bare_action_version, line
    ),
    "action_ref_version": lambda line, cfg: ACTION_REF_VERSION.sub(
        r"\g<prefix>@<version>", line
    ),
    "image_digest": lambda line, cfg: IMAGE_DIGEST.sub(r"\g<prefix><digest>", line),
    "docker_image_pin": lambda line, cfg: DOCKER_IMAGE_PIN.sub(
        lambda m: f"{m.group('prefix')}<version>", line
    ),
    "digest": lambda line, cfg: DIGEST.sub("@sha256:<digest>", line),
    "digest_strip": lambda line, cfg: DIGEST.sub("", line),
    "action_sha_strip": lambda line, cfg: ACTION_SHA_STRIP.sub(_strip_action_sha, line),
    "bare_action_version_strip": lambda line, cfg: BARE_ACTION_VERSION_STRIP.sub(
        _strip_bare_action_version, line
    ),
    "requirement_line": lambda line, cfg: REQUIREMENT_LINE.sub(
        r"\g<prefix><version>", line
    ),
    "version": lambda line, cfg: VERSION.sub(r"\g<prefix><version>", line),
    "annotated_arg": lambda line, cfg: _normalize_annotated_arg(line, cfg),
    "arg_pin": lambda line, cfg: ARG_PIN.sub(
        lambda m: (
            f"{m.group('prefix')}<version>"
            if m.group("name") in _eligible_arg_names(cfg)
            else m.group(0)
        ),
        line,
    ),
}


# docker-torrent-box-with-vpn's variants of the two action grammars and the
# digest one. They are not cosmetic differences: where the grammars above
# substitute a placeholder for the pin, these three remove it outright. Running
# one repository's diff through the other's grammar changes what counts as a
# matching line, so both live here under distinct names until a differential
# test proves one can replace the other.
ACTION_SHA_STRIP = re.compile(
    r"(?P<uses_prefix>^(?:[ \t]*-[ \t]+)?[ \t]*uses:[ \t]+[\w.-]+/[\w./-]+)"
    r"@[0-9a-fA-F]{40}(?![0-9a-fA-F])(?P<comment>[ \t]+#[ \t]*" + RELEASE + r")?$"
)

BARE_ACTION_VERSION_STRIP = re.compile(
    r"(?P<action_prefix>^(?:[ \t]*-[ \t]+)?[ \t]*uses:[ \t]+[\w.-]+/[\w./-]+)@"
    r"(?P<bare_version>" + RELEASE + r")$"
)


def _strip_action_sha(match: re.Match[str]) -> str:
    """Strip a `@<sha>` action pin, normalizing its trailing release comment."""
    prefix = match.group("uses_prefix")
    if match.group("comment"):
        return f"{prefix} # <version>"
    return prefix


def _strip_bare_action_version(match: re.Match[str]) -> str:
    """Strip a bare `@<version>` ref, leaving a 40 character SHA alone."""
    if len(match.group("bare_version")) == 40:
        return match.group(0)
    return f"{match.group('action_prefix')} # <version>"


def _eligible_arg_names(cfg: "Config") -> frozenset[str]:
    """Every ARG name an annotation makes pin eligible, across all sources."""
    eligible: set[str] = set()
    for source in cfg.arg_sources:
        for annotation in source.annotations:
            eligible |= _annotated_arg_names(
                cfg.repo_root / source.file, re.compile(annotation)
            )
    return frozenset(eligible)


def _normalize_annotated_arg(line: str, cfg: "Config") -> str:
    """Normalize an ARG whose name an annotation made eligible, and nothing else."""
    arg = ARG_LINE.match(line)
    if not arg:
        return line
    eligible = _eligible_arg_names(cfg)
    if arg.group("name") in eligible and re.fullmatch(RELEASE, arg.group("value")):
        return ARG_VALUE.sub(r"\g<prefix><version>", line)
    # Not eligible, or the value is not a release on its own: returned
    # unchanged either way, so the edit shows up as a structural mismatch
    # instead of being waved through.
    return line


def _grammars(entries: list) -> tuple[Grammar, ...]:
    """Read a grammar list, where each entry is a name or a {name, when} map."""
    out: list[Grammar] = []
    for entry in entries:
        if isinstance(entry, str):
            out.append(Grammar(name=entry))
        elif isinstance(entry, dict) and "name" in entry:
            out.append(
                Grammar(
                    name=str(entry["name"]),
                    when=str(entry.get("when", "always")),
                )
            )
        else:
            sys.exit(
                "pin-only: a grammar entry must be a name or a mapping with "
                f"`name`, got: {entry!r}"
            )
    return tuple(out)


def _require_yaml():
    try:
        import yaml
    except ModuleNotFoundError:  # pragma: no cover - environment dependent
        sys.exit(
            "pin-only: PyYAML is required to read a configuration file. "
            "Install python3-yaml, or pass the configuration with flags."
        )
    return yaml


def load_config(
    path: Path | None,
    repo_root: Path,
    overrides: dict[str, object] | None = None,
) -> Config:
    """Build a Config from a YAML file, then apply flag overrides key by key.

    A missing file is only an error when it was named explicitly. The default
    location being absent means "this repository configures everything by
    flag", which is a legitimate way to use this.
    """
    data: dict[str, object] = {}
    if path is not None:
        if path.is_file():
            data = _require_yaml().safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                sys.exit(f"pin-only: {path} does not contain a YAML mapping.")
        elif overrides is None or "config_was_explicit" in (overrides or {}):
            sys.exit(f"pin-only: no such configuration file: {path}")

    rules: list[PathRule] = []
    for raw in data.get("rules", []) or []:
        if not isinstance(raw, dict) or "path" not in raw:
            sys.exit("pin-only: every entry under `rules` needs a `path`.")
        rules.append(
            PathRule(
                match=str(raw["path"]),
                grammars=_grammars(raw.get("grammars", []) or []),
                raw=bool(raw.get("raw", False)),
            )
        )

    arg_sources: list[ArgSource] = []
    for raw in data.get("arg_sources", []) or []:
        if not isinstance(raw, dict) or "file" not in raw:
            sys.exit("pin-only: every entry under `arg_sources` needs a `file`.")
        arg_sources.append(
            ArgSource(
                file=str(raw["file"]),
                annotations=tuple(str(a) for a in raw.get("annotations", []) or []),
            )
        )

    config = Config(
        allowed_paths=tuple(data.get("allowed_paths", []) or []),
        default_grammars=_grammars(data.get("default_grammars", []) or []),
        rules=tuple(rules),
        arg_sources=tuple(arg_sources),
        repo_root=repo_root,
    )

    for key, value in (overrides or {}).items():
        if key == "allowed_paths" and value:
            config = replace(config, allowed_paths=tuple(value))
        elif key == "default_grammars" and value:
            config = replace(config, default_grammars=_grammars(list(value)))

    _validate(config)
    return config


def _validate(config: Config) -> None:
    """Refuse a configuration that would grade less than it looks like it does."""
    if not config.allowed_paths:
        sys.exit(
            "pin-only: no allowed_paths configured, so every diff would be "
            "refused. Set them in the configuration file or with --allowed-path."
        )
    named = {g.name for g in config.default_grammars}
    for rule in config.rules:
        named |= {g.name for g in rule.grammars}
    unknown = sorted(named - set(GRAMMARS))
    if unknown:
        sys.exit(
            "pin-only: unknown grammar(s): "
            + ", ".join(unknown)
            + ". Known: "
            + ", ".join(sorted(GRAMMARS))
        )
    for grammar in config.default_grammars + tuple(
        g for rule in config.rules for g in rule.grammars
    ):
        if grammar.when not in {"always", "outside_block_scalar"}:
            sys.exit(
                f"pin-only: grammar {grammar.name!r} has when={grammar.when!r}; "
                "expected 'always' or 'outside_block_scalar'."
            )


# The configuration the module-level helpers read when none is passed in.
_ACTIVE = Config()


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _block_scalar_floor(line: str) -> int:
    """The indentation a block scalar opened on `line` has to exceed.

    For `key: |` that is the key's own column. After a sequence marker,
    `- name: |`, it is still the key's column rather than the dash's: YAML
    reads a line starting at that column as the key's sibling, not as
    scalar content (confirmed with PyYAML), so a step's `uses:` beside a
    `- name: |` is ordinary structure. Only when the sequence item itself
    is the scalar, `- |` or `- &body |`, is the dash the floor. Properties
    leading a compact mapping, `- &step name: |`, belong to the mapping,
    which starts where they do, so they are skipped before deciding.
    """
    column = _line_indent(line)
    rest = line[column:]
    while True:
        marker = SEQUENCE_MARKER.match(rest)
        if not marker:
            return column
        after = rest[marker.end() :]
        value = after[NODE_PROPERTIES.match(after).end() :]
        if not value or value[0] in "|>":
            return column
        column += marker.end()
        rest = after


def _standalone_floor() -> int:
    """The floor of a block scalar whose indicator stands alone on its line.

    None at all: every later line in the file counts as its content. Which
    node owns a lone indicator, and so where its content may start, depends
    on lines above it (a bare `- &body`, a property on a line of its own, an
    explicit indentation digit measured from that owner), and each attempt
    to derive it from them was found to under-mark some valid YAML, fuzzed
    against PyYAML. No workflow here uses a lone indicator, so treating the
    rest of the file as content costs nothing today and only ever refuses
    more: a pin below one waits for a person.
    """
    return -1


def _block_scalar_lines(lines: list[str]) -> list[bool]:
    """Mark every line of a whole YAML file as inside a block scalar or not.

    Walks the file top to bottom. After a line opening a block scalar,
    every following line that is blank or indented deeper than the opener
    is that scalar's literal content, until a non-blank line at or below
    the opener's own indentation closes it. Content is never read as an
    opener itself, which three lines of diff context never could
    guarantee: a `uses:` nested under an `if` inside a `run: |` block is
    content here, however deep. A line that merely looks like an opener
    marks what follows as content, which only ever refuses more; comment
    lines are the exception and are skipped (see below).
    """
    marks: list[bool] = []
    floor: int | None = None
    for line in lines:
        if floor is not None:
            if not line.strip() or _line_indent(line) > floor:
                marks.append(True)
                continue
            floor = None
        marks.append(False)
        # Outside a scalar, a line starting with `#` is a comment, never an
        # opener: reading `# note: |` as one would mark what follows as its
        # content, and a real opener among those lines would go unseen.
        # Fuzzing against PyYAML found exactly that.
        if line.lstrip().startswith("#"):
            continue
        if BLOCK_SCALAR_OPENER.search(line):
            floor = _block_scalar_floor(line)
        elif STANDALONE_INDICATOR.match(line):
            floor = _standalone_floor()
    return marks


def _git_blob_id(data: bytes) -> str:
    # git's own object id, recomputed to compare against the diff's `index`
    # line. It identifies a file version rather than guarding one: what
    # actually holds `_apply_hunks` honest is that every context and removed
    # line must match the base, which no hash collision can fake.
    header = b"blob %d\0" % len(data)
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def _base_lines(path: str, blob: str) -> list[str] | None:
    """The file's base side read from the checkout, or None if it is not
    provably the same file the diff was taken against.

    coderabbit-gate.yml checks out the default branch, never the pull
    request's head, so this reads the file as it stands on main. That is
    the diff's own base only while main has not moved the file since the
    pull request branched, which is what comparing the git blob id against
    the diff's `index` line proves. If main has moved it, or the path
    leaves the checkout, the answer is None and every pin in the file is
    refused.
    """
    root = _ACTIVE.repo_root.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    data = target.read_bytes()
    if not _git_blob_id(data).startswith(blob):
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _apply_hunks(
    base: list[str], hunks: list[tuple[re.Match[str], list[str]]]
) -> list[str] | None:
    """Rebuild the file's head side from its base and the diff's hunks.

    Every context and removed line has to match the base where the hunk
    header says it sits, every hunk has to land where its header says it
    does on the head side too, and each hunk body has to carry exactly the
    line counts its header declares on both sides. Any disagreement means
    the diff and the base are not describing the same file, or the diff
    was cut short, and the answer is None.
    """
    head: list[str] = []
    cursor = 0
    for header, body in hunks:
        old_len = int(header.group("old_len") or 1)
        new_len = int(header.group("new_len") or 1)
        start = int(header.group("old_start")) - (1 if old_len else 0)
        if start < cursor:
            return None
        head.extend(base[cursor:start])
        if len(head) != int(header.group("new_start")) - (1 if new_len else 0):
            return None
        position = start
        added = 0
        for line in body:
            tag, content = (line[:1], line[1:]) if line else (" ", "")
            if tag in (" ", "-"):
                if position >= len(base) or base[position] != content:
                    return None
                position += 1
                if tag == " ":
                    head.append(content)
                    added += 1
            elif tag == "+":
                head.append(content)
                added += 1
            elif tag != "\\":
                return None
        if position - start != old_len or added != new_len:
            return None
        cursor = position
    head.extend(base[cursor:])
    return head


def _whole_file_block_scalars(
    diff_lines: list[str],
) -> dict[str, tuple[list[bool], list[bool]]]:
    """Block scalar marks for each side of every workflow file whose base
    can be read whole and proven to be the diff's own.

    Keyed by path; each value holds the base side's marks and the head
    side's, indexed by line number minus one. A file missing from the
    result has every line treated as block scalar content, so any pin in it
    is refused (see `parse`). Only `.github/workflows/` is read, the one
    place `normalize` consults the answer.
    """
    files: dict[str, tuple[str | None, list[tuple[re.Match[str], list[str]]]]] = {}
    path = None
    for line in diff_lines:
        header = FILE_HEADER.match(line)
        if header:
            same = header.group("old") == header.group("new")
            path = header.group("new") if same else None
            if path is not None:
                files[path] = (None, [])
            continue
        if path is None:
            continue
        blob, hunks = files[path]
        hunk = HUNK_HEADER.match(line)
        if hunk:
            hunks.append((hunk, []))
        elif hunks:
            hunks[-1][1].append(line)
        else:
            index = INDEX_LINE.match(line)
            if index:
                files[path] = (index.group("old"), hunks)

    marks: dict[str, tuple[list[bool], list[bool]]] = {}
    for path, (blob, hunks) in files.items():
        if not path.startswith(".github/workflows/") or not blob or not hunks:
            continue
        if not blob.strip("0"):
            continue
        base = _base_lines(path, blob)
        if base is None:
            continue
        head = _apply_hunks(base, hunks)
        if head is None:
            continue
        marks[path] = (_block_scalar_lines(base), _block_scalar_lines(head))
    return marks


def normalize(
    line: str,
    path: str = "",
    in_block_scalar: bool = False,
    config: Config | None = None,
) -> str:
    """Reduce a line to everything about it that a version bump may not change."""
    cfg = config if config is not None else _ACTIVE
    rule = cfg.rule_for(path)

    # A rule marked `raw` grades its file by exact text. That is the strictest
    # setting, not the loosest: nothing is normalized, so any edit at all
    # inside that file is a structural mismatch.
    if rule is not None and rule.raw:
        return line

    grammars = rule.grammars if rule is not None else cfg.default_grammars
    for grammar in grammars:
        if grammar.applies(in_block_scalar):
            line = GRAMMARS[grammar.name](line, cfg)
    return line


def parse(diff: str) -> tuple[dict[str, tuple[Counter, Counter]], list[str]]:
    """Group removed and added lines by file, and collect structural changes."""
    changes: dict[str, tuple[Counter, Counter]] = {}
    structural: list[str] = []
    path = None
    in_hunk = False
    # Whole-file marks where the base could be proven, and each side's
    # current line number (zero based) to look a line up in them by. With no
    # marks, every line counts as block scalar content: three lines of diff
    # context cannot prove a line sits outside a `run: |` body, and judging
    # from them was a documented gap (a `uses:` line under an `if` inside
    # one read as a step). A workflow diff whose base cannot be proven is
    # therefore refused, and waits for the dependency bot to rebase it onto
    # main, where it can be.
    diff_lines = diff.splitlines()
    whole_file = _whole_file_block_scalars(diff_lines)
    marks = None
    old_number = new_number = 0

    for line in diff_lines:
        header = FILE_HEADER.match(line)
        if header:
            old, new = header.group("old"), header.group("new")
            path = new
            in_hunk = False
            marks = whole_file.get(path) if old == new else None
            # Refused as a whole, not only by withholding pin normalization
            # from its lines: a workflow also carries pins no block scalar
            # check guards (a pip pin in a `run:` step, say), and none of
            # them is graded without a proven base.
            if marks is None and path.startswith(".github/workflows/"):
                structural.append(
                    f"{path}: its base on main could not be proven to be this "
                    "diff's, so nothing in it is graded as a pin until the "
                    "branch is rebased onto main"
                )
            changes.setdefault(path, (Counter(), Counter()))
            if old != new:
                structural.append(f"{old} renamed to {new}")
            continue

        if line.startswith("@@"):
            in_hunk = True
            hunk = HUNK_HEADER.match(line)
            if hunk:
                old_number = int(hunk.group("old_start")) - 1
                new_number = int(hunk.group("new_start")) - 1
            else:
                marks = None
            continue

        # Everything between a file header and its first hunk is preamble: the
        # index line, the ---/+++ pair, and any mode line. Recognizing those
        # only here is what stops a content line impersonating one. Inside a
        # hunk, `+++foo` is an added line reading `++foo`, and skipping it as
        # a file header would drop it from the comparison, which fails open.
        if not in_hunk:
            if line.startswith(
                ("new file ", "deleted file ", "old mode ", "new mode ")
            ):
                structural.append(f"{path}: {line.strip()}")
            continue

        if path is None:
            continue

        # `True` when the marks are missing, but only for the files the marks
        # are computed for at all. _whole_file_block_scalars only reads
        # `.github/workflows/`, so for every other path the absence of marks
        # means "not a file with block scalars in it", not "could not tell".
        # Defaulting those to True said the opposite, and a configuration whose
        # grammars are all `outside_block_scalar` then normalized nothing
        # outside a workflow: a plain `rev:` bump in .pre-commit-config.yaml was
        # refused under examples/devcontainer-images.yml while passing under
        # examples/rsync-crypt.yml. Safe, in that it refuses rather than
        # approves, and still wrong: the lane the file exists to permit stopped
        # working.
        graded_for_scalars = path.startswith(".github/workflows/")

        if line.startswith("-"):
            content = line[1:]
            in_scalar = marks[0][old_number] if marks else graded_for_scalars
            changes[path][0][normalize(content, path, in_scalar)] += 1
            old_number += 1
        elif line.startswith("+"):
            content = line[1:]
            in_scalar = marks[1][new_number] if marks else graded_for_scalars
            changes[path][1][normalize(content, path, in_scalar)] += 1
            new_number += 1
        elif line.startswith(" ") or line == "":
            # An unchanged context line: not compared itself, but it moves
            # both sides' line numbers along.
            old_number += 1
            new_number += 1

    return changes, structural


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pin-only",
        description="Refuse a unified diff that changes anything but a dependency pin.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="YAML configuration (default: .github/pin-only.yml under --repo-root)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root the configuration's paths resolve against.",
    )
    parser.add_argument(
        "--allowed-path",
        action="append",
        default=[],
        dest="allowed_paths",
        help="Override allowed_paths. Repeatable.",
    )
    parser.add_argument(
        "--grammar",
        action="append",
        default=[],
        dest="default_grammars",
        help="Override default_grammars. Repeatable.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global _ACTIVE
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    explicit = args.config is not None
    config_path = args.config or (args.repo_root / ".github" / "pin-only.yml")
    overrides: dict[str, object] = {
        "allowed_paths": args.allowed_paths,
        "default_grammars": args.default_grammars,
    }
    if explicit:
        overrides["config_was_explicit"] = True
    _ACTIVE = load_config(config_path, args.repo_root, overrides)

    diff = sys.stdin.read()
    if not diff.strip():
        print("REFUSED: the diff is empty, so there is nothing to approve.")
        return 1

    changes, problems = parse(diff)

    # Output that parsed into nothing is not a clean bill of health. Truncated
    # output, a binary diff, or anything that arrives without a `diff --git`
    # header would otherwise leave the change set empty and read as "no
    # problems found", approving a diff nobody managed to read.
    if not changes:
        print("REFUSED: no file headers in the diff, so nothing could be checked.")
        return 1

    for path in changes:
        if not path.startswith(_ACTIVE.allowed_paths):
            problems.append(f"{path}: not a dependency pin file")

    for path, (removed, added) in changes.items():
        if not removed and not added:
            problems.append(
                f"{path}: no readable changed lines, so nothing was checked"
            )

    problems.extend(_depinned_actions(diff))

    for path, (removed, added) in changes.items():
        # Counter subtraction drops non-positive counts, so each direction has
        # to be asked separately to see both halves of a mismatch.
        for line in removed - added:
            problems.append(f"{path}: removed a line that was not re-added: -{line}")
        for line in added - removed:
            problems.append(
                f"{path}: added a line that was not a version bump: +{line}"
            )

    if problems:
        print("REFUSED: this diff changes more than dependency pins.")
        for problem in problems:
            print(f"  {problem}")
        print(
            "\nNothing is broken. The automated approval is skipped and the pull "
            "request waits for a person, which is what should happen when a "
            "dependency bot reaches outside its lane."
        )
        return 1

    files = ", ".join(sorted(changes)) or "nothing"
    print(f"Pin-only diff confirmed: {files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
