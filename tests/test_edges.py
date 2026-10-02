# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""The edges of src/pin_only.py and src/review_verdict.py the other suites miss.

Coverage is held at 100% of lines and branches (.coveragerc), and each test
here exists because a line or a branch was otherwise never taken. Most drive
`main()` in process, the same way tests/test_pin_only_hash_locked.py does,
over a throwaway repository; the few that call a helper directly do so where
the input that reaches it through `main()` would need a contrived diff to
say the same thing.
"""

import io
import itertools
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# E402: the imports have to follow the sys.path line above.
import pin_only  # noqa: E402
import review_verdict  # noqa: E402

WORKFLOW = ".github/workflows/ci.yml"
SHA = "a" * 40
OTHER_SHA = "b" * 40

WORKFLOW_CONFIG = """\
allowed_paths:
  - .github/workflows/
default_grammars:
  - name: action_sha
    when: outside_block_scalar
"""


@pytest.fixture(autouse=True)
def _restore_active(monkeypatch):
    """`main()` installs its configuration as a module global; put it back."""
    monkeypatch.setattr(pin_only, "_ACTIVE", pin_only._ACTIVE)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _git_diff(root: Path, path: str, before: bytes, after: bytes) -> str:
    """A real `git diff` of `path` from `before` to `after`, leaving `before`
    checked out, which is how the gate sees a pull request against main."""
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(before)
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    target.write_bytes(after)
    diff = _git(root, "diff")
    target.write_bytes(before)
    return diff


def _grade(monkeypatch, capsys, root: Path, diff: str, *args: str) -> tuple[int, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(diff))
    code = pin_only.main(["--repo-root", str(root), *args])
    return code, capsys.readouterr().out


def _with_config(root: Path, text: str = WORKFLOW_CONFIG) -> str:
    config = root / "pin-only.yml"
    config.write_text(text)
    return str(config)


def _hand_diff(path: str, base: bytes, hunks: str) -> str:
    """A diff whose hunks are written by hand, with the base's real blob id,
    for shapes `git diff` never produces."""
    blob = pin_only._git_blob_id(base)
    return (
        f"diff --git a/{path} b/{path}\n"
        f"index {blob[:12]}..{'1' * 12} 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n" + hunks
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_configures_everything_by_flag_when_the_default_file_is_absent(
    tmp_path, monkeypatch, capsys
):
    """No .github/pin-only.yml and no --config: the flags are the whole
    configuration, which is a supported way to use this, not an error."""
    path = ".pre-commit-config.yaml"
    diff = _git_diff(tmp_path, path, b"    rev: v1.0.0\n", b"    rev: v1.1.0\n")
    code, out = _grade(
        monkeypatch,
        capsys,
        tmp_path,
        diff,
        "--allowed-path",
        path,
        "--grammar",
        "rev_pin",
    )
    assert code == 0, out
    assert f"Pin-only diff confirmed: {path}" in out


def test_refuses_a_configuration_file_named_but_absent(tmp_path, monkeypatch, capsys):
    """Named with --config, a missing file is a mistake, not a choice."""
    absent = tmp_path / "absent.yml"
    with pytest.raises(SystemExit) as exit_info:
        _grade(monkeypatch, capsys, tmp_path, "", "--config", str(absent))
    assert exit_info.value.code == f"pin-only: no such configuration file: {absent}"


def test_builds_a_configuration_from_overrides_alone(tmp_path):
    """No file at all, the way a caller importing the module may use it."""
    config = pin_only.load_config(None, tmp_path, {"allowed_paths": ["a"]})
    assert config.allowed_paths == ("a",)
    assert config.repo_root == tmp_path


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- a list\n", "does not contain a YAML mapping"),
        ("rules:\n  - grammars: [rev_pin]\n", "needs a `path`"),
        ("arg_sources:\n  - annotations: ['#']\n", "needs a `file`"),
        ("allowed_paths: [a]\ndefault_grammars: [42]\n", "a grammar entry must be"),
        ("default_grammars: [rev_pin]\n", "no allowed_paths configured"),
        (
            "allowed_paths: [a]\ndefault_grammars: [no_such_grammar]\n",
            "unknown grammar(s): no_such_grammar",
        ),
        (
            "allowed_paths: [a]\ndefault_grammars:\n  - {name: rev_pin, when: never}\n",
            "has when='never'",
        ),
    ],
    ids=[
        "not-a-mapping",
        "rule-without-path",
        "arg-source-without-file",
        "grammar-neither-name-nor-mapping",
        "no-allowed-paths",
        "unknown-grammar",
        "unknown-when",
    ],
)
def test_refuses_a_configuration_that_would_grade_less_than_it_says(
    tmp_path, text, message
):
    config = tmp_path / "pin-only.yml"
    config.write_text(text)
    with pytest.raises(SystemExit) as exit_info:
        pin_only.load_config(config, tmp_path)
    assert message in str(exit_info.value.code)


def test_an_unreadable_arg_source_makes_no_name_eligible(tmp_path):
    assert pin_only._annotated_arg_names(tmp_path / "absent", re.compile("#")) == (
        frozenset()
    )


def test_a_raw_rule_normalizes_nothing():
    cfg = pin_only.Config(
        allowed_paths=("pins.txt",),
        rules=(
            pin_only.PathRule(
                match="pins.txt", grammars=(pin_only.Grammar("rev_pin"),), raw=True
            ),
        ),
    )
    assert pin_only.normalize("rev: v1.0.0", "pins.txt", config=cfg) == "rev: v1.0.0"


# ---------------------------------------------------------------------------
# Grammar details
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "want"),
    [
        # Forty characters reads as a SHA even when RELEASE also matches it,
        # so it is left for the SHA grammar rather than stripped as a version.
        (f"  uses: a/b@{'1' * 40}", f"  uses: a/b@{'1' * 40}"),
        ("  uses: a/b@v8", "  uses: a/b # <version>"),
    ],
)
def test_bare_action_version_strip_leaves_a_sha_shaped_version_alone(line, want):
    grammar = pin_only.GRAMMARS["bare_action_version_strip"]
    assert grammar(line, pin_only.Config()) == want


@pytest.mark.parametrize(
    ("n", "want"),
    [
        (1, "1st"),
        (2, "2nd"),
        (3, "3rd"),
        (4, "4th"),
        (11, "11th"),
        (12, "12th"),
        (13, "13th"),
        (21, "21st"),
        (111, "111th"),
        (122, "122nd"),
    ],
)
def test_ordinal(n, want):
    assert pin_only._ordinal(n) == want


# The file header pattern as it was written before it was made linear. The
# rewrite must split every line exactly as this one does.
GREEDY_FILE_HEADER = re.compile(r"^diff --git a/(?P<old>.+) b/(?P<new>.+)$")


def _same_file_header(line):
    want = GREEDY_FILE_HEADER.match(line)
    got = pin_only.FILE_HEADER.match(line)
    assert (got is None) == (want is None), repr(line)
    if want is not None:
        assert got.groupdict() == want.groupdict(), repr(line)
        assert got.span() == want.span(), repr(line)


@pytest.mark.parametrize(
    ("line", "old", "new"),
    [
        ("diff --git a/x b/x", "x", "x"),
        ("diff --git a/x b/y b/z", "x b/y", "z"),
        # A " b/" that would leave the new path empty is not the split.
        ("diff --git a/x b/y b/", "x", "y b/"),
        ("diff --git a/x b/ b/", "x", " b/"),
        ("diff --git a/ b/ b/x", " b/", "x"),
        ("diff --git a/x b/y\n", "x", "y"),
        ("diff --git a/ b/x", None, None),
        ("diff --git a/x b/", None, None),
        ("diff --git a/x b/y\nz", None, None),
        ("diff --git a/x\n b/y", None, None),
    ],
)
def test_file_header_splits_at_the_last_usable_b_slash(line, old, new):
    _same_file_header(line)
    header = pin_only.FILE_HEADER.match(line)
    if old is None:
        assert header is None
    else:
        assert (header.group("old"), header.group("new")) == (old, new)


def test_file_header_matches_the_greedy_pattern_on_every_short_line():
    pieces = [" b/", "b", "/", " ", "x", "\n"]
    for length in range(6):
        for combo in itertools.product(pieces, repeat=length):
            _same_file_header("diff --git a/" + "".join(combo))


def test_file_header_matches_the_greedy_pattern_on_every_fixture_line():
    for path in sorted((ROOT / "tests" / "fixtures").rglob("*")):
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
                _same_file_header(line)
                _same_file_header(line.rstrip("\n"))


# ---------------------------------------------------------------------------
# Reading a diff
# ---------------------------------------------------------------------------


def test_names_a_late_step_by_its_ordinal(tmp_path, monkeypatch, capsys):
    """A step past the tenth is named with the right ordinal suffix."""
    steps = [f"      - uses: org/step{n}@{SHA} # v1\n" for n in range(1, 12)]
    before = "jobs:\n  a:\n    steps:\n" + "".join(steps)
    after = before.replace(f"step11@{SHA} # v1", "step11@v2")
    diff = _git_diff(tmp_path, WORKFLOW, before.encode(), after.encode())
    code, out = _grade(
        monkeypatch, capsys, tmp_path, diff, "--config", _with_config(tmp_path)
    )
    assert code == 1
    assert "the 11th `uses:` in the file (org/step11) moves off its commit SHA" in out


def test_a_step_added_is_refused_once_not_twice(tmp_path, monkeypatch, capsys):
    """A changed step count is a structural change the line comparison already
    refuses; the depin check stays quiet rather than repeating it."""
    before = f"jobs:\n  a:\n    steps:\n      - uses: org/one@{SHA} # v1\n"
    after = before + f"      - uses: org/two@{SHA} # v1\n"
    diff = _git_diff(tmp_path, WORKFLOW, before.encode(), after.encode())
    code, out = _grade(
        monkeypatch, capsys, tmp_path, diff, "--config", _with_config(tmp_path)
    )
    assert code == 1
    assert "added a line that was not a version bump" in out
    assert "`uses:` in the file" not in out


def test_accepts_a_bump_in_a_file_with_no_final_newline(tmp_path, monkeypatch, capsys):
    """git marks the last line `\\ No newline at end of file`. The base has
    no empty last line to drop, and the marker is neither side's content."""
    before = f"jobs:\n  a:\n    steps:\n      - uses: org/one@{SHA} # v1"
    after = before.replace(f"{SHA} # v1", f"{OTHER_SHA} # v2")
    diff = _git_diff(tmp_path, WORKFLOW, before.encode(), after.encode())
    assert "\\ No newline at end of file" in diff
    code, out = _grade(
        monkeypatch, capsys, tmp_path, diff, "--config", _with_config(tmp_path)
    )
    assert code == 0, out


def test_refuses_a_workflow_whose_base_is_not_utf8(tmp_path, monkeypatch, capsys):
    before = f"jobs:\n  a:\n    steps:\n      - uses: org/one@{SHA} # v1 \xff\n"
    (tmp_path / WORKFLOW).parent.mkdir(parents=True)
    (tmp_path / WORKFLOW).write_bytes(before.encode("latin-1"))
    hunk = (
        "@@ -4,1 +4,1 @@\n"
        f"-      - uses: org/one@{SHA} # v1 \xff\n"
        f"+      - uses: org/one@{OTHER_SHA} # v2 \xff\n"
    )
    diff = _hand_diff(WORKFLOW, before.encode("latin-1"), hunk)
    code, out = _grade(
        monkeypatch, capsys, tmp_path, diff, "--config", _with_config(tmp_path)
    )
    assert code == 1
    assert "could not be proven" in out


BASE = b"name: ci\non: push\njobs: {}\n"


@pytest.mark.parametrize(
    "hunks",
    [
        # A hunk that starts before the one ahead of it ended.
        "@@ -2,1 +2,1 @@\n-on: push\n+on: pull_request\n@@ -1,1 +1,1 @@\n name: ci\n",
        # A head side start that does not follow from the base side.
        "@@ -2,1 +3,1 @@\n-on: push\n+on: pull_request\n",
        # A body line that is neither context, removal, addition nor marker.
        "@@ -2,1 +2,1 @@\n-on: push\n?on: push\n+on: pull_request\n",
    ],
    ids=["overlapping-hunks", "misplaced-head-side", "unknown-line-tag"],
)
def test_refuses_a_workflow_whose_hunks_do_not_apply_to_its_base(
    tmp_path, monkeypatch, capsys, hunks
):
    (tmp_path / WORKFLOW).parent.mkdir(parents=True)
    (tmp_path / WORKFLOW).write_bytes(BASE)
    diff = _hand_diff(WORKFLOW, BASE, hunks)
    code, out = _grade(
        monkeypatch, capsys, tmp_path, diff, "--config", _with_config(tmp_path)
    )
    assert code == 1
    assert "could not be proven" in out


def test_an_unreadable_hunk_header_drops_the_block_scalar_marks(
    tmp_path, monkeypatch, capsys
):
    """After a hunk header it cannot read, the gate no longer knows which
    lines sit in a block scalar, so it treats them all as if they did and an
    `outside_block_scalar` grammar normalizes nothing. Without the stray
    header the same bump is accepted."""
    before = f"jobs:\n  a:\n    steps:\n      - uses: org/one@{SHA} # v1\n".encode()
    (tmp_path / WORKFLOW).parent.mkdir(parents=True)
    (tmp_path / WORKFLOW).write_bytes(before)
    hunk = (
        "@@ -1,4 +1,4 @@\n jobs:\n   a:\n     steps:\n"
        f"-      - uses: org/one@{SHA} # v1\n"
        f"+      - uses: org/one@{OTHER_SHA} # v2\n"
    )
    config = _with_config(tmp_path)

    clean = _hand_diff(WORKFLOW, before, hunk)
    code, out = _grade(monkeypatch, capsys, tmp_path, clean, "--config", config)
    assert code == 0, out

    stray = _hand_diff(WORKFLOW, before, "@@ unreadable @@\n" + hunk)
    code, out = _grade(monkeypatch, capsys, tmp_path, stray, "--config", config)
    assert code == 1
    assert "added a line that was not a version bump" in out


def test_refuses_hunks_with_no_file_header(tmp_path, monkeypatch, capsys):
    diff = "@@ -1 +1 @@\n-rev: v1.0.0\n+rev: v1.1.0\n"
    code, out = _grade(
        monkeypatch, capsys, tmp_path, diff, "--config", _with_config(tmp_path)
    )
    assert code == 1
    assert "no file headers" in out


# ---------------------------------------------------------------------------
# review_verdict
# ---------------------------------------------------------------------------


def test_verdict_refuses_an_author_that_is_not_a_string():
    assert review_verdict.decide({"author": ["renovate[bot]"]}) == (
        "failure",
        "author was not a string",
    )


BOT_PIN_ONLY = (
    '{"author": "%s", "is_fork": false, "pin_only_state": "success", '
    '"coderabbit_description": ""}'
)


def _verdict(monkeypatch, capsys, payload: str, *args: str) -> str:
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert review_verdict.main(list(args)) == 0
    return capsys.readouterr().out


def test_verdict_no_bots_closes_the_bot_lane(monkeypatch, capsys):
    out = _verdict(monkeypatch, capsys, BOT_PIN_ONLY % "renovate[bot]", "--no-bots")
    assert "state=pending" in out
    assert "waiting for a CodeRabbit review" in out


def test_verdict_bot_names_replace_the_default(monkeypatch, capsys):
    out = _verdict(
        monkeypatch, capsys, BOT_PIN_ONLY % "other[bot]", "--bot", "other[bot]"
    )
    assert "state=success" in out
    out = _verdict(
        monkeypatch, capsys, BOT_PIN_ONLY % "renovate[bot]", "--bot", "other[bot]"
    )
    assert "state=pending" in out
