# Branch protection and release PRs — operational runbook

`main` is protected: specific status checks are required, a pull request is required, and the rules
bind admins too. This file records the operational facts that matter when a PR — usually a release
PR — is blocked and the reason is not obvious. Every fact here was established from a real incident,
not from documentation. Dates refer to late July 2026.

## 1. A release PR whose base has advanced carries checks describing a superseded tree

Release Please keeps its PR open and updates its branch only when a new releasable commit lands
(expectation from the tool's behaviour; consistent with the incident, where the bot head stayed at
one SHA — `3bfd1f0` — while `main` advanced without it). If `main` advances for any other reason,
the checks on the release PR still describe the tree as of the last event — a tree that no longer
exists. With required checks the PR can be **blocked correctly by the rules and wrongly in
substance**: the gate is doing its job, but the thing it evaluated is not the thing that would be
merged. Diagnose before believing a red check: compare the PR's merge-ref parents against the
current `main` tip.

## 2. Re-running a failed check does not help

A re-run replays the merge SHA pinned in the original event payload, so it tests the same stale
tree again rather than the current one. What was observed directly: two separate `pull_request`
events — the original run and a close-and-reopen — fetched the same stale merge ref and failed
identically on a file that was already fixed on `main`. No explicit re-run was performed in that
incident; expect one to behave identically, because a re-run re-uses the original event payload
rather than asking for a fresh merge ref. Only a further fresh event produced a different
(recomputed, passing) ref.

## 3. The first fresh event after a base advance may still capture the stale merge ref

The incident timeline, every line anchored to a timestamp or a SHA:

- `main` advanced to `4d583c5` at 06:07:15 UTC.
- A close-and-reopen **54 minutes later** (run 30244655509, created 07:01:42 UTC, a fresh
  `pull_request` event) still fetched the pre-remediation merge ref `d975919` — parents
  `1c54021` + bot head `3bfd1f0` — and failed on the same file.
- A second reopen **11 minutes after that** (run 30245344277, created 07:13:11 UTC) fetched the
  recomputed ref `f0aef8e` — parents `4d583c5` + `3bfd1f0` — and passed.

So waiting did not help: the merge ref had gone unrecomputed for at least 54 minutes, and the
first fresh event captured the stale value anyway. Mechanism, stated as expectation: GitHub
recomputes the merge ref lazily — the first event after a base change may trigger the
recomputation while its own payload captures the pre-recomputation value, and a later event
benefits. The operational rule:

- Before believing any check on a release PR, compare the PR merge ref's parents against the
  current `main` tip (`gh api repos/{owner}/{repo}/pulls/{n}` → `merge_commit_sha`, then inspect
  its parents — the two refs above differ in exactly that parent).
- After any fresh event, check again — do not assume the event refreshed the ref.
- When you need determinism rather than another attempt, use the update-branch endpoint:
  `PUT /repos/{owner}/{repo}/pulls/{n}/update-branch`
  (via `gh api repos/OWNER/REPO/pulls/N/update-branch -X PUT`). Expect it to merge the base into
  the PR head and fire a `synchronize` event against current `main` — the API's contract, stated
  as expectation; it was not needed in the incident, where the second reopen sufficed. On a
  Release Please branch the extra merge commit is expected to be transient, because the bot
  rewrites the branch on its next run.

## 4. A reported `skipped` conclusion satisfies a required check; a check that never reports blocks forever

These are different states and only one of them is safe:

- **Skipped:** `pr-title-check.yml` gates at the job level
  (`if: !startsWith(github.head_ref, 'release-please--')`), so the workflow still triggers and GitHub
  receives a check run with `status: completed, conclusion: skipped`. A reported skip counts as
  satisfied. Verified on a protected branch: a release PR with `validate-title` SKIPPED computed
  CLEAN.
- **Never reports:** if the workflow never triggers, no check run exists and the required context
  stays pending **forever** — the PR can never merge. This is why any repository whose release PRs
  are created with the default `secrets.GITHUB_TOKEN` (which triggers no workflows at all) must not
  have required checks until its release automation uses the GitHub App token shape. Check who
  authored the release PR and whether its rollup is empty before requiring checks on a repository.

## 5. Historical failures in a check rollup do not block

GitHub computes mergeability from the **latest result per check name**. A rollup listing an old
`FAILURE` next to the current `SUCCESS` for the same check is not a blocked state. Observed, not
assumed: a PR whose `test / build` had failed twice historically computed CLEAN once the current run
passed.

## 6. The escape hatch is to disable protection deliberately — never to weaken the check set

With `enforce_admins: true`, nobody — including the operator — can merge a PR whose required checks
are not green. When a PR is genuinely stuck (for example a stale-tree block that update-branch did
not clear), the deliberate remedy is:

1. Remove branch protection on `main`.
2. Merge or repair the PR.
3. Re-apply protection immediately, with the same contexts.

Under pressure the tempting move is to drop a context from the required set "just for this PR". Do
not: a dropped context is invisible the moment the pressure is forgotten, and it converts a one-PR
problem into a permanent fleet-wide hole. Toggling protection off and on is an audible, bounded act;
a weakened check set is neither.

## Quick inspection commands

```sh
gh pr view <n> --repo <owner>/<repo> --json mergeable,mergeStateStatus,statusCheckRollup
gh api repos/<owner>/<repo>/branches/main/protection
gh api repos/<owner>/<repo>/pulls/<n>/update-branch -X PUT   # the deterministic stale-tree lever
```
