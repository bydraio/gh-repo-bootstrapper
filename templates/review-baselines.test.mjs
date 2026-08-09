import assert from "node:assert/strict";
import { createServer } from "node:http";
import { chmodSync, copyFileSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const scriptsDirectory = dirname(fileURLToPath(import.meta.url));
const columns = [
  "| GHSA | Package | Severity | Scope (runtime/dev) | Why not fixed | Re-check trigger | Review date |",
  "| ---- | ------- | -------- | ------------------- | ------------- | ---------------- | ----------- |",
];
const lintColumns = [
  "| # | Rule | File | Why this is accepted | Review date |",
  "| - | ---- | ---- | ------------------- | ----------- |",
];

function advisoryBaseline(rows) {
  return ["## Accepted advisories", "", ...columns, ...rows].join("\n");
}

function lintBaseline(rows) {
  return ["## Accepted suppressions", "", ...lintColumns, ...rows].join("\n");
}

function auditReportMatching(...ghsaIds) {
  return {
    vulnerabilities: {
      fixture: {
        via: ghsaIds.map((ghsa) => ({ url: `https://github.com/advisories/${ghsa}` })),
      },
    },
  };
}

function writeFakeNpm(root, scriptBody) {
  const binDir = join(root, "bin");
  mkdirSync(binDir);
  const npmPath = join(binDir, "npm");
  writeFileSync(npmPath, `#!/bin/sh\n${scriptBody}\n`);
  chmodSync(npmPath, 0o755);
  return binDir;
}

function fakeNpmAuditJson(auditReport) {
  return `cat <<'JSON'\n${JSON.stringify(auditReport)}\nJSON\n`;
}

const capturedSuccessfulReleaseRun = {
  id: 30230627141,
  name: "Release Please",
  status: "completed",
  conclusion: "success",
  run_started_at: "2026-07-27T01:47:31Z",
  updated_at: "2026-07-27T01:50:22Z",
  completed_at: null,
};

function successfulRelease(updatedAt = new Date().toISOString()) {
  return { ...capturedSuccessfulReleaseRun, updated_at: updatedAt };
}

async function runFixture({
  rows,
  lintRows = [],
  alerts,
  latestReleaseRuns = [successfulRelease()],
  unfilteredReleaseRuns = latestReleaseRuns,
  successfulReleaseRuns = latestReleaseRuns,
  token = true,
  dependabotStatus = 200,
  releaseStatus = 200,
  auditReport = auditReportMatching("GHSA-aaaa-bbbb-cccc"),
  fakeNpmScript,
}) {
  const root = mkdtempSync(join(tmpdir(), "review-baselines-"));
  const requests = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://fixture.test");
    requests.push(`${url.pathname}?${url.searchParams}`);
    response.setHeader("content-type", "application/json");
    if (url.pathname === "/repos/bydraio/fixture/dependabot/alerts") {
      response.statusCode = dependabotStatus;
      response.end(JSON.stringify(alerts));
      return;
    }
    if (url.pathname === "/repos/bydraio/fixture/actions/workflows/release-please.yml/runs") {
      response.statusCode = releaseStatus;
      response.end(
        JSON.stringify({
          workflow_runs:
            url.searchParams.get("status") === "success"
              ? successfulReleaseRuns
              : url.searchParams.get("status") === "completed"
                ? latestReleaseRuns
                : unfilteredReleaseRuns,
        }),
      );
      return;
    }
    response.statusCode = 404;
    response.end(JSON.stringify({ message: "unexpected fixture request" }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    mkdirSync(join(root, "scripts"));
    mkdirSync(join(root, "docs"));
    for (const file of ["baseline-table.mjs", "review-baselines.mjs"])
      copyFileSync(join(scriptsDirectory, file), join(root, "scripts", file));
    writeFileSync(join(root, "docs/advisory-baseline.md"), advisoryBaseline(rows));
    writeFileSync(join(root, "docs/lint-baseline.md"), lintBaseline(lintRows));
    const binDir = writeFakeNpm(root, fakeNpmScript ?? fakeNpmAuditJson(auditReport));
    const child = spawn(process.execPath, [join(root, "scripts/review-baselines.mjs")], {
      cwd: root,
      env: {
        ...process.env,
        PATH: `${binDir}${delimiter}${process.env.PATH}`,
        GITHUB_API_URL: `http://127.0.0.1:${port}`,
        GITHUB_REPOSITORY: "bydraio/fixture",
        ...(token ? { GITHUB_TOKEN: "fixture-token" } : {}),
      },
    });
    let output = "";
    for (const stream of [child.stdout, child.stderr])
      stream.on("data", (chunk) => (output += chunk));
    const code = await new Promise((resolve) => child.on("exit", resolve));
    return { code, output, requests };
  } finally {
    await new Promise((resolve) => server.close(resolve));
    rmSync(root, { force: true, recursive: true });
  }
}

const documented =
  "| `GHSA-aaaa-bbbb-cccc` | fixture | high | dev | fixture | fixture | 2099-01-01 |";
const matchingAlert = [{ security_advisory: { ghsa_id: "GHSA-aaaa-bbbb-cccc" } }];

test("accepts a captured GitHub workflow-run payload and exits zero when healthy", async () => {
  const freshCapturedRun = successfulRelease();
  const { code, output, requests } = await runFixture({
    rows: [documented],
    alerts: matchingAlert,
    latestReleaseRuns: [freshCapturedRun],
    successfulReleaseRuns: [freshCapturedRun],
  });
  assert.equal(code, 0);
  assert.match(
    output,
    /Orphaned advisory-baseline rows: none — every row's advisory appears in `npm audit`/,
  );
  assert.match(
    output,
    /Dependabot parity: every dismissed alert has a row and every row has a dismissed alert/,
  );
  assert.match(
    output,
    /Release pipeline: last successful `release-please\.yml` run completed successfully/,
  );
  assert.match(output, /Baseline review completed/);
  assert.deepEqual(
    requests.filter((request) => request.includes("release-please.yml/runs")),
    [
      "/repos/bydraio/fixture/actions/workflows/release-please.yml/runs?status=completed&per_page=1",
      "/repos/bydraio/fixture/actions/workflows/release-please.yml/runs?status=success&per_page=1",
    ],
  );
});

test("ignores a newer in-progress release run when determining release health", async () => {
  const freshCompletedRun = successfulRelease();
  const { code, output, requests } = await runFixture({
    rows: [documented],
    alerts: matchingAlert,
    unfilteredReleaseRuns: [{ ...freshCompletedRun, status: "in_progress", conclusion: null }],
    latestReleaseRuns: [freshCompletedRun],
    successfulReleaseRuns: [freshCompletedRun],
  });
  assert.equal(code, 0);
  assert.match(
    output,
    /Release pipeline: last successful `release-please\.yml` run completed successfully/,
  );
  assert.doesNotMatch(output, /Release pipeline: stale/);
  assert.deepEqual(
    requests.filter((request) => request.includes("release-please.yml/runs")),
    [
      "/repos/bydraio/fixture/actions/workflows/release-please.yml/runs?status=completed&per_page=1",
      "/repos/bydraio/fixture/actions/workflows/release-please.yml/runs?status=success&per_page=1",
    ],
  );
});

test("reports both Dependabot parity directions and exits non-zero", async () => {
  const { code, output } = await runFixture({
    rows: [documented],
    alerts: [{ security_advisory: { ghsa_id: "GHSA-dddd-eeee-ffff" } }],
  });
  assert.equal(code, 1);
  assert.match(output, /Dismissed Dependabot alerts without advisory-baseline rows/);
  assert.match(output, /Advisory-baseline rows without dismissed Dependabot alerts/);
});

test("reports an advisory-baseline row whose advisory no longer appears in npm audit", async () => {
  const { code, output } = await runFixture({
    rows: [documented],
    alerts: matchingAlert,
    auditReport: auditReportMatching("GHSA-dddd-eeee-ffff"),
  });
  assert.equal(code, 1);
  assert.match(output, /Orphaned advisory-baseline rows \(advisory not found in `npm audit`\)/);
  assert.match(output, /GHSA-aaaa-bbbb-cccc \(fixture\) — 2099-01-01/);
});

test("reports orphan detection as unavailable when npm audit fails", async () => {
  const { code, output } = await runFixture({
    rows: [documented],
    alerts: matchingAlert,
    fakeNpmScript: "echo 'not json'\nexit 1\n",
  });
  assert.equal(code, 1);
  assert.match(
    output,
    /Orphaned advisory-baseline rows: could not be determined — npm audit did not return valid JSON/,
  );
});

test("reports unavailable credentials as actionable", async () => {
  const { code, output } = await runFixture({ rows: [documented], alerts: [], token: false });
  assert.equal(code, 1);
  assert.match(
    output,
    /could not be determined because GITHUB_REPOSITORY or GITHUB_TOKEN is unavailable/,
  );
  assert.match(output, /Baseline review completed/);
});

test("reports rejected Dependabot API access without claiming healthy parity", async () => {
  const { code, output } = await runFixture({
    rows: [documented],
    alerts: [],
    dependabotStatus: 403,
  });
  assert.equal(code, 1);
  assert.match(output, /Dependabot parity: could not be determined — Dependabot API returned 403/);
  assert.doesNotMatch(
    output,
    /every dismissed alert has a row and every row has a dismissed alert/,
  );
});

test("reports overdue review dates as actionable", async () => {
  const { code, output } = await runFixture({
    rows: [documented.replace("2099-01-01", "2020-01-01")],
    alerts: matchingAlert,
  });
  assert.equal(code, 1);
  assert.match(output, /Overdue advisory reviews/);
  assert.match(output, /Baseline review completed/);
});

test("reports overdue lint review dates as actionable", async () => {
  const { code, output } = await runFixture({
    rows: [documented],
    lintRows: ["| 1 | `no-console` | `e2e/fixture.mjs` | accepted | 2020-01-01 |"],
    alerts: matchingAlert,
  });
  assert.equal(code, 1);
  assert.match(output, /Overdue lint reviews/);
  assert.match(output, /no-console in e2e\/fixture\.mjs — 2020-01-01/);
  assert.match(output, /Baseline review completed/);
});

test("reports upcoming lint review dates as informational", async () => {
  const upcomingDate = new Date(Date.now() + 15 * 86_400_000).toISOString().slice(0, 10);
  const { code, output } = await runFixture({
    rows: [documented],
    lintRows: [`| 1 | \`no-console\` | \`e2e/fixture.mjs\` | accepted | ${upcomingDate} |`],
    alerts: matchingAlert,
  });
  assert.equal(code, 0);
  assert.match(output, /Lint reviews due within 30 days/);
  assert.match(output, /no-console in e2e\/fixture\.mjs/);
});

test("reports unavailable release-health access without claiming it healthy", async () => {
  const { code, output } = await runFixture({
    rows: [documented],
    alerts: matchingAlert,
    releaseStatus: 403,
  });
  assert.equal(code, 1);
  assert.match(
    output,
    /Release pipeline: could not be determined — Release Please API returned 403/,
  );
  assert.doesNotMatch(output, /Release pipeline: last successful/);
});

test("reports a release workflow that has never completed", async () => {
  const { code, output } = await runFixture({
    rows: [documented],
    alerts: matchingAlert,
    latestReleaseRuns: [],
    successfulReleaseRuns: [],
  });
  assert.equal(code, 1);
  assert.match(output, /Release pipeline: stale — `release-please\.yml` has never completed/);
  assert.match(output, /older than 14 days is reported as stale/);
});

test("reports a successful release run older than the declared stale threshold", async () => {
  const oldRelease = new Date(Date.now() - 15 * 86_400_000).toISOString();
  const { code, output } = await runFixture({
    rows: [documented],
    alerts: matchingAlert,
    latestReleaseRuns: [successfulRelease(oldRelease)],
    successfulReleaseRuns: [successfulRelease(oldRelease)],
  });
  assert.equal(code, 1);
  assert.match(output, /Release pipeline: stale — last successful `release-please\.yml` run/);
  assert.match(output, /older than 14 days is reported as stale/);
});

test("reports a failed latest release run as stale and exits non-zero", async () => {
  const { code, output } = await runFixture({
    rows: [documented],
    alerts: matchingAlert,
    latestReleaseRuns: [{ ...successfulRelease(), conclusion: "failure" }],
    successfulReleaseRuns: [successfulRelease()],
  });
  assert.equal(code, 1);
  assert.match(
    output,
    /Release pipeline: stale — latest completed `release-please\.yml` run concluded failure/,
  );
  assert.match(output, /older than 14 days is reported as stale/);
});
