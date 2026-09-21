#!/usr/bin/env bash
: 'Fetch each repository'\''s original assert-pin-only-diff.py for the equivalence test.
Exit status: 0 all fetched, 1 a fetch failed.'
set -o errexit
set -o pipefail
set -o nounset

here="$(cd "$(dirname "$0")/.." && pwd)"
out="${here}/tests/originals"
mkdir -p "${out}"

for repo in rsync-crypt devcontainer-images github-template \
            pre-commit-checklists pre-commit-checklists-demo \
            docker-torrent-box-with-vpn; do
  gh api "repos/ivan-pinatti-labs/${repo}/contents/scripts/assert-pin-only-diff.py" \
    --jq .content | base64 -d > "${out}/${repo}.py"
  printf '%-32s %s lines\n' "${repo}" "$(wc -l < "${out}/${repo}.py")"
done
