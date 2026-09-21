#!/usr/bin/env bash
: 'Fetch each repository'\''s original assert-pin-only-diff.py for the equivalence test.
Exit status: 0 all fetched, 1 a fetch failed.'
set -o errexit
set -o pipefail
set -o nounset

here="$(cd "$(dirname "$0")/.." && pwd)"
out="${here}/tests/originals"
mkdir -p "${out}"

# The pin-only copies. .github never had one, which is the gap this work also
# closes, so it is absent here on purpose.
for repo in rsync-crypt devcontainer-images github-template \
            pre-commit-checklists pre-commit-checklists-demo \
            docker-torrent-box-with-vpn; do
  gh api "repos/ivan-pinatti-labs/${repo}/contents/scripts/assert-pin-only-diff.py" \
    --jq .content | base64 -d > "${out}/${repo}.py"
  printf 'pin-only   %-30s %s lines\n' "${repo}" "$(wc -l < "${out}/${repo}.py")"
done

# The review-verdict copies, including .github's, which is the one with no bot
# lane and so the one the shared version has to reproduce with an empty list.
for repo in rsync-crypt devcontainer-images github-template \
            pre-commit-checklists pre-commit-checklists-demo \
            docker-torrent-box-with-vpn .github; do
  gh api "repos/ivan-pinatti-labs/${repo}/contents/scripts/coderabbit-review-verdict.py" \
    --jq .content | base64 -d > "${out}/verdict-${repo}.py"
  printf 'verdict    %-30s %s lines\n' "${repo}" "$(wc -l < "${out}/verdict-${repo}.py")"
done
