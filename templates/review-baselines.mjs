import { appendFileSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { parseAdvisoryRows, parseLintRows } from "./baseline-table.mjs";

const advisoryBaselinePath = new URL("../docs/advisory-baseline.md", import.meta.url);
const lintBaselinePath = new URL("../docs/lint-baseline.md", import.meta.url);
const now = new Date();
const reviewWindowDays = 30;
const releaseStaleDays = 14;
const apiBase = process.env.GITHUB_API_URL ?? "https://api.github.com";

function linesForReviewDates(rows, describe) {
  const upcoming = [];
  const past = [];
  for (const row of rows) {
    const reviewAt = new Date(`${row.reviewDate}T00:00:00.000Z`);
    const daysUntilReview = Math.ceil((reviewAt.valueOf() - now.valueOf()) / 86_400_000);
    const description = describe(row);
    if (daysUntilReview < 0) past.push(description);
    else if (daysUntilReview <= reviewWindowDays) upcoming.push(description);
  }
  return { past, upcoming };
}

async function pagedApi(repository, token, path, collectionKey, label) {
  const values = [];
  let url = `${apiBase}/repos/${repository}/${path}`;
  while (url) {
    const response = await fetch(url, {
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
      },
    });
    if (!response.ok)
      throw new Error(`${label} API returned ${response.status} ${response.statusText}`);
    const body = await response.json();
    const page = collectionKey ? body[collectionKey] : body;
    if (!Array.isArray(page)) throw new Error(`${label} API returned an invalid response`);
    values.push(...page);
    const link = response.headers.get("link") ?? "";
    url = /<([^>]+)>; rel="next"/.exec(link)?.[1] ?? "";
  }
  return values;
}

function dismissedAlerts(repository, token) {
  return pagedApi(
    repository,
    token,
    "dependabot/alerts?state=dismissed&per_page=100",
    null,
    "Dependabot",
  );
}

async function releaseWorkflowRuns(repository, token, query) {
  const response = await fetch(
    `${apiBase}/repos/${repository}/actions/workflows/release-please.yml/runs?${query}`,
    {
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
      },
    },
  );
  if (!response.ok)
    throw new Error(`Release Please API returned ${response.status} ${response.statusText}`);
  const body = await response.json();
  if (!Array.isArray(body.workflow_runs))
    throw new Error("Release Please API returned an invalid response");
  return body.workflow_runs;
}

function npmAuditReport() {
  const audit = spawnSync("npm", ["audit", "--json"], { encoding: "utf8" });
  if (audit.error) throw new Error(`unable to run npm audit: ${audit.error.message}`);
  try {
    return JSON.parse(audit.stdout);
  } catch {
    throw new Error(`npm audit did not return valid JSON. ${audit.stderr || audit.stdout}`);
  }
}

function auditedAdvisoryUrls(report) {
  const urls = new Set();
  for (const vulnerability of Object.values(report.vulnerabilities ?? {}))
    for (const entry of vulnerability.via ?? [])
      if (typeof entry === "object" && typeof entry.url === "string") urls.add(entry.url);
  return urls;
}

function orphanedAdvisoryRows(rows, auditedUrls) {
  return rows
    .filter((row) => !auditedUrls.has(`https://github.com/advisories/${row.ghsa}`))
    .map((row) => `${row.ghsa} (${row.packageName}) — ${row.reviewDate}`);
}

function parity(rows, alerts) {
  const documented = new Set(rows.map(({ ghsa }) => ghsa));
  const dismissed = new Set(
    alerts
      .map((alert) => alert.security_advisory?.ghsa_id)
      .filter((ghsa) => typeof ghsa === "string"),
  );
  return {
    undocumentedDismissals: [...dismissed].filter((ghsa) => !documented.has(ghsa)),
    rowsWithoutDismissal: [...documented].filter((ghsa) => !dismissed.has(ghsa)),
  };
}

function writeSummary(lines, actionable) {
  const summary = ["## Baseline review", "", ...lines, "", "Baseline review completed."].join("\n");
  console.log(summary);
  if (process.env.GITHUB_STEP_SUMMARY)
    appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`);
  if (actionable) process.exitCode = 1;
}

function completionTimestamp(run) {
  const timestamp = run.completed_at ?? run.updated_at;
  const date = new Date(timestamp);
  if (Number.isNaN(date.valueOf()))
    throw new Error("Release Please API returned a completed run without a completion timestamp");
  return timestamp;
}

function ageInDays(run) {
  const date = new Date(completionTimestamp(run));
  return Math.max(0, Math.floor((now.valueOf() - date.valueOf()) / 86_400_000));
}

function releaseHealth(latest, lastSuccess) {
  if (!latest)
    return {
      actionable: true,
      line: `- Release pipeline: stale — \`release-please.yml\` has never completed; no successful run exists. A successful run older than ${releaseStaleDays} days is reported as stale.`,
    };

  const latestAt = completionTimestamp(latest);
  const latestAge = ageInDays(latest);
  const latestConclusion = latest.conclusion ?? "unknown";
  if (!lastSuccess)
    return {
      actionable: true,
      line: `- Release pipeline: stale — latest completed \`release-please.yml\` run concluded ${latestConclusion} at ${latestAt} (${latestAge} days ago); no successful run exists. A successful run older than ${releaseStaleDays} days is reported as stale.`,
    };

  const successAt = completionTimestamp(lastSuccess);
  const successAge = ageInDays(lastSuccess);
  const success = `last successful \`release-please.yml\` run completed successfully at ${successAt} (${successAge} days ago)`;
  if (latestConclusion !== "success")
    return {
      actionable: true,
      line: `- Release pipeline: stale — latest completed \`release-please.yml\` run concluded ${latestConclusion} at ${latestAt} (${latestAge} days ago); ${success}. A successful run older than ${releaseStaleDays} days is reported as stale.`,
    };
  if (successAge > releaseStaleDays)
    return {
      actionable: true,
      line: `- Release pipeline: stale — ${success}; a successful run older than ${releaseStaleDays} days is reported as stale.`,
    };
  return {
    actionable: false,
    line: `- Release pipeline: ${success}; stale after ${releaseStaleDays} days.`,
  };
}

async function main() {
  let rows;
  try {
    rows = parseAdvisoryRows(readFileSync(advisoryBaselinePath, "utf8"));
  } catch (error) {
    writeSummary(
      [
        `- Advisory baseline: could not be parsed — ${error.message}`,
        "- Dependabot parity: could not be determined because the advisory baseline is unavailable.",
        "- Release pipeline: could not be determined because the advisory baseline is unavailable.",
      ],
      true,
    );
    return;
  }

  const { past, upcoming } = linesForReviewDates(
    rows,
    (row) => `${row.ghsa} (${row.packageName}) — ${row.reviewDate}`,
  );
  const lines = [];
  let actionable = false;
  if (past.length) lines.push(`- Overdue advisory reviews:\n  - ${past.join("\n  - ")}`);
  if (past.length) actionable = true;
  if (upcoming.length)
    lines.push(
      `- Advisory reviews due within ${reviewWindowDays} days:\n  - ${upcoming.join("\n  - ")}`,
    );
  if (!past.length && !upcoming.length)
    lines.push(`- Advisory review dates: no rows overdue or due within ${reviewWindowDays} days.`);

  try {
    const orphaned = orphanedAdvisoryRows(rows, auditedAdvisoryUrls(npmAuditReport()));
    if (orphaned.length) {
      lines.push(
        `- Orphaned advisory-baseline rows (advisory not found in \`npm audit\`):\n  - ${orphaned.join("\n  - ")}`,
      );
      actionable = true;
    } else {
      lines.push(
        "- Orphaned advisory-baseline rows: none — every row's advisory appears in `npm audit`.",
      );
    }
  } catch (error) {
    lines.push(`- Orphaned advisory-baseline rows: could not be determined — ${error.message}`);
    actionable = true;
  }

  let lintRows = [];
  let lintParsed = true;
  try {
    lintRows = parseLintRows(readFileSync(lintBaselinePath, "utf8"));
  } catch (error) {
    lintParsed = false;
    lines.push(`- Lint baseline: could not be parsed — ${error.message}`);
    actionable = true;
  }
  if (lintParsed) {
    const { past: lintPast, upcoming: lintUpcoming } = linesForReviewDates(
      lintRows,
      (row) => `${row.rule} in ${row.file} — ${row.reviewDate}`,
    );
    if (lintPast.length) lines.push(`- Overdue lint reviews:\n  - ${lintPast.join("\n  - ")}`);
    if (lintPast.length) actionable = true;
    if (lintUpcoming.length)
      lines.push(
        `- Lint reviews due within ${reviewWindowDays} days:\n  - ${lintUpcoming.join("\n  - ")}`,
      );
    if (!lintPast.length && !lintUpcoming.length)
      lines.push(`- Lint review dates: no rows overdue or due within ${reviewWindowDays} days.`);
  }

  const { GITHUB_REPOSITORY: repository, GITHUB_TOKEN: token } = process.env;
  if (!repository || !token) {
    lines.push(
      "- Dependabot parity: could not be determined because GITHUB_REPOSITORY or GITHUB_TOKEN is unavailable.",
    );
    lines.push(
      "- Release pipeline: could not be determined because GITHUB_REPOSITORY or GITHUB_TOKEN is unavailable.",
    );
    writeSummary(lines, true);
    return;
  }

  try {
    const result = parity(rows, await dismissedAlerts(repository, token));
    actionable ||=
      result.undocumentedDismissals.length > 0 || result.rowsWithoutDismissal.length > 0;
    if (result.undocumentedDismissals.length)
      lines.push(
        `- Dismissed Dependabot alerts without advisory-baseline rows:\n  - ${result.undocumentedDismissals.join("\n  - ")}`,
      );
    if (result.rowsWithoutDismissal.length)
      lines.push(
        `- Advisory-baseline rows without dismissed Dependabot alerts:\n  - ${result.rowsWithoutDismissal.join("\n  - ")}`,
      );
    if (!result.undocumentedDismissals.length && !result.rowsWithoutDismissal.length)
      lines.push(
        "- Dependabot parity: every dismissed alert has a row and every row has a dismissed alert.",
      );
  } catch (error) {
    lines.push(`- Dependabot parity: could not be determined — ${error.message}`);
    actionable = true;
  }
  try {
    const [latestRuns, successfulRuns] = await Promise.all([
      releaseWorkflowRuns(repository, token, "status=completed&per_page=1"),
      releaseWorkflowRuns(repository, token, "status=success&per_page=1"),
    ]);
    const result = releaseHealth(latestRuns[0], successfulRuns[0]);
    lines.push(result.line);
    actionable ||= result.actionable;
  } catch (error) {
    lines.push(`- Release pipeline: could not be determined — ${error.message}`);
    actionable = true;
  }
  writeSummary(lines, actionable);
}

await main();
