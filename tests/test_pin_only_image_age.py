# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ivan Pinatti
"""Tests for the image age check, which refuses a bump to an older build.

In process, like the hash locked tests, because the check asks each image's
registry and every request has to be stubbed: nothing in this suite touches
the network. The registry client is tested against canned answers in the
shapes Docker Hub, GHCR and Quay give.
"""

import email.message
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# E402: the import has to follow the sys.path line above.
import pin_only  # noqa: E402

OLD = "sha256:" + "1" * 64
NEW = "sha256:" + "2" * 64
OTHER = "sha256:" + "3" * 64

CONFIG = """\
allowed_paths:
  - versions.env
  - Dockerfile
image_age: {image_age}
rules:
  - path: versions.env
    grammars: [digest_strip, version]
  - path: Dockerfile
    grammars: [docker_image_pin]
"""


def _diff(*lines: str) -> str:
    # Joined rather than written as one string literal, since a diff's
    # context lines start with a single space.
    return "\n".join(lines) + "\n"


ENV_DIFF = _diff(
    "diff --git a/versions.env b/versions.env",
    "--- a/versions.env",
    "+++ b/versions.env",
    "@@ -1,3 +1,3 @@",
    " # renovate: depName=docker.io/linuxserver/mylar3 versioning=loose",
    f"-MYLAR_VERSION=v0.11.0-ls277@{OLD}",
    f"+MYLAR_VERSION=3ea9b997-ls249@{NEW}",
    " NGINX_VERSION=stable-alpine",
)

DOCKERFILE_DIFF = _diff(
    "diff --git a/Dockerfile b/Dockerfile",
    "--- a/Dockerfile",
    "+++ b/Dockerfile",
    "@@ -1,2 +1,2 @@",
    f"-FROM docker.io/library/alpine:3.23@{OLD}",
    f"+FROM docker.io/library/alpine:3.24@{NEW}",
    " RUN true",
)

MAY = datetime(2026, 5, 1, tzinfo=UTC)
OCTOBER = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_cached_tokens(monkeypatch):
    """Each test starts with no registry token cached by another."""
    monkeypatch.setattr(pin_only, "_TOKENS", {})


@pytest.fixture
def built(monkeypatch):
    """Stub the registry with a table of build dates, recording every query."""
    table: dict[tuple[str, str], object] = {}
    calls: list[tuple[str, str]] = []

    def fake(image: str, digest: str) -> datetime:
        calls.append((image, digest))
        answer = table[(image, digest)]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(pin_only, "_image_created", fake)
    table["calls"] = calls
    return table


def _run(monkeypatch, capsys, tmp_path, diff, image_age="true", *flags):
    (tmp_path / ".github").mkdir(exist_ok=True)
    (tmp_path / ".github" / "pin-only.yml").write_text(
        CONFIG.format(image_age=image_age)
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(diff))
    code = pin_only.main(["--repo-root", str(tmp_path), *flags])
    return code, capsys.readouterr().out


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


def test_refuses_a_bump_to_an_older_build(tmp_path, monkeypatch, capsys, built):
    image = "docker.io/linuxserver/mylar3"
    built[(image, OLD)] = OCTOBER
    built[(image, NEW)] = MAY

    code, out = _run(monkeypatch, capsys, tmp_path, ENV_DIFF)

    assert code == 1
    assert f"moves {image} to a build from 2026-05-01" in out
    assert "older than the current one from 2026-10-01" in out


@pytest.mark.parametrize("new", [OCTOBER, MAY], ids=["newer", "same"])
def test_accepts_a_bump_to_a_build_no_older(tmp_path, monkeypatch, capsys, built, new):
    built[("docker.io/linuxserver/mylar3", OLD)] = MAY
    built[("docker.io/linuxserver/mylar3", NEW)] = new

    code, out = _run(monkeypatch, capsys, tmp_path, ENV_DIFF)

    assert code == 0, out


def test_reads_the_image_from_the_line_when_it_names_one(
    tmp_path, monkeypatch, capsys, built
):
    built[("docker.io/library/alpine", OLD)] = MAY
    built[("docker.io/library/alpine", NEW)] = OCTOBER

    code, out = _run(monkeypatch, capsys, tmp_path, DOCKERFILE_DIFF)

    assert code == 0, out
    assert built["calls"] == [
        ("docker.io/library/alpine", OLD),
        ("docker.io/library/alpine", NEW),
    ]


@pytest.mark.parametrize("error", [OSError("unreachable"), ValueError("no date")])
def test_refuses_when_the_registry_cannot_confirm(
    tmp_path, monkeypatch, capsys, built, error
):
    built[("docker.io/linuxserver/mylar3", OLD)] = error

    code, out = _run(monkeypatch, capsys, tmp_path, ENV_DIFF)

    assert code == 1
    assert "could not confirm docker.io/linuxserver/mylar3's build dates" in out


def test_refuses_the_pins_left_when_the_budget_runs_out(monkeypatch, built):
    clock = iter([0, 0, pin_only.IMAGE_AGE_BUDGET + 1])
    monkeypatch.setattr(pin_only.time, "monotonic", lambda: next(clock))
    built[("a", OLD)] = MAY
    built[("a", NEW)] = OCTOBER
    bumps = [
        pin_only.ImageBump("Makefile", "a", OLD, NEW),
        pin_only.ImageBump("Makefile", "b", OLD, NEW),
    ]

    problems = pin_only._image_age_problems(bumps)

    assert problems == [
        f"the registry lookups ran past {pin_only.IMAGE_AGE_BUDGET}s with 1 "
        "image pin(s) unchecked, so they are not graded as pins"
    ]


def test_off_unless_asked(tmp_path, monkeypatch, capsys, built):
    code, out = _run(monkeypatch, capsys, tmp_path, ENV_DIFF, "false")

    assert code == 0, out
    assert built["calls"] == []


def test_the_flag_turns_it_on(tmp_path, monkeypatch, capsys, built):
    built[("docker.io/linuxserver/mylar3", OLD)] = OCTOBER
    built[("docker.io/linuxserver/mylar3", NEW)] = MAY

    code, out = _run(monkeypatch, capsys, tmp_path, ENV_DIFF, "false", "--image-age")

    assert code == 1
    assert "older than the current one" in out


def test_a_diff_already_refused_asks_no_registry(tmp_path, monkeypatch, capsys, built):
    diff = ENV_DIFF.replace("+MYLAR_VERSION=", "+MYLAR_IMAGE=")

    code, _ = _run(monkeypatch, capsys, tmp_path, diff)

    assert code == 1
    assert built["calls"] == []


def test_refuses_an_image_age_that_is_not_a_boolean(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit, match="image_age must be true or false"):
        _run(monkeypatch, capsys, tmp_path, ENV_DIFF, '"yes"')


# ---------------------------------------------------------------------------
# Which pins a diff moves
# ---------------------------------------------------------------------------


def _bumps(diff: str, paths=("versions.env", "Dockerfile", "Makefile")):
    return pin_only._image_bumps(diff.splitlines(), set(paths))


def test_refuses_a_run_of_unequal_length_holding_a_pin():
    diff = _diff(
        "diff --git a/Dockerfile b/Dockerfile",
        "@@ -1,2 +1,1 @@",
        f"-FROM ghcr.io/a/one:1@{OLD}",
        "-RUN true",
        f"+FROM ghcr.io/a/one:2@{NEW}",
    )
    bumps, problems = _bumps(diff)

    assert bumps == []
    assert problems == [
        "Dockerfile: a run of 2 removed and 1 added lines holds an image pin, "
        "so its old and new image cannot be paired"
    ]


def test_a_removed_line_reading_like_a_file_header_stays_in_its_run():
    # `-- x` removed reads `--- x` in the diff, which outside a hunk would be
    # a file header line.
    diff = _diff(
        "diff --git a/Dockerfile b/Dockerfile",
        "--- a/Dockerfile",
        "+++ b/Dockerfile",
        "@@ -1,2 +1,2 @@",
        f"-FROM ghcr.io/a/one:1@{OLD}",
        "--- x",
        f"+FROM ghcr.io/a/one:2@{NEW}",
        "+-- x",
    )
    bumps, problems = _bumps(diff)

    assert problems == []
    assert [(b.image, b.new) for b in bumps] == [("ghcr.io/a/one", NEW)]


def test_pairs_each_pin_in_a_run_with_its_replacement():
    diff = f"""\
diff --git a/Dockerfile b/Dockerfile
@@ -1,2 +1,2 @@
-FROM ghcr.io/a/one:1@{OLD}
-FROM quay.io/b/two:1@{OLD}
+FROM ghcr.io/a/one:2@{NEW}
+FROM quay.io/b/two:2@{OTHER}
"""
    bumps, problems = _bumps(diff)

    assert problems == []
    assert [(b.image, b.old, b.new) for b in bumps] == [
        ("ghcr.io/a/one", OLD, NEW),
        ("quay.io/b/two", OLD, OTHER),
    ]


def test_a_removed_line_after_an_added_one_starts_a_new_pair():
    diff = f"""\
diff --git a/Makefile b/Makefile
@@ -1,2 +1,2 @@
-A ?= alpine:1@{OLD}
+A ?= alpine:2@{NEW}
-B ?= ghcr.io/x/y@{OLD}
+B ?= ghcr.io/x/y@{OTHER}
"""
    bumps, _ = _bumps(diff)

    assert [(b.image, b.new) for b in bumps] == [
        ("alpine", NEW),
        ("ghcr.io/x/y", OTHER),
    ]


def test_skips_lines_without_a_moved_digest_and_files_not_asked_about():
    diff = f"""\
diff --git a/Dockerfile b/Dockerfile
@@ -1,3 +1,3 @@
-ARG TOOL_VERSION=1.0
+ARG TOOL_VERSION=1.1
-FROM alpine:3@{OLD}
+FROM alpine:3@{OLD}
diff --git a/other.env b/other.env
--- a/other.env
+++ b/other.env
@@ -1 +1 @@
-FROM alpine:3@{OLD}
+FROM alpine:4@{NEW}
"""
    assert _bumps(diff) == ([], [])


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (f"X=@{OLD}", f"X=@{NEW}"),
        (f"X=a:1@{OLD}", f"X=a:2@{NEW} b:2@{OTHER}"),
    ],
    ids=["no image", "a second image"],
)
def test_refuses_a_pin_whose_image_it_cannot_tell(old, new):
    diff = f"""\
diff --git a/Makefile b/Makefile
@@ -1 +1 @@
-{old}
+{new}
"""
    bumps, problems = _bumps(diff)

    assert bumps == []
    assert problems == [f"Makefile: could not tell which image this pin is: +{new}"]


def test_an_annotation_only_names_the_pin_directly_below_it():
    diff = _diff(
        "diff --git a/versions.env b/versions.env",
        "@@ -1,4 +1,4 @@",
        " # renovate: depName=docker.io/a/b",
        " A_VERSION=1",
        f"-B_VERSION=x:1@{OLD}",
        f"+B_VERSION=x:2@{NEW}",
    )
    bumps, _ = _bumps(diff)

    assert [b.image for b in bumps] == ["x"]


# ---------------------------------------------------------------------------
# The registry client
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("alpine", ("registry-1.docker.io", "library/alpine")),
        ("docker.io/alpine", ("registry-1.docker.io", "library/alpine")),
        (
            "dotenvlinter/dotenv-linter",
            ("registry-1.docker.io", "dotenvlinter/dotenv-linter"),
        ),
        (
            "docker.io/linuxserver/mylar3",
            ("registry-1.docker.io", "linuxserver/mylar3"),
        ),
        ("ghcr.io/hotio/whisparr", ("ghcr.io", "hotio/whisparr")),
        ("localhost/x", ("localhost", "x")),
    ],
)
def test_registry_and_repository(image, expected):
    assert pin_only._registry_and_repository(image) == expected


def _redirect(target: str) -> urllib.request.Request | None:
    request = urllib.request.Request(
        "https://registry.example/v2/x/blobs/y", headers={"Authorization": "Bearer t"}
    )
    handler = pin_only._NoAuthOnRedirect()
    return handler.redirect_request(request, None, 307, "Redirect", {}, target)


def test_a_redirect_to_another_host_drops_the_token():
    assert not _redirect("https://storage.example/blob").has_header("Authorization")


def test_a_redirect_on_the_same_host_keeps_the_token():
    assert _redirect("https://registry.example/other").has_header("Authorization")


def test_a_redirect_off_https_is_refused():
    with pytest.raises(ValueError, match="non https"):
        _redirect("http://storage.example/blob")


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self.body


def test_fetch_sends_the_headers_through_the_opener(monkeypatch):
    seen = {}

    class Opener:
        def open(self, request, timeout):
            seen["accept"] = request.get_header("Accept")
            seen["timeout"] = timeout
            return _Response(b"body")

    monkeypatch.setattr(pin_only, "_OPENER", Opener())

    assert pin_only._fetch("https://x/y", {"Accept": "a/b"}) == b"body"
    assert seen == {"accept": "a/b", "timeout": pin_only.REGISTRY_TIMEOUT}


def _http_error(code: int, challenge: str = "") -> urllib.error.HTTPError:
    headers = email.message.Message()
    if challenge:
        headers["WWW-Authenticate"] = challenge
    return urllib.error.HTTPError("https://x", code, "error", headers, None)


CHALLENGE = (
    'Bearer realm="https://auth.example/token",service="registry.example",'
    'scope="repository:a/b:pull"'
)


def test_registry_get_answers_a_bearer_challenge(monkeypatch):
    requests = []

    def fake(url, headers):
        requests.append((url, headers.get("Authorization")))
        if url.startswith("https://auth.example/token?"):
            return json.dumps({"token": "t0k"}).encode()
        if headers.get("Authorization") is None:
            raise _http_error(401, CHALLENGE)
        return b"manifest"

    monkeypatch.setattr(pin_only, "_fetch", fake)

    assert (
        pin_only._registry_get("registry.example", "a/b", "manifests/x", "*/*")
        == b"manifest"
    )
    assert requests == [
        ("https://registry.example/v2/a/b/manifests/x", None),
        (
            "https://auth.example/token?service=registry.example"
            "&scope=repository%3Aa%2Fb%3Apull",  # cspell:disable-line
            None,
        ),
        ("https://registry.example/v2/a/b/manifests/x", "Bearer t0k"),
    ]


def test_registry_get_reuses_a_token_and_replaces_a_refused_one(monkeypatch):
    requests = []
    tokens = iter(["first", "second"])

    def fake(url, headers):
        auth = headers.get("Authorization")
        requests.append((url.rsplit("/", 1)[-1], auth))
        if url.startswith("https://auth.example/token?"):
            return json.dumps({"token": next(tokens)}).encode()
        if auth in (None, "Bearer expired"):
            raise _http_error(401, CHALLENGE)
        return b"ok"

    monkeypatch.setattr(pin_only, "_fetch", fake)

    for path in ("manifests/x", "blobs/y"):
        pin_only._registry_get("registry.example", "a/b", path, "*/*")
    pin_only._TOKENS[("registry.example", "a/b")] = "expired"
    pin_only._registry_get("registry.example", "a/b", "blobs/z", "*/*")

    challenged = [r for r in requests if r[0].startswith("token?")]
    assert len(challenged) == 2
    assert ("y", "Bearer first") in requests
    assert requests[-1] == ("z", "Bearer second")


def test_registry_get_needs_no_token_when_none_is_asked(monkeypatch):
    monkeypatch.setattr(pin_only, "_fetch", lambda url, headers: b"open")

    assert pin_only._registry_get("r", "a", "manifests/x", "*/*") == b"open"


def test_registry_get_raises_any_other_error(monkeypatch):
    def fake(url, headers):
        raise _http_error(404)

    monkeypatch.setattr(pin_only, "_fetch", fake)

    with pytest.raises(urllib.error.HTTPError):
        pin_only._registry_get("r", "a", "manifests/x", "*/*")


@pytest.mark.parametrize("key", ["token", "access_token"])
def test_bearer_token_reads_either_key(monkeypatch, key):
    monkeypatch.setattr(
        pin_only, "_fetch", lambda url, headers: json.dumps({key: "t"}).encode()
    )

    assert pin_only._bearer_token(CHALLENGE) == "t"


@pytest.mark.parametrize(
    ("challenge", "answer", "message"),
    [
        ('Basic realm="https://x"', {}, "unsupported registry challenge"),
        ('Bearer realm="http://auth.example/token"', {}, "realm is not https"),
        (CHALLENGE, {}, "carries no token"),
    ],
)
def test_bearer_token_refuses(monkeypatch, challenge, answer, message):
    monkeypatch.setattr(
        pin_only, "_fetch", lambda url, headers: json.dumps(answer).encode()
    )

    with pytest.raises(ValueError, match=message):
        pin_only._bearer_token(challenge)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-23T09:30:34Z", datetime(2026, 10, 23, 9, 30, 34, tzinfo=UTC)),
        (
            "2026-10-23T09:30:34.123456789Z",
            datetime(2026, 10, 23, 9, 30, 34, tzinfo=UTC),
        ),
        ("2026-10-23T11:30:34+02:00", datetime(2026, 10, 23, 9, 30, 34, tzinfo=UTC)),
    ],
)
def test_build_date(value, expected):
    assert pin_only._build_date(value) == expected


@pytest.mark.parametrize("value", [None, 1, "yesterday", "1970-01-01T00:00:00Z"])
def test_build_date_refuses_what_is_not_a_real_date(value):
    with pytest.raises(ValueError, match="build date"):
        pin_only._build_date(value)


def _registry(monkeypatch, objects: dict[str, object]) -> list[str]:
    asked = []

    def fake(host, repository, path, accept):
        asked.append(path)
        return json.dumps(objects[path]).encode()

    monkeypatch.setattr(pin_only, "_registry_get", fake)
    return asked


def test_image_created_reads_the_amd64_image_of_an_index(monkeypatch):
    asked = _registry(
        monkeypatch,
        {
            f"manifests/{OLD}": {
                "manifests": [
                    {
                        "digest": "arm",
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                    {"digest": "attestation"},
                    {
                        "digest": "amd",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                ]
            },
            "manifests/amd": {"config": {"digest": "cfg"}},
            "blobs/cfg": {"created": "2026-10-23T09:30:34Z"},
        },
    )

    created = pin_only._image_created("docker.io/linuxserver/mylar3", OLD)

    assert created == datetime(2026, 10, 23, 9, 30, 34, tzinfo=UTC)
    assert asked == [f"manifests/{OLD}", "manifests/amd", "blobs/cfg"]


def test_image_created_reads_a_single_image(monkeypatch):
    _registry(
        monkeypatch,
        {
            f"manifests/{OLD}": {"config": {"digest": "cfg"}},
            "blobs/cfg": {"created": "2021-11-29T03:51:34Z"},
        },
    )

    assert pin_only._image_created("alpine", OLD).year == 2021


@pytest.mark.parametrize(
    ("objects", "message"),
    [
        (
            {
                f"manifests/{OLD}": {
                    "manifests": [
                        {
                            "digest": "arm",
                            "platform": {"os": "linux", "architecture": "arm64"},
                        }
                    ]
                }
            },
            "no linux/amd64 image",
        ),
        ({f"manifests/{OLD}": {"layers": []}}, "unexpected answer"),
        ({f"manifests/{OLD}": []}, "unexpected answer"),
    ],
    ids=["no amd64", "no config", "not a mapping"],
)
def test_image_created_refuses_an_answer_it_cannot_read(monkeypatch, objects, message):
    _registry(monkeypatch, objects)

    with pytest.raises(ValueError, match=message):
        pin_only._image_created("alpine", OLD)
