import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { parseAdvisoryRows } from "./baseline-table.mjs";

const baselinePath = new URL("../docs/advisory-baseline.md", import.meta.url);

function fail(message) {
  console.error(`Production advisory baseline error: ${message}`);
  process.exit(1);
}

function parseApprovedRuntimeAdvisories(markdown) {
  return new Set(
    parseAdvisoryRows(markdown)
      .filter(({ scope }) => scope === "runtime")
      .map(({ ghsa }) => `https://github.com/advisories/${ghsa}`),
  );
}
let approvedRuntimeAdvisories;
try {
  approvedRuntimeAdvisories = parseApprovedRuntimeAdvisories(readFileSync(baselinePath, "utf8"));
} catch (error) {
  if (error.code === "ENOENT") fail("docs/advisory-baseline.md is missing");
  throw error;
}
const audit = spawnSync("npm", ["audit", "--omit=dev", "--json"], { encoding: "utf8" });
if (audit.error) fail(`unable to run npm audit: ${audit.error.message}`);
let report;
try {
  report = JSON.parse(audit.stdout);
} catch {
  fail(`npm audit did not return valid JSON. ${audit.stderr || audit.stdout}`);
}
const vulnerabilities = report.vulnerabilities ?? {};
function isApproved(name, seen = new Set()) {
  if (seen.has(name)) return false;
  const vulnerability = vulnerabilities[name];
  if (!vulnerability || !Array.isArray(vulnerability.via) || vulnerability.via.length === 0)
    return false;
  const nextSeen = new Set(seen).add(name);
  return vulnerability.via.every((entry) =>
    typeof entry === "string"
      ? isApproved(entry, nextSeen)
      : typeof entry.url === "string" && approvedRuntimeAdvisories.has(entry.url),
  );
}
const unapproved = Object.keys(vulnerabilities).filter((name) => !isApproved(name));
if (unapproved.length > 0) {
  console.error(`Unapproved production vulnerabilities: ${unapproved.join(", ")}`);
  console.error(audit.stdout);
  process.exit(1);
}
if (Object.keys(vulnerabilities).length === 0)
  console.log("No production dependency vulnerabilities found.");
else {
  console.log("Production audit contains only documented runtime exceptions:");
  for (const advisory of approvedRuntimeAdvisories) console.log(`- ${advisory}`);
}
