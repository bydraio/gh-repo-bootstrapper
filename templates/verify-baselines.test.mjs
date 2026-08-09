import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const scriptsDirectory = dirname(fileURLToPath(import.meta.url));
const lintHeader = [
  "## Accepted suppressions",
  "",
  "| # | Rule | File | Why this is accepted | Review date |",
  "| - | ---- | ---- | ------------------- | ----------- |",
].join("\n");
const advisoryHeader = [
  "## Accepted advisories",
  "",
  "| GHSA | Package | Severity | Scope (runtime/dev) | Why not fixed | Re-check trigger | Review date |",
  "| ---- | ------- | -------- | ------------------- | ------------- | ---------------- | ----------- |",
].join("\n");

function runFixture(source) {
  const root = mkdtempSync(join(tmpdir(), "verify-baselines-"));
  try {
    mkdirSync(join(root, "scripts"));
    mkdirSync(join(root, "docs"));
    copyFileSync(
      join(scriptsDirectory, "baseline-table.mjs"),
      join(root, "scripts/baseline-table.mjs"),
    );
    copyFileSync(
      join(scriptsDirectory, "verify-baselines.mjs"),
      join(root, "scripts/verify-baselines.mjs"),
    );
    writeFileSync(join(root, "docs/lint-baseline.md"), lintHeader);
    writeFileSync(join(root, "docs/advisory-baseline.md"), advisoryHeader);
    writeFileSync(join(root, "sample.ts"), source);
    return execFileSync(process.execPath, [join(root, "scripts/verify-baselines.mjs")], {
      cwd: root,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    return error.stderr?.toString() || error.stdout?.toString() || error.message;
  } finally {
    rmSync(root, { force: true, recursive: true });
  }
}

test("requires a lint-baseline row for TypeScript suppression directives", () => {
  for (const directive of ["@ts-ignore", "@ts-expect-error", "@ts-nocheck"])
    assert.match(
      runFixture(
        "/" + `/ ${directive} -- fixture suppression\nconst answer: number = \"wrong\";\n`,
      ),
      /Undocumented suppressions/,
    );
});

test("does not treat bare eslint-disable text as a suppression", () => {
  assert.match(
    runFixture('export const message = "use eslint-disable-next-line no-console to silence";\n'),
    /Baseline verification passed/,
  );
});

test("recognises block-comment ESLint suppressions", () => {
  assert.match(
    runFixture("/" + '* eslint-disable no-console */\nconsole.log("fixture");\n'),
    /Undocumented suppressions/,
  );
});
