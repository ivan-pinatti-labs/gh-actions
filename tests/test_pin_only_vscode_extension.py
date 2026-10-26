# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""The vscode_extension_pin grammar: a VS Code extension pinned to a release.

devcontainer-airlock bakes its editor extensions into the workbench image from
a list of `publisher.name@1.2.3` lines, which Renovate moves through a custom
datasource. No other grammar reads that shape, so every one of those bumps
would go to a person.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "pin_only.py"
TARGET = "images/workbench/vscode/extensions.txt"

CONFIG = f"""\
allowed_paths:
  - {TARGET}
rules:
  - path: {TARGET}
    grammars: [vscode_extension_pin]
"""

BASE = """\
# The extensions baked into the workbench.
anthropic.claude-code@2.1.274
openai.chatgpt@26.908.40401
SonarSource.sonarlint-vscode@5.10.0
"""


def _git(repo: Path, *args: str) -> str:
    # S603/S607: git from PATH, with arguments written here, in a throwaway
    # repository pytest created.
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@users.noreply.github.com",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _grade(tmp_path: Path, old_line: str, new_line: str) -> subprocess.CompletedProcess:
    """Commit BASE, replace one line, and grade the real diff against BASE."""
    target = tmp_path / TARGET
    target.parent.mkdir(parents=True)
    (tmp_path / "pin-only.yml").write_text(CONFIG)
    _git(tmp_path, "init", "-q")
    target.write_text(BASE)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    assert old_line in BASE
    target.write_text(BASE.replace(old_line, new_line, 1))
    diff = _git(tmp_path, "diff")
    target.write_text(BASE)
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(tmp_path / "pin-only.yml"),
            "--repo-root",
            str(tmp_path),
        ],
        input=diff,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_accepts_a_patch_bump(tmp_path):
    result = _grade(
        tmp_path, "anthropic.claude-code@2.1.274", "anthropic.claude-code@2.1.296"
    )
    assert result.returncode == 0, result.stdout


def test_accepts_a_bump_with_long_components(tmp_path):
    result = _grade(
        tmp_path, "openai.chatgpt@26.908.40401", "openai.chatgpt@26.1007.21434"
    )
    assert result.returncode == 0, result.stdout


def test_accepts_a_major_bump_of_a_mixed_case_identifier(tmp_path):
    result = _grade(
        tmp_path,
        "SonarSource.sonarlint-vscode@5.10.0",
        "SonarSource.sonarlint-vscode@6.1.0",
    )
    assert result.returncode == 0, result.stdout


def test_refuses_another_extension(tmp_path):
    result = _grade(
        tmp_path, "anthropic.claude-code@2.1.274", "anthropic.claude-c0de@2.1.296"
    )
    assert result.returncode == 1, result.stdout


def test_refuses_another_publisher(tmp_path):
    result = _grade(
        tmp_path, "anthropic.claude-code@2.1.274", "anthroplc.claude-code@2.1.296"
    )
    assert result.returncode == 1, result.stdout


def test_refuses_dropping_the_version(tmp_path):
    result = _grade(tmp_path, "anthropic.claude-code@2.1.274", "anthropic.claude-code")
    assert result.returncode == 1, result.stdout


def test_refuses_a_pre_release_suffix(tmp_path):
    result = _grade(
        tmp_path,
        "anthropic.claude-code@2.1.274",
        "anthropic.claude-code@2.1.296-beta",
    )
    assert result.returncode == 1, result.stdout


def test_refuses_a_payload_after_the_version(tmp_path):
    result = _grade(
        tmp_path,
        "anthropic.claude-code@2.1.274",
        "anthropic.claude-code@2.1.296 evil.extension@1.0.0",
    )
    assert result.returncode == 1, result.stdout


def test_refuses_a_version_that_is_not_three_numbers(tmp_path):
    result = _grade(
        tmp_path, "anthropic.claude-code@2.1.274", "anthropic.claude-code@2.1"
    )
    assert result.returncode == 1, result.stdout


def test_refuses_a_comment_line_changing(tmp_path):
    result = _grade(
        tmp_path,
        "# The extensions baked into the workbench.",
        "# The extensions baked into the workbench, and more.",
    )
    assert result.returncode == 1, result.stdout


def test_refuses_an_added_extension(tmp_path):
    result = _grade(
        tmp_path,
        "openai.chatgpt@26.908.40401\n",
        "openai.chatgpt@26.908.40401\nevil.extension@1.0.0\n",
    )
    assert result.returncode == 1, result.stdout
