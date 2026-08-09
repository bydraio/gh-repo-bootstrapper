# Lint Baseline

## What this document covers

This is the baseline for **our own code**: inline suppressions we author, such as
`eslint-disable` and `@ts-expect-error`. It is deliberately separate from
[`docs/advisory-baseline.md`](advisory-baseline.md), which records accepted third-party dependency
security advisories.

This baseline is self-cleaning. ESLint reports an unused disable directive when the code it covered
is removed or refactored. Because `npm run lint` runs with `--max-warnings=0`, that warning fails
CI and requires removing both the stale directive and its row below. Dependency advisories do not
self-clean this way; their review triggers belong in `docs/advisory-baseline.md`. Each accepted
suppression below carries a review date for the same reason: the weekly `npm run review:baselines`
surfaces overdue acceptances alongside overdue advisories. Review-date expiry is reported by the
weekly review only and never gates a pull request. The review cadence is six months from acceptance, the fleet precedent established by the advisory baseline.

## Policy: the baseline is zero

`npm run lint` runs `eslint --max-warnings=0`. A clean run reports `0 problems` and exits 0. Any
warning or error is new work to investigate; do not hide it in a growing baseline.

When a warning appears:

1. **Fix the code.** This is the normal outcome.
2. **Suppress an unavoidable false positive inline.** Use
   `// eslint-disable-next-line <rule> -- <reason>` and add a row below. The reason is mandatory.

Never turn a rule off globally merely to silence an instance. That removes the tripwire for every
future use of the rule.

## Accepted suppressions

There are currently no accepted inline suppressions.

| # | Rule | File | Why this is accepted | Review date |
| - | ---- | ---- | ------------------- | ----------- |

## Considered alternatives (not adopted)

- **Disable the rule globally** — rejected because it removes the signal for all future code.
- **Ignore the warning without an inline reason** — rejected because the next reader cannot tell an
  intentional exception from an oversight.
