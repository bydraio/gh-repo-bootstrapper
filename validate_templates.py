#!/usr/bin/env python3
"""
validate_templates.py — Render every supported bootstrap.py configuration and
validate the generated files.

Checks performed on each generated file:
  - YAML syntax     (every .yml/.yaml file parses with yaml.safe_load)
  - JSON syntax      (every .json file parses with json.loads)
  - marker replacement (no leftover "__MARKER__" or "# <<MARKER>>" placeholders)
  - workflow/job consistency, checked both directions: every context in
    bootstrap.py.required_status_checks() must name a job that actually
    exists in the generated ci.yml / test.yml / pr-title-check.yml, AND
    every reusable-workflow context the generated ci.yml / test.yml would
    actually produce must be listed in required_status_checks() (so an
    added test.yml job can't silently go unenforced)
  - npm-script assumption consistency: every `npm run <script>` and `npm test`
    command in a template is declared by bootstrap.ASSUMED_NPM_SCRIPTS, and
    every declared assumption is documented by at least one template
  - README rendering: every repository type receives its starter, and Swift
    commands retain the safe formatter path and configured test destination
  - shared AGENTS.md guidance: every generated repository type carries the
    required SDLC, dependency, external-knowledge, and completion guidance

  - branch-protection payload semantics: bootstrap.branch_protection_payload()
    must pin the operator-ruled configuration (strict False, enforce_admins
    True, a required PR with zero required approvals, no push restrictions)
    and contexts identical to required_status_checks(), for every repo type
  - runbook presence: every generated repo carries
    docs/branch-protection-runbook.md with the load-bearing operational facts

Also runs a handful of self-contained self-tests (see run_self_tests())
against synthetic workflow fixtures to prove the missing/unexpected-context
branches of the consistency check actually fire, rather than only exercising
already-consistent generated configurations.

Requires PyYAML (`pip install pyyaml`) — a dev-only dependency for this
script; bootstrap.py itself remains stdlib-only.

Exit status is non-zero if any configuration or self-test fails any check.
"""

import itertools
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Optional, Union

try:
    import yaml
except ImportError:
    sys.exit("error: PyYAML is required to run this script — pip install pyyaml")

import bootstrap

MARKER_RE = re.compile(r"__[A-Z_]+__|# <<[A-Z_]+>>")
NPM_SCRIPT_RE = re.compile(r"\bnpm\s+run\s+([A-Za-z0-9:_-]+)|\bnpm\s+test\b")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

OWN_WORKFLOWS_DIR = Path(__file__).parent / ".github" / "workflows"

BASELINE_DOCUMENT_REQUIREMENTS = {
    "docs/lint-baseline.md": (
        "self-cleaning",
        "docs/advisory-baseline.md",
        "Why this is accepted",
        "Review date",
        "review cadence is six months from acceptance",
    ),
    "docs/advisory-baseline.md": (
        "not self-cleaning",
        # The enforced command, not a severity threshold. audit-production.mjs
        # runs `npm audit --omit=dev --json` and demands a row for every
        # reported advisory at any severity; pinning the old
        # "--audit-level=high" phrase here made the validator enforce the
        # documentation of a gate the code does not implement.
        "npm audit --omit=dev",
        "zero undocumented findings at any severity",
        "npm run audit:production",
        "Re-check trigger",
    ),
}

NEXTJS_BASELINE_REQUIRED_FILES = {
    *bootstrap.NEXTJS_BASELINE_DOCUMENTS,
    bootstrap.NEXTJS_ENFORCED_AUDIT_SCRIPT,
    *bootstrap.NEXTJS_BASELINE_SCRIPTS,
    bootstrap.NEXTJS_BASELINE_REVIEW_WORKFLOW,
    bootstrap.README,
    "AGENTS.md",
}

README_REQUIREMENTS = {
    "nextjs": (
        "## Start here",
        "## Local development",
        "## Verification",
    ),
    "python": (
        "## Local development",
        "### Preferred: uv",
        "uv venv",
        "### Standard-library alternative",
        "python3 -m venv .venv",
    ),
    "swift": ("## Local development", "## Verification"),
    "simple": ("## Start here", "## Project guide"),
}

AGENTS_COMMON_REQUIREMENTS = (
    "## Development workflow",
    "Follow any more-local `AGENTS.md` instructions.",
    "## Dependencies and external interfaces",
    "do not hand-edit a lockfile",
    "## External knowledge and capabilities",
    "Use connected documentation or research capabilities",
    "Use an installed skill only when it matches the task",
    "Do not send secrets, private source, or customer data to external services.",
    "A successful screenshot-generation workflow means only that artifacts were produced; it is not visual approval.",
    "## Definition of done",
    "do not claim unrun checks passed.",
)

BRANCH_PROTECTION_RUNBOOK = "docs/branch-protection-runbook.md"

# The bootstrapper ships the runbook into every generated repository from
# templates/docs-branch-protection-runbook.md, and (after item 20) carries its
# own docs/branch-protection-runbook.md for readers here. The two must not drift;
# check_runbook_copy_matches_template enforces that.
#
# REPO_RUNBOOK uses the same literal path as BRANCH_PROTECTION_RUNBOOK: the
# bootstrapper's own copy and the file generated into each repository are the
# same runbook. The constants are separate because they name different roles
# (this repo's copy vs. the per-generated-repo copy), not different files.
REPO_RUNBOOK = "docs/branch-protection-runbook.md"
TEMPLATE_RUNBOOK = "templates/docs-branch-protection-runbook.md"
REPO_RUNBOOK_PATH = Path(__file__).parent / REPO_RUNBOOK
TEMPLATE_RUNBOOK_PATH = Path(__file__).parent / TEMPLATE_RUNBOOK

RUNBOOK_REQUIRED_PHRASES = (
    "update-branch",
    "skipped",
    "never reports",
    "latest result per check name",
    "disable protection",
)


def configurations():
    """Yield (label, cfg) for every supported bootstrap.py configuration."""
    for postgres in (False, True):
        yield (
            f"nextjs postgres={postgres}",
            {
                "name": "sample-app",
                "repo_type": "nextjs",
                "postgres": postgres,
                "scheme": "",
                "destination": "",
            },
        )

    yield (
        "python",
        {
            "name": "sample-lib",
            "repo_type": "python",
            "postgres": False,
            "scheme": "",
            "destination": "",
        },
    )

    for destination, xcodegen in itertools.product(
        ("iphone", "ipad", "macos"), [False, True]
    ):
        yield (
            f"swift destination={destination} xcodegen={xcodegen}",
            {
                "name": "sample-app",
                "repo_type": "swift",
                "postgres": False,
                "scheme": "SampleApp",
                "destination": destination,
                "xcodegen": xcodegen,
            },
        )

    yield (
        "simple",
        {
            "name": "sample-repo",
            "repo_type": "simple",
            "postgres": False,
            "scheme": "",
            "destination": "",
        },
    )


def check_syntax(label: str, files: dict) -> list:
    errors = []
    for path, content in files.items():
        if path.endswith((".yml", ".yaml")):
            try:
                yaml.safe_load(content)
            except yaml.YAMLError as exc:
                errors.append(f"[{label}] {path}: invalid YAML — {exc}")
        elif path.endswith(".json") or path.endswith(".swift-format"):
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                errors.append(f"[{label}] {path}: invalid JSON — {exc}")
    return errors


def check_nextjs_provider_free(label: str, repo_type: str, files: dict) -> list:
    """Keep provider provisioning out of generated Next.js content.

    `.gitignore` intentionally retains local Vercel and Wrangler cache entries
    for applications that later add their own deployment workflow.
    """
    if repo_type != "nextjs":
        return []

    rendered = "\n".join(
        content for path, content in files.items() if path != ".gitignore"
    ).lower()
    errors = []
    for term in ("vercel", "cloudflare", "wrangler", "deployments: write"):
        if term in rendered:
            errors.append(
                f"[{label}] generated Next.js output still contains retired provider surface {term!r}"
            )
    if "wrangler.jsonc" in files:
        errors.append(f"[{label}] generated Next.js output includes retired wrangler.jsonc")
    gitignore = files.get(".gitignore", "")
    for cache_path in (".vercel/", ".wrangler/"):
        if cache_path not in gitignore:
            errors.append(f"[{label}] .gitignore is missing local tool cache {cache_path!r}")
    return errors


def check_markers(label: str, files: dict) -> list:
    errors = []
    for path, content in files.items():
        leftover = MARKER_RE.findall(content)
        if leftover:
            errors.append(f"[{label}] {path}: unreplaced marker(s) {sorted(set(leftover))}")
    return errors


def check_agents_guidance(label: str, files: dict) -> list:
    """Require the shared SDLC guidance for every generated repository type."""
    agents = files.get("AGENTS.md")
    if agents is None:
        return [f"[{label}] missing AGENTS.md"]
    normalized_agents = " ".join(agents.split())
    return [
        f"[{label}] AGENTS.md is missing common guidance {phrase!r}"
        for phrase in AGENTS_COMMON_REQUIREMENTS
        if phrase not in normalized_agents
    ]


def _template_npm_scripts(templates: dict) -> dict:
    """Map each documented npm script to the template paths that reference it."""
    scripts = {}
    for path, content in templates.items():
        for match in NPM_SCRIPT_RE.finditer(content):
            script = match.group(1) or "test"
            scripts.setdefault(script, set()).add(path)
    return scripts


def check_npm_script_assumptions(templates: dict = None, assumptions: set = None) -> list:
    """Check the bootstrapper-owned documentation contract, not generated repos.

    bootstrap.py intentionally does not create package.json, so this cannot
    prove a future scaffold actually provides a script. It only makes the
    commands in templates explicit and self-consistent with that assumption.
    """
    if templates is None:
        templates = {
            path.relative_to(bootstrap.TEMPLATES_DIR).as_posix(): path.read_text()
            for path in bootstrap.TEMPLATES_DIR.rglob("*")
            if path.is_file()
        }
    if assumptions is None:
        assumptions = bootstrap.ASSUMED_NPM_SCRIPTS

    documented = _template_npm_scripts(templates)
    errors = []
    undeclared = set(documented) - assumptions
    unused = assumptions - set(documented)

    for script in sorted(undeclared):
        errors.append(
            f"template npm script '{script}' is not declared in "
            f"bootstrap.ASSUMED_NPM_SCRIPTS (referenced by {sorted(documented[script])})"
        )
    for script in sorted(unused):
        errors.append(
            f"bootstrap.ASSUMED_NPM_SCRIPTS entry '{script}' is never documented by a template"
        )
    return errors


def check_baseline_documents(label: str, repo_type: str, files: dict) -> list:
    """Ensure policy documents are generated only for the npm/ESLint repo type."""
    expected = set(bootstrap.NEXTJS_BASELINE_DOCUMENTS) if repo_type == "nextjs" else set()
    actual = {path for path in files if path.startswith("docs/") and path.endswith("-baseline.md")}
    errors = []

    missing = expected - actual
    unexpected = actual - expected
    if missing:
        errors.append(f"[{label}] missing baseline document(s) {sorted(missing)}")
    if unexpected:
        errors.append(f"[{label}] unexpected baseline document(s) {sorted(unexpected)}")

    for path in expected & actual:
        for phrase in BASELINE_DOCUMENT_REQUIREMENTS[path]:
            if phrase not in files[path]:
                errors.append(f"[{label}] {path} is missing required policy text {phrase!r}")

    if repo_type == "nextjs":
        missing_files = NEXTJS_BASELINE_REQUIRED_FILES - set(files)
        if missing_files:
            errors.append(f"[{label}] missing baseline file(s) {sorted(missing_files)}")

        audit_script = files.get(bootstrap.NEXTJS_ENFORCED_AUDIT_SCRIPT)
        if audit_script is None:
            errors.append(f"[{label}] missing {bootstrap.NEXTJS_ENFORCED_AUDIT_SCRIPT}")
        else:
            for phrase in ("docs/advisory-baseline.md", "npm", "--omit=dev"):
                if phrase not in audit_script:
                    errors.append(
                        f"[{label}] {bootstrap.NEXTJS_ENFORCED_AUDIT_SCRIPT} is missing {phrase!r}"
                    )
        if "## Baseline process" not in files.get("AGENTS.md", ""):
            errors.append(f"[{label}] AGENTS.md is missing the baseline process guidance")
        readme = files.get(bootstrap.README, "")
        for phrase in ("docs/lint-baseline.md", "docs/advisory-baseline.md"):
            if phrase not in readme:
                errors.append(f"[{label}] README.md is missing the baseline pointer {phrase!r}")

        prettierignore = files.get(".prettierignore", "")
        if ".release-please-manifest.json" not in prettierignore:
            errors.append(
                f"[{label}] .prettierignore must ignore the generated Release Please manifest"
            )

        # Item 11: the lint baseline now carries a review-date column and an
        # honest "Why this is accepted" header. The verifier must parse that
        # shape and the weekly review must report lint expiry, so a generated
        # repo whose scripts drift back to the old single-purpose lint parser
        # must fail validation rather than silently shipping a stale checker.
        baseline_table = files.get("scripts/baseline-table.mjs", "")
        for phrase in ("parseLintRows", "Why this is accepted"):
            if phrase not in baseline_table:
                errors.append(f"[{label}] scripts/baseline-table.mjs is missing {phrase!r}")
        verify_script = files.get("scripts/verify-baselines.mjs", "")
        if "parseLintRows" not in verify_script:
            errors.append(f"[{label}] scripts/verify-baselines.mjs is missing 'parseLintRows'")
        review_script = files.get("scripts/review-baselines.mjs", "")
        for phrase in ("parseLintRows", "Overdue lint reviews"):
            if phrase not in review_script:
                errors.append(f"[{label}] scripts/review-baselines.mjs is missing {phrase!r}")

        test_yml = files.get(".github/workflows/test.yml", "")
        try:
            test_workflow = yaml.safe_load(test_yml) or {}
            build_job = test_workflow["jobs"]["build"]
            steps = build_job["steps"]
        except (KeyError, TypeError, yaml.YAMLError):
            errors.append(f"[{label}] test.yml does not define build steps for the production audit")
        else:
            errors.extend(_blocking_build_job_errors(label, build_job))
            errors.extend(
                _blocking_step_errors(label, steps, "npm run audit:production", "production audit")
            )
            errors.extend(
                _blocking_step_errors(label, steps, "npm run verify:baselines", "baseline verification")
            )

        review_yml = files.get(bootstrap.NEXTJS_BASELINE_REVIEW_WORKFLOW, "")
        try:
            review_workflow = yaml.safe_load(review_yml) or {}
        except yaml.YAMLError as exc:
            errors.append(f"[{label}] baseline-review.yml is invalid YAML — {exc}")
        else:
            triggers = review_workflow.get("on", review_workflow.get(True, {})) or {}
            if set(triggers) != {"schedule", "workflow_dispatch"}:
                errors.append(
                    f"[{label}] baseline-review.yml must be schedule-and-dispatch only, got {sorted(triggers)}"
                )
            permissions = review_workflow.get("permissions", {}) or {}
            if not isinstance(permissions, dict):
                errors.append(
                    f"[{label}] baseline-review.yml permissions must be a mapping granting vulnerability-alerts: read"
                )
            else:
                if permissions.get("actions") != "read":
                    errors.append(f"[{label}] baseline-review.yml must grant actions: read")
                if permissions.get("vulnerability-alerts") != "read":
                    errors.append(f"[{label}] baseline-review.yml must grant vulnerability-alerts: read")
                if "security-events" in permissions:
                    errors.append(f"[{label}] baseline-review.yml must not use security-events permissions")
    return errors


def check_readme(label: str, cfg: dict, files: dict) -> list:
    """Ensure every generated repository has an actionable README starter."""
    repo_type = cfg["repo_type"]
    readme = files.get(bootstrap.README)
    if readme is None:
        return [f"[{label}] missing {bootstrap.README}"]

    errors = [
        f"[{label}] README.md is missing {phrase!r}"
        for phrase in README_REQUIREMENTS[repo_type]
        if phrase not in readme
    ]
    if repo_type == "swift":
        destination = cfg.get("destination") or "iphone"
        expected_commands = (
            "xcrun swift-format lint --recursive --strict .",
            "xcodebuild test",
            f"-scheme {shlex.quote(cfg['scheme'])}",
            f'-destination "{bootstrap._DESTINATION_EXAMPLES[destination]}"',
        )
        for command in expected_commands:
            if command not in readme:
                errors.append(f"[{label}] Swift README.md is missing {command!r}")
    return errors


def _blocking_build_job_errors(label: str, build_job: dict) -> list:
    if "if" in build_job:
        return [f"[{label}] template build job must not be conditional"]
    if build_job.get("continue-on-error", False) is not False:
        return [f"[{label}] template build job must be blocking"]
    return []


def _blocking_step_errors(label: str, steps: list, command: str, description: str) -> list:
    matching = [
        step for step in steps if isinstance(step, dict) and step.get("run") == command
    ]
    if len(matching) != 1:
        return [f"[{label}] test.yml does not run the enforced {description} exactly once"]
    step = matching[0]
    if "if" in step:
        return [f"[{label}] template {description} must not be conditional"]
    if step.get("continue-on-error", False) is not False:
        return [f"[{label}] template {description} must be blocking"]
    return []


def _job_ids(workflow: dict) -> set:
    return set((workflow or {}).get("jobs", {}) or {})


def _reusable_call_targets(workflow: dict) -> dict:
    """Map caller job id -> local workflow file path it calls via `uses:`."""
    targets = {}
    for job_id, job in (workflow.get("jobs", {}) or {}).items():
        uses = job.get("uses", "")
        if uses.startswith("./.github/workflows/"):
            targets[job_id] = uses.removeprefix("./.github/workflows/")
    return targets


def _actual_reusable_contexts(ci_yml: str, test_yml: str, target_name: str = "test.yml") -> set:
    """Required-check-style "{caller job} / {called job}" contexts actually
    produced by a caller workflow (e.g. ci.yml) invoking a reusable workflow
    (e.g. test.yml) via `uses: ./.github/workflows/<target_name>`."""
    ci = yaml.safe_load(ci_yml)
    test = yaml.safe_load(test_yml)
    call_targets = _reusable_call_targets(ci)
    test_jobs = _job_ids(test)
    return {
        f"{caller} / {job}"
        for caller, target in call_targets.items()
        if target == target_name
        for job in test_jobs
    }


def _compare_contexts(expected: set, actual: set) -> tuple:
    """Return (missing, unexpected): contexts required-status-checks expects
    that don't exist, and contexts that exist but aren't required — either
    direction means the branch-protection check list has drifted from the
    generated workflows."""
    return expected - actual, actual - expected


def check_workflow_job_consistency(
    label: str, repo_type: str, files: dict, checks: list = None
) -> list:
    errors = []
    if checks is None:
        checks = bootstrap.required_status_checks(repo_type)

    title_check_job = "validate-title"
    pr_title_yml = files.get(".github/workflows/pr-title-check.yml")
    if pr_title_yml is not None:
        jobs = _job_ids(yaml.safe_load(pr_title_yml))
        if title_check_job not in jobs:
            errors.append(
                f"[{label}] required check '{title_check_job}' has no matching job "
                f"in pr-title-check.yml (jobs: {sorted(jobs)})"
            )

    ci_yml = files.get(".github/workflows/ci.yml")
    test_yml = files.get(".github/workflows/test.yml")
    non_title_checks = [c for c in checks if c != title_check_job]

    # Even with no non-title checks expected, a generated ci.yml/test.yml
    # pair that calls out to reusable jobs would produce *unexpected*
    # contexts — so run the comparison whenever those files exist, not only
    # when non_title_checks is non-empty.
    if ci_yml is None or test_yml is None:
        if non_title_checks:
            errors.append(
                f"[{label}] required check(s) {non_title_checks} expect ci.yml/test.yml "
                f"but one or both were not generated"
            )
        return errors

    actual_contexts = _actual_reusable_contexts(ci_yml, test_yml)
    expected_contexts = set(non_title_checks)
    missing, unexpected = _compare_contexts(expected_contexts, actual_contexts)

    if missing:
        errors.append(
            f"[{label}] required check context(s) {sorted(missing)} do not "
            f"correspond to any job in the generated ci.yml/test.yml "
            f"(available: {sorted(actual_contexts)})"
        )
    if unexpected:
        errors.append(
            f"[{label}] generated ci.yml/test.yml produce context(s) "
            f"{sorted(unexpected)} that required_status_checks({repo_type!r}) "
            f"doesn't list — update required_status_checks() to match"
        )

    return errors


def _triggers(workflow: dict) -> dict:
    """Return a workflow's `on:` mapping.

    YAML 1.1 resolves the bare word `on` to boolean True, so yaml.safe_load
    keys a workflow's trigger block under True rather than "on". Reading
    workflow["on"] silently yields nothing and every trigger-based assertion
    passes vacuously — so both spellings are accepted here, and this is the
    only place that detail needs to be known.
    """
    return workflow.get("on") or workflow.get(True) or {}


def _workflow_paths(files: dict) -> list:
    return sorted(
        path
        for path in files
        if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
    )


# Every generated workflow's top-level permissions, asserted exactly. A
# rendered path absent from this map is itself an error (see
# check_workflow_permissions) — a new workflow template must be a deliberate
# addition here, not an oversight.
#
# release-please.yml holds only {contents: read}: verified empirically against
# a live release run (finding #11), not by reasoning. googleapis/release-
# please-action was passed the explicit App token from create-github-app-token,
# and with the workflow scoped to read and no job-level override, PR creation,
# PR merge, tag creation, and GitHub Release creation all succeeded with no
# GITHUB_TOKEN write-permission error. That shows this run did not need a
# write fallback for those operations — it does not prove no read-only-shaped
# fallback path exists for some unobserved case. Do not broaden this without
# re-verifying against a live run first: narrowing it wrongly fails loudly
# (the next release is dead), but widening it wrongly fails silently — nothing
# breaks, it just grants standing write for no reason, which is exactly #11's
# original complaint.
EXPECTED_WORKFLOW_PERMISSIONS = {
    ".github/workflows/ci.yml": {"contents": "read"},
    ".github/workflows/test.yml": {"contents": "read"},
    ".github/workflows/release-please.yml": {"contents": "read"},
    ".github/workflows/pr-title-check.yml": {"pull-requests": "read"},
    ".github/workflows/baseline-review.yml": {
        "actions": "read",
        "contents": "read",
        "vulnerability-alerts": "read",
    },
}

# Job-level permissions, keyed by (workflow path, job id) and asserted as an
# exact expected *declaration*, not merely an allowlist for whatever a job
# happens to declare. A value of `None` means the job must declare no
# permissions block at all; a dict means it must declare exactly that one —
# in both cases the check is active whether or not the job currently has a
# block, so removing a required block is caught exactly like widening one.
# A (path, job_id) pair absent from this map entirely is a job this policy
# has no opinion on: it may or may not declare permissions, but if it does,
# the declaration must still be a recognised one (see the "unexpected
# job-level permissions block" branch below).
#
# release-please: relies entirely on the workflow-level {contents: read} plus
# the App token — a job-level grant here is exactly the kind of future
# addition #11 was raised to stop from passing unexamined, the way the old
# filename exemption let it.
EXPECTED_JOB_PERMISSIONS = {
    (".github/workflows/release-please.yml", "release-please"): None,
}


def check_workflow_permissions(label: str, files: dict) -> list:
    """Every generated workflow and job must scope GITHUB_TOKEN explicitly,
    minimally, and exactly — not merely "some mapping" (#10) and not merely
    "this file may hold write" (#11).

    Four assertions, because presence and boundedness are each weaker than
    the property that actually matters — an exact match:

    1. Every generated workflow path is a recognised one. An unmapped path
       means a new workflow template was added without updating
       EXPECTED_WORKFLOW_PERMISSIONS — the same "presence is not correctness"
       gap #10 exposed, one layer up, for the map itself.
    2. Its top-level permissions block exists, is a mapping (not a scalar like
       `read-all`, valid GitHub syntax but not an explicit per-scope grant),
       and equals its expected map exactly.
    3. Every job named in EXPECTED_JOB_PERMISSIONS is checked as an exact
       expected *declaration*, not merely an allowlist for a block it happens
       to have: a job expected to hold `None` must declare no block, and a job
       expected to hold a map must declare exactly that map — declaring
       nothing when a map is expected is caught the same as declaring the
       wrong map, closing the gap where deleting a required permission block
       passed silently and left a workflow to inherit an unsuitable default.
    4. A job outside that map that declares any permissions block is rejected
       outright as unexpected — an allowlist by (file, job), not a write/read
       heuristic that a new job-level grant could satisfy just by being
       read-only-shaped.
    """
    errors = []
    for path in _workflow_paths(files):
        workflow = yaml.safe_load(files[path]) or {}

        expected_top = EXPECTED_WORKFLOW_PERMISSIONS.get(path)
        if expected_top is None:
            errors.append(
                f"[{label}] {path} is not a recognised generated workflow — add "
                f"its expected permissions to EXPECTED_WORKFLOW_PERMISSIONS"
            )
        else:
            permissions = workflow.get("permissions")
            if permissions is None:
                errors.append(
                    f"[{label}] {path} declares no top-level permissions — "
                    f"expected exactly {expected_top}"
                )
            elif not isinstance(permissions, dict):
                errors.append(
                    f"[{label}] {path} permissions must be a mapping of "
                    f"explicit scopes, not {permissions!r}"
                )
            elif permissions != expected_top:
                errors.append(
                    f"[{label}] {path} must grant exactly {expected_top}, got "
                    f"{permissions}"
                )

        for job_id, job in (workflow.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            # "permissions" in job, not job.get("permissions") is not None: a
            # bare `permissions:` key with no value parses to None in YAML,
            # same as an absent key — .get() alone cannot tell a declared-null
            # block from no block at all, and a declared-null block is still a
            # declaration that must be rejected wherever none is expected.
            declared = "permissions" in job
            job_permissions = job.get("permissions")
            key = (path, job_id)
            if key not in EXPECTED_JOB_PERMISSIONS:
                if declared:
                    errors.append(
                        f"[{label}] {path} job '{job_id}' declares an unexpected "
                        f"job-level permissions block {job_permissions!r} — add "
                        f"it to EXPECTED_JOB_PERMISSIONS if intentional"
                    )
                continue

            expected_job = EXPECTED_JOB_PERMISSIONS[key]
            if expected_job is None:
                if declared:
                    errors.append(
                        f"[{label}] {path} job '{job_id}' must not declare its "
                        f"own permissions block — it relies on the "
                        f"workflow-level {EXPECTED_WORKFLOW_PERMISSIONS.get(path)} "
                        f"plus the explicit App token (verified against a live "
                        f"release run, finding #11)"
                    )
            elif not declared:
                errors.append(
                    f"[{label}] {path} job '{job_id}' declares no permissions "
                    f"block — expected exactly {expected_job}"
                )
            elif not isinstance(job_permissions, dict):
                errors.append(
                    f"[{label}] {path} job '{job_id}' permissions must be a "
                    f"mapping of explicit scopes, not {job_permissions!r}"
                )
            elif job_permissions != expected_job:
                errors.append(
                    f"[{label}] {path} job '{job_id}' must grant exactly "
                    f"{expected_job}, got {job_permissions}"
                )
    return errors


def check_sha_pinned_actions(label: str, files: dict) -> list:
    """Every external `uses:` must pin a full 40-character commit SHA.

    GitHub's "Require actions to be pinned to a full-length commit SHA" repo
    setting (bootstrap.py's configure_repo() sets sha_pinning_required: true)
    rejects any run whose workflow references a tag or branch instead — a
    regression here would fail the first real workflow run, not just this
    validator, so it is caught here. Local reusable-workflow calls
    (`./.github/workflows/...`) are exempt: the setting does not require them
    to use SHAs, and they carry no external supply-chain exposure.
    """
    errors = []
    for path in _workflow_paths(files):
        workflow = yaml.safe_load(files[path]) or {}
        for job_id, job in (workflow.get("jobs", {}) or {}).items():
            if not isinstance(job, dict):
                continue
            refs = []
            job_uses = job.get("uses")
            if isinstance(job_uses, str):
                refs.append(("job", job_uses))
            for step in job.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("uses"), str):
                    refs.append(("step", step["uses"]))

            for kind, uses in refs:
                if uses.startswith("./"):
                    continue
                if "@" not in uses:
                    errors.append(
                        f"[{label}] {path} job '{job_id}' {kind} `uses: {uses}` "
                        f"has no @ref to pin"
                    )
                    continue
                ref = uses.rsplit("@", 1)[1]
                if not COMMIT_SHA_RE.match(ref):
                    errors.append(
                        f"[{label}] {path} job '{job_id}' {kind} `uses: {uses}` "
                        f"is not pinned to a full 40-character commit SHA"
                    )
    return errors


def _own_workflow_files() -> dict:
    return {
        f".github/workflows/{path.name}": path.read_text()
        for path in OWN_WORKFLOWS_DIR.glob("*.yml")
    }


def check_reusable_workflow_inputs(label: str, files: dict) -> list:
    """Assert every `with:` key on a local reusable-workflow call is declared.

    GitHub fails the whole workflow at parse time on an undeclared input
    ("Invalid input, <name> is not defined in the referenced workflow"), so a
    caller/callee drift here doesn't degrade a run — it stops the workflow ever
    running. That is how release-please.yml came to be inert on every generated
    Python repo: the `full` input was added to test.yml, test-swift.yml and
    test-swift-xcodegen.yml and passed by both callers, but never declared in
    test-python.yml. check_workflow_job_consistency matches job *ids*, so it saw
    nothing wrong. Checked both directions — a required input the caller never
    supplies fails the same way.
    """
    errors = []
    for caller_path in _workflow_paths(files):
        caller = yaml.safe_load(files[caller_path]) or {}
        for job_id, job in (caller.get("jobs", {}) or {}).items():
            if not isinstance(job, dict):
                continue
            uses = job.get("uses", "")
            if not uses.startswith("./.github/workflows/"):
                continue

            target_path = f".github/workflows/{uses.removeprefix('./.github/workflows/')}"
            target_source = files.get(target_path)
            if target_source is None:
                errors.append(
                    f"[{label}] {caller_path} job '{job_id}' calls {uses} "
                    f"but that workflow is not generated"
                )
                continue

            target = yaml.safe_load(target_source) or {}
            triggers = _triggers(target)
            if "workflow_call" not in triggers:
                # Checked before the input comparison, not folded into it: a
                # target that dropped `on: workflow_call` while its caller
                # supplies no inputs produces two empty dicts, so every
                # per-input assertion below passes vacuously while the call
                # itself is invalid. GitHub refuses to run it.
                errors.append(
                    f"[{label}] {caller_path} job '{job_id}' calls {target_path}, "
                    f"which does not declare `on: workflow_call` and is "
                    f"therefore not callable (triggers: {sorted(map(str, triggers))})"
                )
                continue

            call_trigger = triggers.get("workflow_call") or {}
            declared = call_trigger.get("inputs") or {}
            supplied = job.get("with") or {}

            for name in sorted(set(supplied) - set(declared)):
                errors.append(
                    f"[{label}] {caller_path} job '{job_id}' passes input "
                    f"'{name}' to {target_path}, which does not declare it — "
                    f"GitHub rejects this at parse time (declared: "
                    f"{sorted(declared)})"
                )
            for name, spec in sorted(declared.items()):
                if isinstance(spec, dict) and spec.get("required") and name not in supplied:
                    errors.append(
                        f"[{label}] {caller_path} job '{job_id}' omits required "
                        f"input '{name}' of {target_path}"
                    )
    return errors


def check_release_please_config(label: str, cfg: dict, files: dict) -> list:
    """Assert the *values* in the rendered Release Please config, not just that
    it parses.

    check_syntax calls json.loads and discards the result, so every rendered
    JSON file was checked for parseability and nothing else. That is how every
    Swift repo came to ship "package-name": "DEPENDENCY_NOTE" — generate_files()
    rebound its `name` local in an unrelated marker loop, and no assertion ever
    looked at the value.
    """
    source = files.get("release-please-config.json")
    if source is None:
        return [f"[{label}] missing release-please-config.json"]
    try:
        config = json.loads(source)
    except json.JSONDecodeError as exc:
        return [f"[{label}] release-please-config.json: invalid JSON — {exc}"]

    errors = []
    package = (config.get("packages") or {}).get(".")
    if not isinstance(package, dict):
        return [f"[{label}] release-please-config.json has no '.' package entry"]

    expected_name = cfg["name"]
    if package.get("package-name") != expected_name:
        errors.append(
            f"[{label}] release-please-config.json package-name is "
            f"{package.get('package-name')!r}, expected {expected_name!r}"
        )
    expected_release_type = "node" if cfg["repo_type"] == "nextjs" else "simple"
    if package.get("release-type") != expected_release_type:
        errors.append(
            f"[{label}] release-please-config.json release-type is "
            f"{package.get('release-type')!r}, expected {expected_release_type!r}"
        )
    if config.get("include-component-in-tag") is not False:
        errors.append(
            f"[{label}] release-please-config.json must set "
            f"include-component-in-tag: false (single-package repos tag vX.Y.Z)"
        )

    manifest_source = files.get(".release-please-manifest.json")
    if manifest_source is None:
        errors.append(f"[{label}] missing .release-please-manifest.json")
    else:
        try:
            if json.loads(manifest_source).get(".") != "0.1.0":
                errors.append(
                    f"[{label}] .release-please-manifest.json must start a new "
                    f"repo at '.': '0.1.0'"
                )
        except json.JSONDecodeError as exc:
            errors.append(f"[{label}] .release-please-manifest.json: invalid JSON — {exc}")
    return errors


def check_branch_protection_payload(label: str, repo_type: str, payload: dict = None) -> list:
    """Assert the branch-protection policy a generated repo is born with.

    The contexts check (check_workflow_job_consistency) proves the required
    checks exist; this proves the *configuration* carrying them matches the
    operator's item-10 rulings — a payload proposing strict True again, or a
    dropped context, must fail here rather than in the next generated repo.
    """
    if payload is None:
        payload = bootstrap.branch_protection_payload(repo_type)
    errors = []

    rsc = payload.get("required_status_checks") or {}
    if rsc.get("strict") is not False:
        errors.append(
            f"[{label}] branch protection must set strict: False "
            f"(ruled: up-to-date requirement strands release PRs)"
        )
    expected_contexts = bootstrap.required_status_checks(repo_type)
    if rsc.get("contexts") != expected_contexts:
        errors.append(
            f"[{label}] protection contexts {rsc.get('contexts')} do not match "
            f"required_status_checks({repo_type!r}) {expected_contexts}"
        )
    if payload.get("enforce_admins") is not True:
        errors.append(f"[{label}] branch protection must enforce admins")

    reviews = payload.get("required_pull_request_reviews")
    if not isinstance(reviews, dict) or reviews.get("required_approving_review_count") != 0:
        errors.append(
            f"[{label}] branch protection must require a PR with zero required approvals"
        )
    if payload.get("restrictions") is not None:
        errors.append(f"[{label}] branch protection must not add push restrictions")
    return errors


def check_runbook(label: str, files: dict) -> list:
    """Every generated repo is born with the branch-protection runbook.

    Its facts were bought with real incidents; a generated repo that lacks
    them rediscovers each one the hard way."""
    content = files.get(BRANCH_PROTECTION_RUNBOOK)
    if content is None:
        return [f"[{label}] missing {BRANCH_PROTECTION_RUNBOOK}"]
    return [
        f"[{label}] {BRANCH_PROTECTION_RUNBOOK} is missing operational fact {phrase!r}"
        for phrase in RUNBOOK_REQUIRED_PHRASES
        if phrase not in content
    ]


def _read_file_or_none(path: Union[str, Path]) -> Optional[bytes]:
    """Read the file at the given path, or None if it is absent.

    Used by check_runbook_copy_matches_template so a missing file becomes a
    labelled error instead of an abort — the same defensive discipline case 21
    established for the generated-runbook check."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def check_runbook_copy_matches_template(
    label: str, repo_copy: Optional[bytes], template_copy: Optional[bytes]
) -> list:
    """The bootstrapper's own docs/ runbook must match the template byte-for-byte.

    The template ships into every generated repository; the repo's own copy is
    what readers here see. A silent drift between the two means the repository
    documents one operational runbook while shipping another. Both files live in
    this one repository and validate-templates is already a required check here,
    so the assertion is enforced the moment it is written."""
    if repo_copy is None:
        return [f"[{label}] missing {REPO_RUNBOOK}"]
    if template_copy is None:
        return [f"[{label}] missing {TEMPLATE_RUNBOOK}"]
    if repo_copy != template_copy:
        return [
            f"[{label}] {REPO_RUNBOOK} differs from {TEMPLATE_RUNBOOK} — "
            "the repository's own runbook must match the template byte-for-byte "
            "so this repo and the repositories it generates never document "
            "different gates"
        ]
    return []


# ---------------------------------------------------------------------------
# Self-tests for check_workflow_job_consistency itself — these use synthetic
# workflow fixtures (not bootstrap.generate_files output) to prove the missing
# and unexpected branches of the consistency check actually fire, rather than
# only exercising the already-consistent generated configurations.
# ---------------------------------------------------------------------------


def _fixture_files(test_job_ids: list) -> dict:
    jobs_yaml = "\n".join(f"    {job_id}: {{}}" for job_id in test_job_ids)
    return {
        ".github/workflows/pr-title-check.yml": "jobs:\n  validate-title: {}\n",
        ".github/workflows/ci.yml": "jobs:\n  test:\n    uses: ./.github/workflows/test.yml\n",
        ".github/workflows/test.yml": f"jobs:\n{jobs_yaml}\n",
    }


def run_self_tests() -> list:
    errors = []

    # Case 1: missing context — required_status_checks expects "test / test"
    # but test.yml's only job is "unit", so no "test / test" context exists.
    files = _fixture_files(["unit"])
    result = check_workflow_job_consistency(
        "self-test:missing", "python", files, checks=["validate-title", "test / test"]
    )
    if not any("do not correspond" in e for e in result):
        errors.append(f"self-test 'missing context' did not fail as expected: {result}")

    # Case 2: unexpected context — test.yml has an extra "lint" job producing
    # "test / lint", which required_status_checks doesn't list.
    files = _fixture_files(["test", "lint"])
    result = check_workflow_job_consistency(
        "self-test:unexpected", "python", files, checks=["validate-title", "test / test"]
    )
    if not any("doesn't list" in e for e in result):
        errors.append(f"self-test 'unexpected context' did not fail as expected: {result}")

    # Case 3: consistent — no errors expected.
    files = _fixture_files(["test"])
    result = check_workflow_job_consistency(
        "self-test:consistent", "python", files, checks=["validate-title", "test / test"]
    )
    if result:
        errors.append(f"self-test 'consistent' unexpectedly failed: {result}")

    # Case 4: template command omitted from assumptions.
    result = check_npm_script_assumptions(
        {"AGENTS-nextjs-tooling.md": "npm run lint\nnpm test\n"}, {"test"}
    )
    if not any("not declared" in e for e in result):
        errors.append(f"self-test 'undeclared npm script' did not fail as expected: {result}")

    # Case 5: stale assumption no template actually documents.
    result = check_npm_script_assumptions(
        {"AGENTS-nextjs-tooling.md": "npm test\n"}, {"test", "lint"}
    )
    if not any("never documented" in e for e in result):
        errors.append(f"self-test 'unused npm assumption' did not fail as expected: {result}")

    # Case 6: shared agent guidance applies to every generated repository type,
    # not only the Next.js configuration that has baseline guidance.
    files = bootstrap.generate_files(
        next(cfg for _, cfg in configurations() if cfg["repo_type"] == "python")
    )
    files["AGENTS.md"] = files["AGENTS.md"].replace("## Definition of done", "")
    result = check_agents_guidance("self-test:missing common agents guidance", files)
    if not any("Definition of done" in e for e in result):
        errors.append(
            "self-test 'missing common agents guidance' did not fail as expected: "
            f"{result}"
        )

    # Case 7: a Next.js configuration must carry both policy documents.
    result = check_baseline_documents("self-test:missing baseline", "nextjs", {})
    if not any("missing baseline document" in e for e in result):
        errors.append(f"self-test 'missing baseline document' did not fail as expected: {result}")

    # Case 7: npm/ESLint policy docs are not valid output for Swift.
    result = check_baseline_documents(
        "self-test:unexpected baseline",
        "swift",
        {"docs/lint-baseline.md": ""},
    )
    if not any("unexpected baseline document" in e for e in result):
        errors.append(f"self-test 'unexpected baseline document' did not fail as expected: {result}")

    # Case 8: a Next.js configuration must ship the executable audit checker,
    # not only prose that claims an advisory floor is enforced.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files.pop(bootstrap.NEXTJS_ENFORCED_AUDIT_SCRIPT, None)
    result = check_baseline_documents("self-test:missing audit checker", "nextjs", files)
    if not any("missing scripts/audit-production.mjs" in e for e in result):
        errors.append(f"self-test 'missing audit checker' did not fail as expected: {result}")

    # Case 9: the template must run the checker as a blocking step. Quoting a
    # truthy value must not evade the semantic workflow check.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[".github/workflows/test.yml"] = files[".github/workflows/test.yml"].replace(
        "- run: npm run audit:production",
        "- run: npm run audit:production\n        continue-on-error: \"true\"",
        1,
    )
    result = check_baseline_documents("self-test:quoted non-blocking audit", "nextjs", files)
    if not any("template production audit must be blocking" in e for e in result):
        errors.append(f"self-test 'quoted non-blocking audit' did not fail as expected: {result}")

    # Case 10: YAML permits mapping keys in either order, so the same guard
    # must reject a truthy continue-on-error before the run command too.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[".github/workflows/test.yml"] = files[".github/workflows/test.yml"].replace(
        "- run: npm run audit:production",
        "- continue-on-error: true\n        run: npm run audit:production",
        1,
    )
    result = check_baseline_documents("self-test:reordered non-blocking audit", "nextjs", files)
    if not any("template production audit must be blocking" in e for e in result):
        errors.append(f"self-test 'reordered non-blocking audit' did not fail as expected: {result}")

    # Case 11: a conditional audit step can be skipped entirely, so the
    # template must reject it rather than trying to classify conditions.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[".github/workflows/test.yml"] = files[".github/workflows/test.yml"].replace(
        "- run: npm run audit:production",
        "- run: npm run audit:production\n        if: false",
        1,
    )
    result = check_baseline_documents("self-test:conditional audit", "nextjs", files)
    if not any("template production audit must not be conditional" in e for e in result):
        errors.append(f"self-test 'conditional audit' did not fail as expected: {result}")

    # Case 12: the verifier is equally blocking; it cannot be weakened by a
    # quoted truthy value or a step condition.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[".github/workflows/test.yml"] = files[".github/workflows/test.yml"].replace(
        "- run: npm run verify:baselines",
        "- run: npm run verify:baselines\n        continue-on-error: \"true\"\n        if: false",
        1,
    )
    result = check_baseline_documents("self-test:conditional verifier", "nextjs", files)
    if not any("baseline verification" in e for e in result):
        errors.append(f"self-test 'conditional verifier' did not fail as expected: {result}")

    # Case 13: job-level settings can neutralise every step together and must
    # be rejected just as firmly as a step-level bypass.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[".github/workflows/test.yml"] = files[".github/workflows/test.yml"].replace(
        "  build:\n", "  build:\n    continue-on-error: \"true\"\n", 1
    )
    result = check_baseline_documents("self-test:non-blocking build job", "nextjs", files)
    if not any("template build job must be blocking" in e for e in result):
        errors.append(f"self-test 'non-blocking build job' did not fail as expected: {result}")

    # Case 14: job-level conditions can skip every required gate.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[".github/workflows/test.yml"] = files[".github/workflows/test.yml"].replace(
        "  build:\n", "  build:\n    if: false\n", 1
    )
    result = check_baseline_documents("self-test:conditional build job", "nextjs", files)
    if not any("template build job must not be conditional" in e for e in result):
        errors.append(f"self-test 'conditional build job' did not fail as expected: {result}")

    # Case 15: the scheduled review must not quietly become a PR gate or lose
    # either API permission its Dependabot and release-pipeline checks need.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[bootstrap.NEXTJS_BASELINE_REVIEW_WORKFLOW] = files[
        bootstrap.NEXTJS_BASELINE_REVIEW_WORKFLOW
    ].replace("vulnerability-alerts: read", "security-events: read").replace(
        "actions: read", "actions: none"
    ).replace(
        "  workflow_dispatch:\n", "  workflow_dispatch:\n  pull_request:\n"
    )
    result = check_baseline_documents("self-test:invalid review workflow", "nextjs", files)
    if not any("schedule-and-dispatch only" in e for e in result) or not any(
        "vulnerability-alerts: read" in e for e in result
    ) or not any("actions: read" in e for e in result):
        errors.append(f"self-test 'invalid review workflow' did not fail as expected: {result}")

    # Case 16: scalar permissions are valid GitHub syntax, but not sufficient
    # for this workflow's explicit Dependabot permission contract.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[bootstrap.NEXTJS_BASELINE_REVIEW_WORKFLOW] = files[
        bootstrap.NEXTJS_BASELINE_REVIEW_WORKFLOW
    ].replace(
        "permissions:\n  actions: read\n  contents: read\n  vulnerability-alerts: read",
        "permissions: read-all",
    )
    result = check_baseline_documents("self-test:scalar review permissions", "nextjs", files)
    if not any("permissions must be a mapping" in e for e in result):
        errors.append(f"self-test 'scalar review permissions' did not fail as expected: {result}")

    # Case 17: Release Please controls its generated manifest's formatting, so
    # the template must not make a generated first-release update fail Prettier.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[".prettierignore"] = files[".prettierignore"].replace(
        ".release-please-manifest.json\n", "", 1
    )
    result = check_baseline_documents("self-test:manifest formatting", "nextjs", files)
    if not any("generated Release Please manifest" in e for e in result):
        errors.append(f"self-test 'manifest formatting' did not fail as expected: {result}")

    # Case 18: the ruled protection configuration must not drift back to
    # strict True — the failure mode the operator ruled against.
    payload = bootstrap.branch_protection_payload("nextjs")
    payload["required_status_checks"]["strict"] = True
    result = check_branch_protection_payload("self-test:strict drift", "nextjs", payload)
    if not any("strict: False" in e for e in result):
        errors.append(f"self-test 'strict drift' did not fail as expected: {result}")

    # Case 19: a context dropped from the payload must not pass silently.
    payload = bootstrap.branch_protection_payload("nextjs")
    payload["required_status_checks"]["contexts"] = ["validate-title"]
    result = check_branch_protection_payload("self-test:dropped context", "nextjs", payload)
    if not any("do not match" in e for e in result):
        errors.append(f"self-test 'dropped context' did not fail as expected: {result}")

    # Case 20: enforce_admins weakened to False must be caught.
    payload = bootstrap.branch_protection_payload("swift")
    payload["enforce_admins"] = False
    result = check_branch_protection_payload("self-test:admin bypass", "swift", payload)
    if not any("must enforce admins" in e for e in result):
        errors.append(f"self-test 'admin bypass' did not fail as expected: {result}")

    # Case 21: the runbook never being generated at all (as when the render
    # line is removed from generate_files) must produce a labelled missing-file
    # error, not a KeyError that aborts the run and leaves later configs
    # unchecked.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files.pop(BRANCH_PROTECTION_RUNBOOK, None)
    result = check_runbook("self-test:never-generated runbook", files)
    if not any("missing docs/branch-protection-runbook.md" in e for e in result):
        errors.append(f"self-test 'never-generated runbook' did not fail as expected: {result}")

    # Case 22: a runbook that loses an operational fact must fail validation.
    # The fixture reads the key defensively — a direct index here was what
    # turned a missing runbook into the run-aborting KeyError case 21 covers.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[BRANCH_PROTECTION_RUNBOOK] = files.get(BRANCH_PROTECTION_RUNBOOK, "").replace(
        "update-branch", "update branch"
    )
    result = check_runbook("self-test:gutted runbook", files)
    if not any("update-branch" in e for e in result):
        errors.append(f"self-test 'gutted runbook' did not fail as expected: {result}")

    # Case 23: the bootstrapper's own docs/ runbook must match the template
    # byte-for-byte. A single-character drift between the two means the
    # repository documents one operational runbook while shipping another, so
    # the check must flag it rather than letting it pass silently.
    result = check_runbook_copy_matches_template(
        "self-test:drifted repo runbook",
        repo_copy=b"# branch protection and release PRs\n\nalpha\n",
        template_copy=b"# branch protection and release PRs\n\nbeta\n",
    )
    if not any("docs/branch-protection-runbook.md differs from" in e for e in result):
        errors.append(f"self-test 'drifted repo runbook' did not fail as expected: {result}")

    # Case 24: a missing repo-side copy must produce a labelled missing-file
    # error, not an abort — the same defensive-read discipline as case 21.
    result = check_runbook_copy_matches_template(
        "self-test:missing repo runbook", repo_copy=None, template_copy=b"# ...\n"
    )
    if not any("missing docs/branch-protection-runbook.md" in e for e in result):
        errors.append(f"self-test 'missing repo runbook' did not fail as expected: {result}")

    # Case 25: the lint baseline must carry the review-date column and the
    # honest "Why this is accepted" header, not the old "unavoidable false
    # positive" wording that misdescribes accepted true positives.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files["docs/lint-baseline.md"] = files["docs/lint-baseline.md"].replace(
        "Why this is accepted", "Why the warning is an unavoidable false positive"
    ).replace("Review date", "Removed")
    result = check_baseline_documents("self-test:stale lint header", "nextjs", files)
    if not any("Why this is accepted" in e for e in result) or not any(
        "'Review date'" in e for e in result
    ):
        errors.append(f"self-test 'stale lint header' did not fail as expected: {result}")

    # Case 26: a generated verifier that drifts back to the old single-purpose
    # lint parser (no parseLintRows) must fail validation rather than silently
    # shipping a checker that cannot validate the new review-date column.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files["scripts/verify-baselines.mjs"] = files["scripts/verify-baselines.mjs"].replace(
        "parseLintRows", "parseTable"
    )
    result = check_baseline_documents("self-test:stale lint parser", "nextjs", files)
    if not any("scripts/verify-baselines.mjs is missing 'parseLintRows'" in e for e in result):
        errors.append(f"self-test 'stale lint parser' did not fail as expected: {result}")

    # Case 27: the regression that shipped. release-please-gated.yml passes
    # `full` to test.yml; a called workflow that doesn't declare it fails at
    # parse time, so the whole release pipeline never runs. This is the exact
    # shape of the Python bug — reproduced by deleting the declaration.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "python"))
    files[".github/workflows/test.yml"] = re.sub(
        r"    inputs:\n(?:.*\n)*?        default: true\n",
        "",
        files[".github/workflows/test.yml"],
        count=1,
    )
    result = check_reusable_workflow_inputs("self-test:undeclared input", files)
    if not any("does not declare it" in e for e in result):
        errors.append(f"self-test 'undeclared input' did not fail as expected: {result}")

    # Case 28: the mirror direction — a called workflow that starts requiring an
    # input its caller never supplies fails just as hard.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "python"))
    files[".github/workflows/test.yml"] = files[".github/workflows/test.yml"].replace(
        "        type: boolean\n        default: true\n",
        "        type: boolean\n        required: true\n",
        1,
    )
    files[".github/workflows/release-please.yml"] = re.sub(
        r"    with:\n      full: .*\n", "", files[".github/workflows/release-please.yml"], count=1
    )
    result = check_reusable_workflow_inputs("self-test:omitted required input", files)
    if not any("omits required input" in e for e in result):
        errors.append(f"self-test 'omitted required input' did not fail as expected: {result}")

    # Case 28b: a target that stops being callable at all. With no inputs
    # supplied, the declared/supplied comparison comes down to two empty dicts
    # and passes vacuously — so callability is asserted separately.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "python"))
    files[".github/workflows/test.yml"] = files[".github/workflows/test.yml"].replace(
        "on:\n  workflow_call:", "on:\n  push:", 1
    )
    files[".github/workflows/release-please.yml"] = re.sub(
        r"    with:\n      full: .*\n", "", files[".github/workflows/release-please.yml"], count=1
    )
    result = check_reusable_workflow_inputs("self-test:non-callable target", files)
    if not any("not callable" in e for e in result):
        errors.append(f"self-test 'non-callable target' did not fail as expected: {result}")

    # Case 29: a generated workflow that drops its permissions block falls
    # back to inheriting whatever its caller grants — which can change out
    # from under it later even if the caller happens to be read-only today.
    # Absence must fail regardless of the caller's current scope.
    for repo_type in ("nextjs", "python", "swift", "simple"):
        files = bootstrap.generate_files(
            next(cfg for _, cfg in configurations() if cfg["repo_type"] == repo_type)
        )
        target = ".github/workflows/test.yml" if repo_type != "simple" else ".github/workflows/pr-title-check.yml"
        files[target] = re.sub(r"\npermissions:\n(?:  \S+: \S+\n)+", "\n", files[target], count=1)
        result = check_workflow_permissions(f"self-test:unscoped token {repo_type}", files)
        if not any("declares no top-level permissions" in e for e in result):
            errors.append(
                f"self-test 'unscoped token {repo_type}' did not fail as expected: {result}"
            )

    # Case 29b: presence is not the property that matters. Broadening the test
    # suite's own scope to contents: write satisfies "declares a mapping" while
    # restoring the exact exposure #10 removed — the write-scoped token reaches
    # pip/pytest/xcodebuild again, this time by declaration rather than by
    # inheritance. Both the caller and the suite must be rejected.
    for repo_type in ("nextjs", "python", "swift"):
        files = bootstrap.generate_files(
            next(cfg for _, cfg in configurations() if cfg["repo_type"] == repo_type)
        )
        for path in (".github/workflows/ci.yml", ".github/workflows/test.yml"):
            broadened = dict(files)
            broadened[path] = files[path].replace(
                "permissions:\n  contents: read", "permissions:\n  contents: write", 1
            )
            result = check_workflow_permissions(f"self-test:broadened {repo_type} {path}", broadened)
            if not any("must grant exactly" in e for e in result):
                errors.append(
                    f"self-test 'broadened scope {repo_type} {path}' did not fail "
                    f"as expected: {result}"
                )

    # Case 29c: the exact-map guard covers workflows outside the ci/test pair
    # too — every generated workflow's scope is asserted, not just the two most
    # obviously security-sensitive ones.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs"))
    files[bootstrap.NEXTJS_BASELINE_REVIEW_WORKFLOW] = files[
        bootstrap.NEXTJS_BASELINE_REVIEW_WORKFLOW
    ].replace("contents: read", "contents: write", 1)
    result = check_workflow_permissions("self-test:write-scoped observer", files)
    if not any("must grant exactly" in e for e in result):
        errors.append(f"self-test 'write-scoped observer' did not fail as expected: {result}")

    # Case 29e: release-please.yml no longer needs GITHUB_TOKEN write — verified
    # empirically against a live release run (finding #11): PR creation, PR
    # merge, tag creation, and GitHub Release creation all succeeded under
    # {contents: read}, with no write-required GITHUB_TOKEN fallback needed.
    # Regressing the workflow-level grant back to write must fail exactly like
    # any other workflow drifting from its expected map.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "simple"))
    files[".github/workflows/release-please.yml"] = files[".github/workflows/release-please.yml"].replace(
        "permissions:\n  contents: read", "permissions:\n  contents: write\n  pull-requests: write", 1
    )
    result = check_workflow_permissions("self-test:release write regressed", files)
    if not any("must grant exactly" in e for e in result):
        errors.append(f"self-test 'release write regressed' did not fail as expected: {result}")

    # Case 29f: an extra scope alongside the correct one is still a drift from
    # the expected map, not a superset that happens to be fine — equality, not
    # containment, is what "exactly" means.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "python"))
    files[".github/workflows/release-please.yml"] = files[".github/workflows/release-please.yml"].replace(
        "permissions:\n  contents: read", "permissions:\n  contents: read\n  issues: write", 1
    )
    result = check_workflow_permissions("self-test:release extra scope", files)
    if not any("must grant exactly" in e for e in result):
        errors.append(f"self-test 'release extra scope' did not fail as expected: {result}")

    # Case 29g: a workflow path this check has never seen — well-formed
    # permissions and all — must still be rejected. An unmapped path is a new
    # template added without updating EXPECTED_WORKFLOW_PERMISSIONS, the same
    # "presence is not correctness" gap #10 exposed, one layer up.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "simple"))
    files[".github/workflows/mystery.yml"] = files[".github/workflows/pr-title-check.yml"]
    result = check_workflow_permissions("self-test:unrecognised workflow", files)
    if not any("is not a recognised generated workflow" in e for e in result):
        errors.append(f"self-test 'unrecognised workflow' did not fail as expected: {result}")

    # Case 29h: the release-please job must not acquire its own permissions
    # block. This is the exact shape a future "helpful" addition would take —
    # a job-level grant that looks locally reasonable while reopening the
    # standing write access the live-run test proved unnecessary.
    for repo_type in ("nextjs", "python", "swift", "simple"):
        files = bootstrap.generate_files(
            next(cfg for _, cfg in configurations() if cfg["repo_type"] == repo_type)
        )
        files[".github/workflows/release-please.yml"] = re.sub(
            r"(\n  release-please:\n)",
            r"\1    permissions:\n      contents: write\n",
            files[".github/workflows/release-please.yml"],
            count=1,
        )
        result = check_workflow_permissions(f"self-test:release job permissions {repo_type}", files)
        if not any("must not declare its own permissions block" in e for e in result):
            errors.append(
                f"self-test 'release job permissions {repo_type}' did not fail "
                f"as expected: {result}"
            )

    # Case 29h-null: a bare `permissions:` key with no value parses to None in
    # YAML — identical to an absent key under `.get()`. That makes it a
    # distinct way to sneak a "declaration" past the None-expected check if
    # the check only asks whether the value is not None rather than whether
    # the key exists at all. Must fail exactly like a real mapping would.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "simple"))
    files[".github/workflows/release-please.yml"] = re.sub(
        r"(\n  release-please:\n)",
        r"\1    permissions:\n",
        files[".github/workflows/release-please.yml"],
        count=1,
    )
    result = check_workflow_permissions("self-test:release job null permissions", files)
    if not any("must not declare its own permissions block" in e for e in result):
        errors.append(
            f"self-test 'release job null permissions' did not fail as expected: {result}"
        )

    # Case 30: `permissions: read-all` is valid GitHub syntax but not an
    # explicit per-scope grant, so it must not satisfy the check.
    files = bootstrap.generate_files(next(cfg for _, cfg in configurations() if cfg["repo_type"] == "swift"))
    files[".github/workflows/test.yml"] = files[".github/workflows/test.yml"].replace(
        "permissions:\n  contents: read", "permissions: read-all", 1
    )
    result = check_workflow_permissions("self-test:scalar permissions", files)
    if not any("must be a mapping" in e for e in result):
        errors.append(f"self-test 'scalar permissions' did not fail as expected: {result}")

    # Case 31: the other regression that shipped — generate_files() rebinding
    # its `name` local put "DEPENDENCY_NOTE" in every Swift package-name, and
    # check_syntax's parse-only JSON check could not see it.
    for _, cfg in configurations():
        files = bootstrap.generate_files(dict(cfg))
        files["release-please-config.json"] = files["release-please-config.json"].replace(
            f'"package-name": "{cfg["name"]}"', '"package-name": "DEPENDENCY_NOTE"'
        )
        result = check_release_please_config("self-test:wrong package name", cfg, files)
        if not any("package-name is 'DEPENDENCY_NOTE'" in e for e in result):
            errors.append(f"self-test 'wrong package name' did not fail as expected: {result}")
            break

    # Case 32: release-type is equally load-bearing and equally invisible to a
    # parse-only check — nextjs must stay 'node', everything else 'simple'.
    cfg = next(cfg for _, cfg in configurations() if cfg["repo_type"] == "nextjs")
    files = bootstrap.generate_files(dict(cfg))
    files["release-please-config.json"] = files["release-please-config.json"].replace(
        '"release-type": "node"', '"release-type": "simple"'
    )
    result = check_release_please_config("self-test:wrong release type", cfg, files)
    if not any("release-type is 'simple'" in e for e in result):
        errors.append(f"self-test 'wrong release type' did not fail as expected: {result}")

    # Case 33: a config that parses but has no '.' package entry must produce a
    # labelled error, not a crash — the same defensive discipline as case 21.
    cfg = next(cfg for _, cfg in configurations() if cfg["repo_type"] == "simple")
    result = check_release_please_config(
        "self-test:packageless config", cfg, {"release-please-config.json": "{}"}
    )
    if not any("no '.' package entry" in e for e in result):
        errors.append(f"self-test 'packageless config' did not fail as expected: {result}")

    # Case 34: a mutation test for the SHA-pinning gate itself — regressing one
    # pinned `uses:` back to a tag must fail, not pass silently. This is the
    # exact reintroduction bootstrap.py's sha_pinning_required: true depends on
    # the validator catching before it reaches GitHub, which rejects the run
    # outright once that repo setting is enabled.
    files = bootstrap.generate_files(
        next(cfg for _, cfg in configurations() if cfg["repo_type"] == "python")
    )
    files[".github/workflows/test.yml"] = re.sub(
        r"uses: actions/checkout@[0-9a-f]{40}(?: # v[\w.]+)?",
        "uses: actions/checkout@v7",
        files[".github/workflows/test.yml"],
        count=1,
    )
    result = check_sha_pinned_actions("self-test:tag reintroduced", files)
    if not any("not pinned to a full 40-character commit SHA" in e for e in result):
        errors.append(f"self-test 'tag reintroduced' did not fail as expected: {result}")

    # Case 35: a Swift README must retain the safe formatter invocation and
    # the configured local xcodebuild destination. Omitting the formatter's
    # final path makes swift-format wait for standard input, while omitting the
    # destination gives users a different test command than generated AGENTS.md.
    cfg = next(cfg for _, cfg in configurations() if cfg["repo_type"] == "swift")
    files = bootstrap.generate_files(dict(cfg))
    for name, old, new in (
        (
            "formatter path omitted",
            "xcrun swift-format lint --recursive --strict .",
            "xcrun swift-format lint --recursive --strict",
        ),
        (
            "destination omitted",
            f'-destination "{bootstrap._DESTINATION_EXAMPLES[cfg["destination"]]}"',
            "",
        ),
    ):
        mutated = dict(files)
        mutated[bootstrap.README] = files[bootstrap.README].replace(old, new, 1)
        result = check_readme(f"self-test:{name}", cfg, mutated)
        if not any("Swift README.md is missing" in e for e in result):
            errors.append(f"self-test '{name}' did not fail as expected: {result}")

    # Line continuations are presentation, not command semantics. Keep the
    # validator flexible enough for a one-line README command while retaining
    # the formatter, scheme, and destination checks above.
    reflowed = dict(files)
    reflowed[bootstrap.README] = (
        files[bootstrap.README]
        .replace("xcodebuild test \\\n  -scheme", "xcodebuild test -scheme", 1)
        .replace(" \\\n  -destination", " -destination", 1)
    )
    result = check_readme("self-test:reflowed Swift command", cfg, reflowed)
    if result:
        errors.append(f"self-test 'reflowed Swift command' unexpectedly failed: {result}")

    # generate_files() defaults an empty programmatic destination to iphone;
    # the README validator must use that same default rather than rejecting a
    # configuration the generator itself accepts.
    defaulted_cfg = dict(cfg, destination="")
    result = check_readme(
        "self-test:default Swift destination",
        defaulted_cfg,
        bootstrap.generate_files(defaulted_cfg),
    )
    if result:
        errors.append(f"self-test 'default Swift destination' unexpectedly failed: {result}")

    # Case 36: SampleApp is shell-safe, so its normal rendered output cannot
    # distinguish the raw display marker from the shell-quoted command marker.
    # A spaced scheme must keep quotes in xcodebuild while leaving prose clean.
    spaced_readme = bootstrap.generate_files(dict(cfg, scheme="Sample App"))[bootstrap.README]
    if "-scheme 'Sample App'" not in spaced_readme:
        errors.append("self-test 'spaced scheme' lost shell quoting in the command")
    if "| Test scheme | `Sample App` |" not in spaced_readme:
        errors.append("self-test 'spaced scheme' leaked shell quoting into prose")

    return errors


def main() -> int:
    all_errors = []
    all_errors += run_self_tests()
    all_errors += check_npm_script_assumptions()

    total = 0
    for label, cfg in configurations():
        total += 1
        files = bootstrap.generate_files(cfg)
        all_errors += check_syntax(label, files)
        all_errors += check_nextjs_provider_free(label, cfg["repo_type"], files)
        all_errors += check_markers(label, files)
        all_errors += check_agents_guidance(label, files)
        all_errors += check_workflow_job_consistency(label, cfg["repo_type"], files)
        all_errors += check_workflow_permissions(label, files)
        all_errors += check_sha_pinned_actions(label, files)
        all_errors += check_reusable_workflow_inputs(label, files)
        all_errors += check_release_please_config(label, cfg, files)
        all_errors += check_baseline_documents(label, cfg["repo_type"], files)
        all_errors += check_readme(label, cfg, files)
        all_errors += check_branch_protection_payload(label, cfg["repo_type"])
        all_errors += check_runbook(label, files)

    # The bootstrapper's own docs/ runbook must match the template it ships
    # into every generated repository. Both files live in this one repo, and
    # validate-templates is already a required check here, so a single
    # byte-equality assertion closes the drift class for the repo's own copy.
    all_errors += check_runbook_copy_matches_template(
        "bootstrapper self",
        _read_file_or_none(REPO_RUNBOOK_PATH),
        _read_file_or_none(TEMPLATE_RUNBOOK_PATH),
    )
    all_errors += check_sha_pinned_actions("bootstrapper own workflows", _own_workflow_files())

    if all_errors:
        print(f"FAILED — {len(all_errors)} error(s) across {total} configuration(s):\n")
        for err in all_errors:
            print(f"  {err}")
        return 1

    print(f"OK — {total} configuration(s) validated, no errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
