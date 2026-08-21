
## Local browser-validation constraints

When a local Playwright suite is present, treat a browser-launch failure before
navigation — for example, macOS `MachPortRendezvousServer` /
`bootstrap_check_in ... Permission denied` — as an environment or
process-launch failure, not an application test failure. Preserve the exact
output. Request the narrowest available permission elevation for the exact
browser-test command; do not weaken agent-wide sandbox or host-execution policy.
If elevation is unavailable or denied, report the constraint and use equivalent
hosted CI evidence where available.

If Next.js or Watchpack reports `EMFILE: too many open files, watch`, treat it
as local host resource exhaustion. First run `npm run test:e2e:local` when that
script is available. Otherwise, run the project's normal Playwright suite with
one worker, for example `npx playwright test --workers=1`. Do not replace the
default E2E command, disable parallel CI, reduce test coverage, or alter
`playwright.config.ts` merely to accommodate a constrained host. Before
retrying, inspect any existing local listeners on the E2E ports; do not
terminate processes you cannot identify.

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

`ci.yml` runs the same checks (via the reusable `test.yml` suite) on every PR.
`npm run lint:fix` auto-fixes ESLint violations; `npm run format` auto-fixes
Prettier formatting issues.
