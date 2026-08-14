# __REPOSITORY_NAME__

> A Next.js project bootstrapped with GitHub Actions, Release Please, and
> Dependabot. Replace this sentence with the product’s purpose and intended users.

| Detail | Value |
|---|---|
| Status | Initial setup |
| Repository type | Next.js |

## Start here

The bootstrapper supplies repository automation but does not create or patch
`package.json`. Add the application scaffold and its project-specific setup
instructions before shipping.

## Local development

Once the application scaffold is in place, install its locked dependencies and
start the local server:

```sh
npm ci
npm run dev
```

## Verification

Once the application scaffold is in place, install Chromium once per machine,
then run the checks CI enforces on pull requests:

```sh
npx playwright install chromium  # CI adds --with-deps for the bare Linux runner
npm run audit:production
npm run verify:baselines
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
npm run test:e2e
```

## Deployment

Deployment is application-owned. The generated `release-please.yml` only tests
and creates releases; add any provider-specific deployment workflow separately,
preferably as a release-triggered workflow after the application and provider
configuration have been reviewed.

## Quality baselines

The [lint baseline](docs/lint-baseline.md) records justified code suppressions; the
[advisory baseline](docs/advisory-baseline.md) records accepted dependency advisories with reasons
and review dates. Both are automatically enforced as blocking checks; see [AGENTS.md](AGENTS.md) for
the contribution process.

## Project guide

- `AGENTS.md` — branch, commit, pull-request, and validation workflow.
- `docs/branch-protection-runbook.md` — how to unblock required GitHub checks.
