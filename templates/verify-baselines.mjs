import { existsSync, readdirSync, readFileSync } from "node:fs";
import { relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseAdvisoryRows, parseLintRows } from "./baseline-table.mjs";

// fileURLToPath, not `.pathname`: a file URL percent-encodes characters that are
// legal in paths, so a checkout under "~/My Projects/app" yields
// "/Users/you/My%20Projects/app" and every resolve() and readFileSync() below
// silently misses. CI runners rarely have such a path; local clones do.
const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const lintBaselinePath = resolve(root, "docs/lint-baseline.md");
const advisoryBaselinePath = resolve(root, "docs/advisory-baseline.md");
const sourceExtensions = new Set([".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"]);
const excludedDirectories = new Set([".git", "node_modules", ".next", "upstream"]);

function fail(message) {
  console.error(`Baseline verification error: ${message}`);
  process.exit(1);
}

function readBaseline(path, label) {
  try {
    return readFileSync(path, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") fail(`${label} is missing`);
    throw error;
  }
}

function isIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}

function walk(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!excludedDirectories.has(entry.name)) files.push(...walk(resolve(directory, entry.name)));
      continue;
    }
    if (sourceExtensions.has(entry.name.slice(entry.name.lastIndexOf("."))))
      files.push(resolve(directory, entry.name));
  }
  return files;
}

function rulesFromEslintDirective(text, file) {
  const rules = text.split("--", 1)[0].trim();
  if (!rules) fail(`suppression in ${file} does not name a rule`);
  return rules.split(/[\s,]+/).filter(Boolean);
}

function count(entries) {
  const counts = new Map();
  for (const entry of entries) counts.set(entry, (counts.get(entry) ?? 0) + 1);
  return counts;
}

const advisoryMarkdown = readBaseline(advisoryBaselinePath, "docs/advisory-baseline.md");
const lintMarkdown = readBaseline(lintBaselinePath, "docs/lint-baseline.md");

let advisoryRows;
let lintRows;
try {
  advisoryRows = parseAdvisoryRows(advisoryMarkdown);
  lintRows = parseLintRows(lintMarkdown);
} catch (error) {
  fail(error.message);
}

for (const row of advisoryRows) {
  if (!isIsoDate(row.reviewDate))
    fail(`invalid ISO review date ${JSON.stringify(row.reviewDate)} for ${row.ghsa}`);
}

for (const row of lintRows) {
  if (!isIsoDate(row.reviewDate))
    fail(
      `invalid ISO review date ${JSON.stringify(row.reviewDate)} for ${row.rule} in ${row.file}`,
    );
}

const documented = [];
for (const row of lintRows) {
  if (!row.rule) fail("lint-baseline row does not name a rule");
  const sourcePath = resolve(root, row.file);
  if (!existsSync(sourcePath)) fail(`lint-baseline file does not exist: ${row.file}`);
  documented.push(`${row.file}\u0000${row.rule}`);
}

const suppressions = [];
for (const sourcePath of walk(root)) {
  const relativePath = relative(root, sourcePath);
  const source = readFileSync(sourcePath, "utf8");
  const directives = source.matchAll(
    /(?:\/\/|\/\*)\s*(eslint-disable(?:-next-line|-line)?|@ts-(?:ignore|expect-error|nocheck))(?=\s|:|\*|$)([^\n*]*)/g,
  );
  for (const [, directive, remainder] of directives) {
    const rules = directive.startsWith("@ts-")
      ? [directive]
      : rulesFromEslintDirective(remainder, relativePath);
    for (const rule of rules) suppressions.push(`${relativePath}\u0000${rule}`);
  }
}

const documentedCounts = count(documented);
const suppressionCounts = count(suppressions);
const missingRows = [];
const orphanedRows = [];
for (const [entry, occurrences] of suppressionCounts)
  if ((documentedCounts.get(entry) ?? 0) < occurrences)
    missingRows.push(entry.replace("\u0000", " — "));
for (const [entry, occurrences] of documentedCounts)
  if ((suppressionCounts.get(entry) ?? 0) < occurrences)
    orphanedRows.push(entry.replace("\u0000", " — "));

if (missingRows.length || orphanedRows.length) {
  if (missingRows.length)
    console.error(`Undocumented suppressions:\n- ${missingRows.join("\n- ")}`);
  if (orphanedRows.length)
    console.error(`Orphaned lint-baseline rows:\n- ${orphanedRows.join("\n- ")}`);
  process.exit(1);
}

console.log(
  `Baseline verification passed: ${suppressions.length} suppression(s), ${advisoryRows.length} advisory row(s).`,
);
