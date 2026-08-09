# Advisory Baseline

## What this document covers

This is the baseline for **third-party dependencies**: security advisories we have consciously
accepted rather than fixed. It is deliberately separate from
[`docs/lint-baseline.md`](lint-baseline.md), which records inline suppressions in our own code.

The lint baseline is self-cleaning because ESLint reports unused disable directives. An accepted
dependency advisory is not self-cleaning: it can remain accepted silently after its rationale has
expired. Every row here therefore has a concrete re-check trigger and review date.

## Policy: enforced production audit floor

The enforced production dependency floor is **zero undocumented findings at any severity**:

```sh
npm audit --omit=dev
```

Note the absence of `--audit-level`. CI runs `npm run audit:production`, which reads
`npm audit --omit=dev --json` and requires a row in the table below for **every** reported
advisory — a `low` finding blocks the build exactly as a `critical` one does. `--audit-level`
has no effect alongside `--json` (it only sets npm's own exit code), so a threshold in this
command would describe a gate that does not exist.

The checker derives its runtime allowlist from this table and fails closed if the document is
missing or malformed. A row in this document is therefore the only way an accepted runtime
advisory can pass the production audit.

Severity still governs *urgency* — how fast a finding must be fixed rather than accepted — but it
does not govern whether the finding needs a row. Everything does.

A row in this document must never be used to accept a production finding before the fix and upgrade
paths have been tried. Development-only advisories are recorded here when accepted, but do not gate
production CI.

## Decision procedure

For every advisory, decide in this order:

1. **Fix it** in the direct dependency or source that introduces it.
2. **Upgrade past it** when a compatible fixed release exists.
3. **Accept it here** only when the first two options are not currently safe or compatible. Add the
   advisory, package, scope, reason, re-check trigger, and review date to the table below.

Reaching for an accepted-advisory row before trying the first two options is a process failure.

## Accepted advisories

There are currently no accepted dependency advisories.

| GHSA | Package | Severity | Scope (runtime/dev) | Why not fixed | Re-check trigger | Review date |
| ---- | ------- | -------- | ------------------- | ------------- | ---------------- | ----------- |

If a Dependabot alert is dismissed, its dismissal comment must cite this document and the row’s
re-check trigger. A dismissal without a matching row here is not accepted risk; it is an
undocumented dismissal.

## Considered alternatives (not adopted)

- **Dismiss the Dependabot alert without a documented row** — rejected because its rationale and
  expiry condition disappear from review.
- **Accept a production finding rather than fixing or upgrading it** — rejected because the
  production audit floor is zero at high severity and above.
- **Record every development advisory indefinitely** — rejected; record only decisions that cannot
  currently be fixed, with a trigger that forces the decision to be revisited.
