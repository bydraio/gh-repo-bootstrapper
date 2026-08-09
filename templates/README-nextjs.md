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

If Vercel and/or Cloudflare Workers deployment was enabled at bootstrap time
(`--vercel` / `--cloudflare`), `release-please.yml` contains a matching
`deploy` and/or `cloudflare-deploy` job that runs production builds after
each release PR is merged — check that file's `jobs:` for which one(s) are
present in this repo. Each present job is gated at runtime by its own
`*_DEPLOY_ENABLED` GitHub variable — the job stays in the workflow file
whether deployment is on or off, so turning it on or off later is
`gh variable set`, not a regeneration:

```sh
gh variable set VERCEL_DEPLOY_ENABLED --body true
gh variable set CLOUDFLARE_DEPLOY_ENABLED --body true
```

Cloudflare Workers deployment assumes a static-export Next.js build
(`output: 'export'` in `next.config`, producing `./out`) and reads
`wrangler.jsonc` for its Worker name and assets directory — see that file's
comments for switching from the default `workers.dev` subdomain to a custom
domain.

## Quality baselines

The [lint baseline](docs/lint-baseline.md) records justified code suppressions; the
[advisory baseline](docs/advisory-baseline.md) records accepted dependency advisories with reasons
and review dates. Both are automatically enforced as blocking checks; see [AGENTS.md](AGENTS.md) for
the contribution process.

## Project guide

- `AGENTS.md` — branch, commit, pull-request, and validation workflow.
- `docs/branch-protection-runbook.md` — how to unblock required GitHub checks.
