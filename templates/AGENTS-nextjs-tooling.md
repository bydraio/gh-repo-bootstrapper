
## Local browser-validation constraints

When a local Playwright suite is present, treat a browser-launch failure before
navigation — for example, macOS `MachPortRendezvousServer` /
`bootstrap_check_in ... Permission denied` — as an environment or
process-launch failure, not an application test failure. Preserve the exact
output. Request the narrowest available permission elevation for the exact
browser-test command; do not weaken agent-wide sandbox or host-execution policy.
If elevation is unavailable or denied, report the constraint and use equivalent
hosted CI evidence where available.

On macOS, use a temporary per-shell descriptor limit when starting a local
Next.js development server:

```sh
ulimit -n 10240 && npm run dev
```

This is a non-persistent per-shell setting. Do not add it to shell profiles,
change system limits, change CI, or alter Playwright configuration. A generated
repository owns its server lifecycle, ports, and test scripts, so follow its
local documentation before combining a manual dev server with browser tests.
If Next.js or Watchpack still reports `EMFILE: too many open files, watch`,
treat it as local host resource exhaustion. Run `npm run test:e2e:local` when that script is available.
Otherwise, run the project's normal Playwright suite with one worker, for
example `npx playwright test --workers=1`. Do not replace the default E2E
command, disable parallel CI, reduce test coverage, or alter
`playwright.config.ts` merely to accommodate a constrained host. Before
retrying, inspect any existing local listeners on the E2E ports; do not
terminate processes you cannot identify. If the raised limit does not resolve
the failure, preserve the exact output and, if present,
`.next/dev/logs/next-development.log` rather than claiming browser validation
passed.

Do not make persistent OS file-limit, watcher, or global sandbox-policy changes
solely to resolve a local validation failure. If the serial command still fails,
record the exact error and report the limitation rather than claiming the
validation passed.

## Tooling
Run all checks before pushing:

```sh
npm run lint          # ESLint
npm run format:check  # Prettier
npm run typecheck     # TypeScript
npm test              # unit/integration tests
npm run audit:production  # runtime advisory floor; requires network access
npm run verify:baselines  # lint/advisory baseline parity
npm run build         # Next.js production build
npm run test:e2e      # Playwright e2e
```

`npm run lint:fix` auto-fixes ESLint violations; `npm run format` auto-fixes
Prettier formatting issues.

In CI, automated validation runs in three tiers:
- **Pull requests (`ci.yml`):** Runs fast validation (`build` only: lint, format, typecheck, unit tests, verify baselines, production build) with browser E2E skipped for rapid feedback (< 2 mins).
- **Push to `main` (`release-please.yml`):** Runs the build suite plus a slim desktop-only Chromium E2E pass (`--project=chromium`).
- **Release Please PR merge (`chore(main): release`):** Runs the full validation suite, including the complete browser E2E matrix and any configured production/runtime checks.

Always run the relevant checks locally before pushing. For changes that alter browser-facing UI or user interactions, run `npm run test:e2e` locally (or `npm run test:e2e:local` when that script is available) before opening or updating a PR.
