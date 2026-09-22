# Bootstrapping this repository's own gate

This is a one time note about the first merge, kept because the situation is
confusing enough to be worth writing down and because the alternative was a
permanent weakness in the check that decides what merges.

## The problem

This repository's own `coderabbit-gate.yml` calls the reusable workflow it
publishes, by relative path. GitHub resolves a relative reusable workflow, and
therefore `job.workflow_sha`, from the same commit as its caller.

Under `merge_group` that commit is the queue's temporary commit, which contains
the pull request's changes. Reading the grading library from there would run
code under test in a job holding `statuses: write`, which is exactly what the
default branch checkout elsewhere in that workflow exists to prevent. So the
workflow refuses, and reads the library from the default branch instead.

On the very first deployment there is no library on the default branch, because
the pull request adding it is the one in the queue. The queue run therefore
fails, and the change that would fix it is the change that cannot merge.

## Why there is no fallback for it

An earlier version trusted the queue commit when the default branch had no
library, reasoning that there was no reviewed copy to prefer and the window
closed after one merge. CodeRabbit refused it on #2 and was right: the window
appeared to close, but the code path stayed reachable indefinitely, and
reaching it needed only the library absent from the default branch. A
conditional weakness in a merge gate is worse than a manual step taken once.

## What to do instead, once

An administrator lands the first commit outside the queue:

1. Confirm the pull request is green on its own head: `Pre-commit`, `Tests`,
   `Pin Only` and `Review Verified` all pass, and CodeRabbit has actually
   reviewed it. None of that is skipped; only the queue is.
2. Temporarily set the `main merge queue` ruleset to `evaluate`, or delete it:

   ```shell
   gh api repos/ivan-pinatti-labs/gh-actions/rulesets --jq '.[]|"\(.id) \(.name)"'
   gh api -X PUT repos/ivan-pinatti-labs/gh-actions/rulesets/<id> \
     -f enforcement=evaluate
   ```

3. Merge the pull request normally.
4. Put the ruleset back to `active` immediately.
5. Confirm the next pull request goes through the queue and that its
   `merge_group` gate run reads the library from `main`. The step logs
   "reading the library from main rather than from the queue's temporary
   commit".

After step 3 the default branch has the library and the situation cannot recur:
every later `merge_group` run finds it there.

## What this does not relax

Branch protection's required contexts and the approval requirement are
untouched, and the pull request is reviewed and green before step 3. The only
thing skipped is the queue's second run of the same check set against its own
temporary commit.
