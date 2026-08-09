export function cells(line) {
  const trimmed = line.trim();
  if (!trimmed.startsWith("|") || !trimmed.endsWith("|")) return null;
  return trimmed
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim().replace(/^`|`$/g, ""));
}

export function parseTable({ markdown, heading, columns, name, separatorPattern = /^:?-{3,}:?$/ }) {
  const section = new RegExp(`^## ${heading}\\s*$`, "m").exec(markdown);
  if (!section || section.index === undefined) throw new Error(`missing "## ${heading}" section`);
  const remainder = markdown.slice(section.index + section[0].length);
  const nextSection = remainder.search(/^## /m);
  const lines = (nextSection < 0 ? remainder : remainder.slice(0, nextSection))
    .split("\n")
    .filter((line) => line.trim());
  const headerIndex = lines.findIndex((line) => cells(line)?.[0] === columns[0]);
  if (headerIndex < 0) throw new Error(`missing ${name} table header`);
  const header = cells(lines[headerIndex]);
  if (header.length !== columns.length || !header.every((cell, index) => cell === columns[index]))
    throw new Error(`${name} table has an unexpected header`);
  const separator = cells(lines[headerIndex + 1] ?? "");
  if (
    !separator ||
    separator.length !== columns.length ||
    !separator.every((cell) => separatorPattern.test(cell))
  )
    throw new Error(`${name} table is missing its separator row`);

  const rows = [];
  for (const line of lines.slice(headerIndex + 2)) {
    if (!line.trim().startsWith("|")) break;
    const row = cells(line);
    if (!row || row.length !== columns.length || row.some((cell) => !cell))
      throw new Error(`${name} table contains a malformed row`);
    rows.push(row);
  }
  return rows;
}

const advisoryColumns = [
  "GHSA",
  "Package",
  "Severity",
  "Scope (runtime/dev)",
  "Why not fixed",
  "Re-check trigger",
  "Review date",
];
const ghsaPattern = /^GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}$/i;

export function parseAdvisoryRows(markdown) {
  return parseTable({
    markdown,
    heading: "Accepted advisories",
    columns: advisoryColumns,
    name: "accepted-advisories",
  }).map((row) => {
    const [ghsa, packageName, severity, scope, whyNotFixed, recheckTrigger, reviewDate] = row;
    if (!ghsaPattern.test(ghsa)) throw new Error(`invalid GHSA identifier ${JSON.stringify(ghsa)}`);
    if (scope !== "runtime" && scope !== "dev")
      throw new Error(`invalid advisory scope ${JSON.stringify(scope)} for ${ghsa}`);
    return { ghsa, packageName, severity, scope, whyNotFixed, recheckTrigger, reviewDate };
  });
}

const lintColumns = ["#", "Rule", "File", "Why this is accepted", "Review date"];

export function parseLintRows(markdown) {
  return parseTable({
    markdown,
    heading: "Accepted suppressions",
    columns: lintColumns,
    name: "lint-baseline",
    separatorPattern: /^:?-+:?$/,
  }).map((row) => {
    const [index, rule, file, whyAccepted, reviewDate] = row;
    return { index, rule, file, whyAccepted, reviewDate };
  });
}
