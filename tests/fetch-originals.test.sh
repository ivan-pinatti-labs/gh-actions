#!/usr/bin/env bash
#
# Tests for tools/fetch-originals.sh. Every line of the script has to run in
# one of them: `make coverage` runs this file under kcov and fails below 100%.
# Each case runs the script as its own bash process, with curl replaced by a
# stub on PATH that records the URL it was asked for and prints a stand in,
# so nothing here touches the network. ORIGINALS_DIR points the script at a
# scratch directory, so a real fetch in tests/originals/ is left alone.

set -o errexit
set -o pipefail
set -o nounset

__script="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/tools/fetch-originals.sh"
__scratch="$(mktemp -d)"
trap 'rm -rf "${__scratch}"' EXIT
__failures=0

# The stub curl. Its last argument is the URL. It fails with curl's own
# status for an HTTP error (22) when the URL contains STUB_CURL_FAIL.
mkdir "${__scratch}/bin"
cat >"${__scratch}/bin/curl" <<'STUB'
#!/usr/bin/env bash
url="${*: -1}"
printf '%s\n' "${url}" >>"${STUB_CURL_LOG}"
if [[ -n "${STUB_CURL_FAIL:-}" && "${url}" == *"${STUB_CURL_FAIL}"* ]]; then
  exit 22
fi
printf '# fetched from %s\n' "${url}"
STUB
chmod +x "${__scratch}/bin/curl"

# Runs the script against the stub and records its exit status and output.
run() {
  __status=0
  rm -rf "${__scratch}/originals" "${__scratch}/curl.log"
  touch "${__scratch}/curl.log"
  PATH="${__scratch}/bin:${PATH}" ORIGINALS_DIR="${__scratch}/originals" \
    STUB_CURL_LOG="${__scratch}/curl.log" STUB_CURL_FAIL="${1:-}" \
    bash "${__script}" >"${__scratch}/out" 2>"${__scratch}/err" || __status=$?
}

pass() { echo "ok ${1}"; }

fail() {
  echo "FAIL ${1}" >&2
  __failures=$((__failures + 1))
}

expect_status() {
  if [[ "${__status}" -eq "${2}" ]]; then pass "${1}"; else fail "${1}: exit ${__status}, wanted ${2}"; fi
}

expect_file() {
  local name="${1}" file="${__scratch}/originals/${2}" text="${3}"
  if grep --quiet --fixed-strings -- "${text}" "${file}" 2>/dev/null; then
    pass "${name}"
  else
    fail "${name}: '${text}' not in ${2}"
  fi
}

expect_text() {
  local name="${1}" file="${__scratch}/${2}" text="${3}"
  if grep --quiet --fixed-strings -- "${text}" "${file}"; then
    pass "${name}"
  else
    fail "${name}: '${text}' not in ${2}"
  fi
}

raw="https://raw.githubusercontent.com/ivan-pinatti-labs"

run
expect_status "every fetch succeeds" 0
lines="$(wc -l <"${__scratch}/curl.log")"
# Six pin-only copies, three ARG source files, seven review-verdict copies.
if [[ "${lines}" -eq 16 ]]; then pass "sixteen fetches"; else fail "sixteen fetches: ${lines}"; fi
expect_file "pin-only copy at its pinned commit" rsync-crypt.py \
  "${raw}/rsync-crypt/7984436dc174c6c8daddfa1961615247127669c0/scripts/assert-pin-only-diff.py"
expect_file "renamed repository read under its new name" devcontainer-images.py \
  "${raw}/devcontainer-airlock/b71cc9aa3a8f3c2b25b0861304ed575a616a586a/scripts/assert-pin-only-diff.py"
if grep --quiet --fixed-strings "/devcontainer-images/" "${__scratch}/curl.log"; then
  fail "the old repository name is never fetched"
else
  pass "the old repository name is never fetched"
fi
expect_file "ARG source kept at its path" devcontainer-images/images/base/Dockerfile \
  "${raw}/devcontainer-airlock/b71cc9aa3a8f3c2b25b0861304ed575a616a586a/images/base/Dockerfile"
expect_file "ARG source for pre-commit-checklists" pre-commit-checklists/.devcontainer/Dockerfile \
  "${raw}/pre-commit-checklists/5909372518fa52fafa5a737781ca682e12e713d2/.devcontainer/Dockerfile"
if [[ -e "${__scratch}/originals/github-template" ]]; then
  fail "no ARG source directory for a repository without one"
else
  pass "no ARG source directory for a repository without one"
fi
if [[ -e "${__scratch}/originals/.github.py" ]]; then
  fail ".github has no pin-only copy"
else
  pass ".github has no pin-only copy"
fi
expect_file "the .github review-verdict copy" verdict-.github.py \
  "${raw}/.github/22bbd245eed4252f9ab8627d112798208f89b3a6/scripts/coderabbit-review-verdict.py"
expect_text "progress names each copy" out "verdict    .github"

run "/github-template/"
expect_status "a failed fetch stops the run with curl's status" 22
if grep --quiet --fixed-strings "/pre-commit-checklists/" "${__scratch}/curl.log"; then
  fail "nothing is fetched after the failure"
else
  pass "nothing is fetched after the failure"
fi

if [[ "${__failures}" -gt 0 ]]; then
  echo "${__failures} failed" >&2
  exit 1
fi
