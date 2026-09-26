#!/usr/bin/env bash
: 'Fetch each repository'\''s original assert-pin-only-diff.py for the equivalence test.
Exit status: 0 all fetched, 1 a fetch failed.'
set -o errexit
set -o pipefail
set -o nounset

here="$(cd "$(dirname "$0")/.." && pwd)"
out="${here}/tests/originals"
mkdir -p "${out}"

# Pinned, not HEAD. Each repository deletes its own copy of these two scripts
# when it adopts the shared library, and HEAD stopped being a place the
# originals could be read from the moment the first adoption merged. These are
# the last commits that still carry them, so the equivalence comparison keeps
# measuring against the code this library replaced rather than against
# whatever a repository happens to hold now.
#
# Do not "refresh" these to HEAD. There is nothing newer to compare against:
# the originals are frozen by definition, and the fetch failing is what a
# refresh would buy.
# Public files at a pinned commit, straight from GitHub's raw file host. No
# token is needed, so this runs in L2 through the egress proxy as well as in
# CI. devcontainer-images was renamed devcontainer-airlock on 2026-09-26; the
# originals keep the old name, their commits do not move.
fetch() {
  local repo="$1"
  [ "${repo}" = devcontainer-images ] && repo=devcontainer-airlock
  curl -fsSL "https://raw.githubusercontent.com/ivan-pinatti-labs/${repo}/$2/$3"
}

declare -A pinned=(
  [rsync-crypt]=7984436dc174c6c8daddfa1961615247127669c0
  [devcontainer-images]=b71cc9aa3a8f3c2b25b0861304ed575a616a586a
  [github-template]=77437975367b372f98e3e53a84cd030b238285f4
  [pre-commit-checklists]=5909372518fa52fafa5a737781ca682e12e713d2
  [pre-commit-checklists-demo]=e7bffb41a16fd9017ff717cc5e56670570fe28b5
  [docker-torrent-box-with-vpn]=7fdb67cbc09dff7047026d912e1a938727c40fcd
  [.github]=22bbd245eed4252f9ab8627d112798208f89b3a6
)

# Files whose annotated ARG names the `annotated_arg` and `arg_pin` grammars
# read. tests/test_equivalence.py recomputes those names from this fixture
# tree, so an absent fixture silently compares an empty set against a
# populated one and reports a divergence that exists only in the harness.
declare -A arg_sources=(
  [rsync-crypt]="Dockerfile"
  [devcontainer-images]="images/base/Dockerfile"
  [pre-commit-checklists]=".devcontainer/Dockerfile"
)

# The pin-only copies. .github never had one, which is the gap this work also
# closes, so it is absent here on purpose.
for repo in rsync-crypt devcontainer-images github-template \
            pre-commit-checklists pre-commit-checklists-demo \
            docker-torrent-box-with-vpn; do
  sha="${pinned[${repo}]}"

  fetch "${repo}" "${sha}" scripts/assert-pin-only-diff.py > "${out}/${repo}.py"
  printf 'pin-only   %-30s %s lines  @%s\n' \
    "${repo}" "$(wc -l < "${out}/${repo}.py")" "${sha:0:8}"

  source_file="${arg_sources[${repo}]:-}"
  if [ -n "${source_file}" ]; then
    mkdir -p "${out}/${repo}/$(dirname "${source_file}")"
    fetch "${repo}" "${sha}" "${source_file}" > "${out}/${repo}/${source_file}"
    printf 'arg source %-30s %s\n' "${repo}" "${source_file}"
  fi
done

# The review-verdict copies, including .github's, which is the one with no bot
# lane and so the one the shared version has to reproduce with an empty list.
for repo in rsync-crypt devcontainer-images github-template \
            pre-commit-checklists pre-commit-checklists-demo \
            docker-torrent-box-with-vpn .github; do
  sha="${pinned[${repo}]}"
  fetch "${repo}" "${sha}" scripts/coderabbit-review-verdict.py > "${out}/verdict-${repo}.py"
  printf 'verdict    %-30s %s lines  @%s\n' \
    "${repo}" "$(wc -l < "${out}/verdict-${repo}.py")" "${sha:0:8}"
done
