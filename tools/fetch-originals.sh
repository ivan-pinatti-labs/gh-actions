#!/usr/bin/env bash
: 'Fetch each repository'\''s original assert-pin-only-diff.py for the equivalence test.
Exit status: 0 all fetched, 1 a fetch failed.'
set -o errexit
set -o pipefail
set -o nounset

here="$(cd "$(dirname "$0")/.." && pwd)"
out="${here}/tests/originals"
mkdir -p "${out}"

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
  sha=$(gh api "repos/ivan-pinatti-labs/${repo}/commits/HEAD" --jq '.sha')

  gh api "repos/ivan-pinatti-labs/${repo}/contents/scripts/assert-pin-only-diff.py?ref=${sha}" \
    --jq .content | base64 -d > "${out}/${repo}.py"
  printf 'pin-only   %-30s %s lines  @%s\n' \
    "${repo}" "$(wc -l < "${out}/${repo}.py")" "${sha:0:8}"

  source_file="${arg_sources[${repo}]:-}"
  if [ -n "${source_file}" ]; then
    mkdir -p "${out}/${repo}/$(dirname "${source_file}")"
    gh api "repos/ivan-pinatti-labs/${repo}/contents/${source_file}?ref=${sha}" \
      --jq .content | base64 -d > "${out}/${repo}/${source_file}"
    printf 'arg source %-30s %s\n' "${repo}" "${source_file}"
  fi
done

# The review-verdict copies, including .github's, which is the one with no bot
# lane and so the one the shared version has to reproduce with an empty list.
for repo in rsync-crypt devcontainer-images github-template \
            pre-commit-checklists pre-commit-checklists-demo \
            docker-torrent-box-with-vpn .github; do
  sha=$(gh api "repos/ivan-pinatti-labs/${repo}/commits/HEAD" --jq '.sha')
  gh api "repos/ivan-pinatti-labs/${repo}/contents/scripts/coderabbit-review-verdict.py?ref=${sha}" \
    --jq .content | base64 -d > "${out}/verdict-${repo}.py"
  printf 'verdict    %-30s %s lines  @%s\n' \
    "${repo}" "$(wc -l < "${out}/verdict-${repo}.py")" "${sha:0:8}"
done
