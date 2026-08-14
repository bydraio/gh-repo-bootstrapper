#!/usr/bin/env python3
"""
bootstrap.py — Create a standardised GitHub repository.

Supported types:
  nextjs   Full CI (lint / typecheck / tests / Playwright e2e) with optional
           PostgreSQL test service.
  python   Python CI (ruff / mypy / pytest) with gated Release Please.
  swift    Swift/Xcode CI (xcodebuild test) with gated Release Please.
  simple   Release Please only — no test workflows.

Requirements: Python 3.9+, gh CLI (authenticated), git
"""

import argparse
import getpass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import NoReturn

# ---------------------------------------------------------------------------
# Startup version check
# ---------------------------------------------------------------------------

if sys.version_info < (3, 9):
    sys.exit(f"error: Python 3.9+ required (got {sys.version})")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


TEMPLATES_DIR = Path(__file__).parent / "templates"

# bootstrap.py deliberately does not create or patch package.json: that file
# belongs to the selected application scaffold. These are the npm scripts the
# Next.js templates assume that scaffold provides. validate_templates.py keeps
# this owned assumption set consistent with the commands those templates show.
ASSUMED_NPM_SCRIPTS = {
    "dev",
    "lint",
    "lint:fix",
    "format",
    "format:check",
    "typecheck",
    "test",
    "audit:production",
    "verify:baselines",
    "review:baselines",
    "build",
    "test:e2e",
}

# These are policy documents for Next.js repositories. The bootstrapper does
# not generate package.json, so its npm-audit and ESLint guidance must not be
# emitted for Python, Swift, or simple repositories.
NEXTJS_BASELINE_DOCUMENTS = (
    "docs/lint-baseline.md",
    "docs/advisory-baseline.md",
)

NEXTJS_ENFORCED_AUDIT_SCRIPT = "scripts/audit-production.mjs"
NEXTJS_BASELINE_SCRIPTS = (
    "scripts/baseline-table.mjs",
    "scripts/verify-baselines.mjs",
    "scripts/verify-baselines.test.mjs",
    "scripts/review-baselines.mjs",
    "scripts/review-baselines.test.mjs",
)
NEXTJS_BASELINE_REVIEW_WORKFLOW = ".github/workflows/baseline-review.yml"
SCREENSHOT_REVIEW = "docs/screenshot-review.md"
README = "README.md"


def _die(msg: str) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def _run(cmd: list, **kwargs):
    subprocess.run(cmd, check=True, **kwargs)


def _run_with_retry(cmd: list, attempts: int = 3, delay: float = 3, **kwargs):
    """Like _run, but retries on failure. `gh repo create --clone` has this
    built in (GitHub's API can return a repo before it's clone-able yet);
    `gh repo create` + `gh repo clone` as two separate calls does not, so we
    replicate it here for the clone step."""
    for attempt in range(1, attempts + 1):
        try:
            _run(cmd, **kwargs)
            return
        except subprocess.CalledProcessError:
            if attempt == attempts:
                raise
            print(f"  clone failed (attempt {attempt}/{attempts}), retrying…")
            time.sleep(delay)


def _load(name: str) -> str:
    path = TEMPLATES_DIR / name
    if not path.exists():
        _die(f"template not found: {path}")
    return path.read_text()


def _compose(template: str, marker: str, fragment: str) -> str:
    line = f"# <<{marker}>>\n"
    if line not in template:
        _die(f"marker '# <<{marker}>>' not found in template")
    return template.replace(line, fragment)


def _extract_section(text: str, name: str) -> str:
    start = f"<!-- SECTION:{name} -->\n"
    end = f"<!-- /SECTION:{name} -->\n"
    if start not in text or end not in text:
        _die(f"section '{name}' not found in delta template")
    return text.split(start, 1)[1].split(end, 1)[0]


# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------


def check_dependencies():
    if not shutil.which("gh"):
        _die("gh CLI not found — install from https://cli.github.com/")
    if not shutil.which("git"):
        _die("git not found — install git and try again")
    result = subprocess.run(["gh", "auth", "status"], capture_output=True)
    if result.returncode != 0:
        _die("not logged in to GitHub CLI — run: gh auth login")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    p = argparse.ArgumentParser(
        prog="bootstrap.py",
        description="Create a standardised GitHub repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Types:
              nextjs   Full CI + optional PostgreSQL tests
              python   Python CI (ruff / mypy / pytest) + gated Release Please
              swift    Swift/Xcode CI (xcodebuild test) + gated Release Please
              simple   Release Please only (no tests)

            Examples:
              ./bootstrap.py
              ./bootstrap.py --name my-app --type nextjs --public
              ./bootstrap.py --name my-tool --type python --org my-org
              ./bootstrap.py --name my-app --type swift --scheme MyApp
              ./bootstrap.py --name my-app --type swift --scheme MyApp --xcodegen
              ./bootstrap.py --name my-app --type nextjs --postgres --dry-run
              ./bootstrap.py --name my-app --type nextjs --configure-only
        """),
    )
    p.add_argument("--name", help="Repository name, or a relative/absolute path ending in one "
                   "(default: created in the current directory)")
    p.add_argument("--type", choices=["nextjs", "simple", "python", "swift"],
                   dest="repo_type", help="Repository type")
    p.add_argument("--org", help="GitHub org or user (default: authenticated user)")
    vis = p.add_mutually_exclusive_group()
    vis.add_argument("--private", action="store_true",
                     help="Make repository private (default)")
    vis.add_argument("--public", action="store_true",
                     help="Make repository public")
    p.add_argument("--postgres", action="store_true",
                   help="Add PostgreSQL 16 service to test workflow (nextjs only)")
    p.add_argument("--scheme",
                   help="Xcode scheme name for xcodebuild test (swift only)")
    p.add_argument("--destination", choices=["iphone", "ipad", "macos"],
                   help="Target destination for xcodebuild test (swift only, default: iphone)")
    p.add_argument("--xcodegen", action="store_true",
                   help="Generate the Xcode project from project.yml in CI (swift only)")
    p.add_argument("--configure-only", action="store_true",
                   help="Apply GitHub configuration to an existing repo (skip file generation)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print files that would be created without doing anything")
    p.add_argument("--non-interactive", action="store_true",
                   help="Fail if required options are missing instead of prompting")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Interactive helpers
# ---------------------------------------------------------------------------


def prompt(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        return input(f"{question}{suffix}: ").strip() or default
    except EOFError:
        _die("unexpected end of input")


def prompt_validated(question: str, validator) -> str:
    while True:
        try:
            value = input(f"{question}: ").strip()
        except EOFError:
            _die("unexpected end of input")
        error = validator(value)
        if not error:
            return value
        print(f"  {error}")


def prompt_yn(question: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        try:
            raw = input(f"{question}{suffix}: ").strip().lower()
        except EOFError:
            _die("unexpected end of input")
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


def prompt_choice(question: str, choices: list) -> str:
    for i, c in enumerate(choices, 1):
        print(f"  {i}. {c}")
    while True:
        try:
            raw = input(f"{question} (1-{len(choices)}): ").strip()
        except EOFError:
            _die("unexpected end of input")
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            pass
        print(f"  Enter a number from 1 to {len(choices)}.")


def prompt_secret(question: str) -> str:
    if not sys.stdin.isatty():
        # No real terminal attached (piped/redirected input) — getpass
        # always tries /dev/tty first, which would ignore this input
        # entirely and block on a real terminal, or silently misread
        # unrelated input via its own stdin fallback. Read a normal,
        # visible line instead, matching prompt()'s behavior.
        try:
            return input(f"{question}: ").strip()
        except EOFError:
            _die("unexpected end of input")
    try:
        value = getpass.getpass(f"{question}: ")
    except EOFError:
        _die("unexpected end of input")
    return value.strip()


def prompt_optional(label: str, secret: bool = False) -> str:
    hint = "press Enter to skip and configure later"
    if secret:
        hint = f"hidden, {hint}"
    value = (prompt_secret if secret else prompt)(f"  {label} ({hint})")
    if not value:
        print("    (skipped)")
    return value


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_name(name: str) -> str:
    """Return error string or empty string if valid."""
    if not name:
        return "Repository name is required."
    if not re.match(r"^[a-z0-9][a-z0-9\-]*$", name):
        return "Must be lowercase letters, digits, and hyphens only (must start with letter or digit)."
    if len(name) > 100:
        return "Must be 100 characters or fewer."
    return ""


def split_name_and_path(raw: str) -> tuple:
    """Split a bare name or relative/absolute path into (repo_name, local_dir)."""
    local_dir = Path(raw).expanduser()
    return local_dir.name, local_dir


def validate_name_or_path(raw: str) -> str:
    """Return error string or empty string if valid. `raw` may be a bare
    repo name or a relative/absolute path ending in the repo name."""
    name, _ = split_name_and_path(raw) if raw else ("", None)
    return validate_name(name)


# ---------------------------------------------------------------------------
# Config gathering
# ---------------------------------------------------------------------------


def _gh_current_user() -> str:
    try:
        r = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def _gh_repo_is_private(full: str) -> bool:
    try:
        r = subprocess.run(
            ["gh", "api", f"repos/{full}", "--jq", ".private"],
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip() == "true"
    except subprocess.CalledProcessError:
        return True  # safe default if the lookup itself fails


def _gh_orgs() -> list:
    try:
        r = subprocess.run(["gh", "org", "list"], capture_output=True, text=True, check=True)
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        return []


def gather_config(args) -> dict:
    ni = args.non_interactive
    dry = args.dry_run
    configure_only = args.configure_only

    # --- name ---
    raw_name = args.name
    if not raw_name:
        if ni:
            _die("--name is required in --non-interactive mode")
        print(
            "\nRepository name — created as a new directory in the current "
            "directory by default.\nTo create it elsewhere, enter a relative "
            "or absolute path instead (e.g. ../my-app or /Users/you/code/my-app)."
        )
        raw_name = prompt_validated("Repository name", validate_name_or_path)
    else:
        err = validate_name_or_path(raw_name)
        if err:
            _die(err)
    name, repo_dir = split_name_and_path(raw_name)

    # --- type ---
    repo_type = args.repo_type
    if not repo_type:
        if ni:
            _die("--type is required in --non-interactive mode")
        print("\nRepository type:")
        repo_type = prompt_choice("Select type", ["nextjs", "python", "swift", "simple"])

    # --- owner ---
    owner = args.org
    if not owner:
        user = "" if dry else _gh_current_user()
        if ni:
            if not user:
                if not dry:
                    _die("could not determine GitHub user; pass --org")
                user = "example-org"  # dry-run touches nothing downstream
            owner = user
        else:
            owners = ([user] if user else []) + ([] if dry else _gh_orgs())
            if len(owners) == 1:
                owner = owners[0]
                print(f"\nGitHub owner: {owner}")
            elif owners:
                print("\nGitHub owner:")
                owner = prompt_choice("Select owner", owners)
            else:
                owner = prompt("GitHub org or user")
                if not owner:
                    _die("GitHub owner is required")

    # --- visibility (looked up for --configure-only; repo already exists) ---
    if configure_only:
        if args.public or args.private:
            print("warning: --public/--private are ignored with --configure-only")
        private = True if dry else _gh_repo_is_private(f"{owner}/{name}")
    elif args.public:
        private = False
    elif args.private:
        private = True
    elif ni:
        private = True  # default
    else:
        private = not prompt_yn("\nMake repository public?", default=False)

    # --- type-specific options ---
    postgres = False
    scheme = ""
    destination = ""
    xcodegen = False

    if repo_type == "nextjs":
        postgres = args.postgres
        if args.scheme:
            print("warning: --scheme is only used with --type swift; ignoring")
        if args.destination:
            print("warning: --destination is only used with --type swift; ignoring")
        if args.xcodegen:
            print("warning: --xcodegen is only used with --type swift; ignoring")
        if not ni and not args.postgres:
            postgres = prompt_yn("Include PostgreSQL service in tests?", default=False)

    elif repo_type == "swift":
        if args.postgres:
            print("warning: --postgres is only used with --type nextjs; ignoring")
        scheme = args.scheme or ""
        if not scheme:
            if ni:
                _die("--scheme is required for --type swift in --non-interactive mode")
            scheme = prompt("\nXcode scheme name")
            if not scheme:
                _die("Xcode scheme name is required for --type swift")
        destination = args.destination or ""
        if not destination:
            if ni:
                destination = "iphone"
            else:
                print("\nTarget destination:")
                destination = prompt_choice("Select destination", ["iphone", "ipad", "macos"])
        xcodegen = args.xcodegen
        if not ni and not args.xcodegen:
            xcodegen = prompt_yn("Generate the Xcode project from project.yml?", default=False)

    else:  # python, simple
        if args.postgres:
            print("warning: --postgres is only used with --type nextjs; ignoring")
        if args.scheme:
            print("warning: --scheme is only used with --type swift; ignoring")
        if args.destination:
            print("warning: --destination is only used with --type swift; ignoring")
        if args.xcodegen:
            print("warning: --xcodegen is only used with --type swift; ignoring")

    # --- GitHub variables and secrets ---
    # Non-interactive: read from environment variables.
    # Interactive: prompt the user (skipped entirely in dry-run).
    release_please_client_id = ""
    release_please_app_key = ""

    if ni:
        release_please_client_id = os.environ.get("RELEASE_PLEASE_CLIENT_ID", "")
        release_please_app_key = os.environ.get("RELEASE_PLEASE_APP_KEY", "")
    elif not dry:
        print("\nGitHub App — Release Please:")
        release_please_client_id = prompt_optional("RELEASE_PLEASE_CLIENT_ID")
        release_please_app_key = prompt_optional("RELEASE_PLEASE_APP_KEY", secret=True)


    return {
        "name": name,
        "repo_dir": repo_dir,
        "repo_type": repo_type,
        "owner": owner,
        "private": private,
        "postgres": postgres,
        "scheme": scheme,
        "destination": destination,
        "xcodegen": xcodegen,
        "configure_only": configure_only,
        "release_please_client_id": release_please_client_id,
        "release_please_app_key": release_please_app_key,
        "dry_run": dry,
    }


# ---------------------------------------------------------------------------
# File templates — loaded from templates/ at runtime
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------


def _release_please_config(name: str, repo_type: str) -> str:
    schema = "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json"
    if repo_type == "nextjs":
        cfg = {
            "$schema": schema,
            "include-component-in-tag": False,
            "packages": {".": {"release-type": "node", "package-name": name}},
        }
    else:  # simple, python, swift — all use release-type: simple
        cfg = {
            "$schema": schema,
            "include-component-in-tag": False,
            "packages": {".": {"release-type": "simple", "package-name": name}},
        }
    return json.dumps(cfg, indent=2) + "\n"


def required_status_checks(repo_type: str) -> list:
    """Required branch-protection status check contexts for a GENERATED repo.

    These describe the repositories this script generates — never an existing
    repository that merely shares a type. gh-repo-bootstrapper itself emits
    "validate-templates" from its own validate.yml and has no "test / test"
    job; existing product repos may run extra lanes the templates do not
    (a production e2e pass, a Lighthouse budget, and so on). Protecting an
    existing repo requires contexts observed from its own PR check rollups,
    not this function.

    Check names follow GitHub's "{caller job} / {reusable job}" convention
    for workflows that call a reusable test.yml via ci.yml — the caller job
    in ci.yml is always named "test"; the job names it maps to inside
    test.yml vary by repo type. Kept alongside generate_files() so the two
    stay consistent (validated two-way by validate_templates.py).
    """
    if repo_type == "nextjs":
        return ["validate-title", "test / build", "test / e2e"]
    elif repo_type in ("python", "swift"):
        return ["validate-title", "test / test"]
    else:
        return ["validate-title"]


def branch_protection_payload(repo_type: str) -> dict:
    """Branch-protection API payload for main on a generated repository.

    The policy values are the operator's item-10 rulings (2026-07-27), not
    defaults: strict False because "branch must be up to date" strands every
    open PR — release PRs worst — on every advance of main; enforce_admins
    True so the gates bind the account that does the merging; a required PR
    with zero required approvals so the no-direct-pushes convention is
    enforced without demanding self-review theatre. Contexts come from
    required_status_checks() and are asserted against the generated workflows
    two-way by validate_templates.py, which also pins every value below.
    """
    return {
        "required_status_checks": {
            "strict": False,  # ruled: up-to-date requirement strands release PRs
            "contexts": required_status_checks(repo_type),
        },
        "enforce_admins": True,  # ruled: gates apply to admins too
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": False,
            "require_code_owner_reviews": False,
            "required_approving_review_count": 0,  # PR required; no approval count
        },
        "restrictions": None,  # no push restrictions beyond the above
    }


_DESTINATION_EXAMPLES = {
    "iphone": "platform=iOS Simulator,name=iPhone 16",
    "ipad": "platform=iOS Simulator,name=iPad (10th generation)",
    "macos": "platform=macOS,arch=arm64",
}


def generate_files(cfg: dict) -> dict:
    name = cfg["name"]
    repo_type = cfg["repo_type"]
    postgres = cfg["postgres"]
    destination = cfg.get("destination") or "iphone"
    xcodegen = bool(cfg.get("xcodegen"))

    files = {}

    files[".github/workflows/pr-title-check.yml"] = _load("pr-title-check.yml")
    readme = _load(f"README-{repo_type}.md").replace("__REPOSITORY_NAME__", name)
    if repo_type == "python":
        readme = readme.replace("__PYTHON_VERSION__", _load(".python-version").strip())
    elif repo_type == "swift":
        readme = (
            readme.replace("__SCHEME__", cfg["scheme"])
            .replace("__SCHEME_SHELL__", shlex.quote(cfg["scheme"]))
            .replace("__DESTINATION_EXAMPLE__", _DESTINATION_EXAMPLES[destination])
        )
    files[README] = readme

    if repo_type == "nextjs":
        files[".github/workflows/release-please.yml"] = _load("release-please-nextjs.yml")
        files[".github/workflows/ci.yml"] = _load("ci.yml")
        pg = _load("test-postgres-block.yml") if postgres else ""
        files[".github/workflows/test.yml"] = _compose(
            _load("test.yml"), "POSTGRES_BLOCK", pg
        )
        files[NEXTJS_BASELINE_REVIEW_WORKFLOW] = _load("baseline-review.yml")
        files[".github/dependabot.yml"] = _load("dependabot-full.yml")
        files[".nvmrc"] = _load(".nvmrc")
        files[".npmrc"] = _load(".npmrc")
        files[".prettierrc.json"] = _load(".prettierrc.json")
        files[".prettierignore"] = _load(".prettierignore")
        files["docs/lint-baseline.md"] = _load("docs-lint-baseline.md")
        files["docs/advisory-baseline.md"] = _load("docs-advisory-baseline.md")
        files[NEXTJS_ENFORCED_AUDIT_SCRIPT] = _load("audit-production.mjs")
        for path in NEXTJS_BASELINE_SCRIPTS:
            files[path] = _load(path.removeprefix("scripts/"))
        screenshot_guidance = _load("docs-screenshot-review-nextjs.md")
    elif repo_type == "python":
        files[".github/workflows/release-please.yml"] = _load("release-please-gated.yml")
        files[".github/workflows/ci.yml"] = _load("ci.yml")
        files[".github/workflows/test.yml"] = _load("test-python.yml")
        files[".github/dependabot.yml"] = _load("dependabot-python.yml")
        files[".python-version"] = _load(".python-version")
        screenshot_guidance = ""

    elif repo_type == "swift":
        files[".github/workflows/release-please.yml"] = _load("release-please-gated.yml")
        files[".github/workflows/ci.yml"] = _load("ci.yml")
        swift_test_template = "test-swift-xcodegen.yml" if xcodegen else "test-swift.yml"
        files[".github/workflows/test.yml"] = (
            _load(swift_test_template)
            .replace("__SCHEME_JSON__", json.dumps(cfg["scheme"]))
            .replace("__DESTINATION_KIND__", destination)
        )
        # A new Swift repo has no usable SPM manifest yet. Generating a Swift
        # Dependabot entry at this point creates a permanently failing updater.
        files[".github/dependabot.yml"] = _load("dependabot-actions-only.yml")
        files[".swift-format"] = _load(".swift-format")
        screenshot_guidance = _load("docs-screenshot-review-swift.md")

    else:  # simple
        files[".github/workflows/release-please.yml"] = _load("release-please-simple.yml")
        files[".github/dependabot.yml"] = _load("dependabot-actions-only.yml")
        screenshot_guidance = ""

    if repo_type in ("nextjs", "swift"):
        files[SCREENSHOT_REVIEW] = _compose(
            _load("docs-screenshot-review-common.md"),
            "PLATFORM_GUIDANCE",
            screenshot_guidance,
        )

    # Every generated repo is born with the runbook for the protection applied
    # below — all types get release-please, pr-title-check and required checks.
    files["docs/branch-protection-runbook.md"] = _load("docs-branch-protection-runbook.md")

    preamble = ""
    baseline_guidance = ""
    tooling = ""
    if repo_type == "nextjs":
        preamble = _load("AGENTS-nextjs-block.md")
        baseline_guidance = _load("AGENTS-nextjs-baseline.md")
        tooling = _load("AGENTS-nextjs-tooling.md")
    elif repo_type == "python":
        tooling = _load("AGENTS-python-tooling.md")
    elif repo_type == "swift":
        swift_tooling = _load("AGENTS-swift-tooling.md")
        delta = _load(
            "AGENTS-swift-xcodegen-delta.md" if xcodegen else "AGENTS-swift-tooling-default.md"
        )
        # Not `name`: that local holds the repository name and is still needed
        # below for release-please-config.json, which silently shipped
        # "package-name": "DEPENDENCY_NOTE" on every Swift repo while this loop
        # rebound it. validate_templates.check_release_please_config asserts the
        # rendered value now.
        for section in ("PROJECT_NOTE", "GENERATE_STEP", "DEPENDENCY_NOTE"):
            swift_tooling = _compose(
                swift_tooling, f"XCODEGEN_{section}", _extract_section(delta, section)
            )
        tooling = (
            swift_tooling
            .replace("__SCHEME__", shlex.quote(cfg["scheme"]))
            .replace("__DESTINATION_EXAMPLE__", _DESTINATION_EXAMPLES[destination])
            .replace("__DESTINATION_KIND__", destination)
        )
    files["CLAUDE.md"] = _load("CLAUDE.md")
    agents = _load("AGENTS.md")
    agents = _compose(agents, "TYPE_PREAMBLE", preamble)
    agents = _compose(agents, "BASELINE_PROCESS", baseline_guidance)
    agents = _compose(agents, "TYPE_TOOLING", tooling)
    agents = _compose(
        agents,
        "SCREENSHOT_GUIDANCE",
        _load(f"AGENTS-{repo_type}-screenshot-link.md") if repo_type in ("nextjs", "swift") else "",
    )
    files["AGENTS.md"] = agents
    files[".gitignore"] = _load(".gitignore")
    if repo_type == "swift" and xcodegen:
        files[".gitignore"] += "\n# XcodeGen output (project.yml is the source of truth)\n*.xcodeproj/\n"
    files["release-please-config.json"] = _release_please_config(name, repo_type)
    files[".release-please-manifest.json"] = json.dumps({".": "0.1.0"}, indent=2) + "\n"

    return files


# ---------------------------------------------------------------------------
# Dry-run output
# ---------------------------------------------------------------------------


def print_dry_run(cfg: dict, files: dict):
    sep = "─" * 60
    vis = "private" if cfg["private"] else "public"
    print(f"\n{'=' * 60}")
    print(f"  DRY RUN — {cfg['owner']}/{cfg['name']} ({cfg['repo_type']}, {vis})")
    print(f"  Local path: {cfg['repo_dir']}/")
    if cfg["repo_type"] == "nextjs":
        print(f"  Postgres: {cfg['postgres']}")
    elif cfg["repo_type"] == "swift":
        print(
            f"  Scheme: {cfg.get('scheme', '')}  |  "
            f"Destination: {cfg.get('destination', 'iphone')}  |  "
            f"XcodeGen: {cfg.get('xcodegen', False)}"
        )
    print(f"{'=' * 60}\n")

    for path in sorted(files):
        print(f"{sep}\n  {path}\n{sep}")
        for line in files[path].splitlines():
            print(f"  {line}")
        print()

    print(f"Total files: {len(files)}\n")

    print("GitHub variables to configure:")
    print("  RELEASE_PLEASE_CLIENT_ID")

    print("\nGitHub secrets to configure:")
    print("  RELEASE_PLEASE_APP_KEY")


# ---------------------------------------------------------------------------
# GitHub operations
# ---------------------------------------------------------------------------


def create_and_push(cfg: dict, files: dict):
    name = cfg["name"]
    owner = cfg["owner"]
    repo_dir = cfg["repo_dir"]
    full = f"{owner}/{name}"
    vis = "--private" if cfg["private"] else "--public"

    if repo_dir.exists() and any(repo_dir.iterdir()):
        _die(f"target directory '{repo_dir}' already exists and is not empty")

    print(f"\nCreating {full} in {repo_dir}/…")
    try:
        _run(["gh", "repo", "create", full, vis])
    except subprocess.CalledProcessError:
        _die(f"failed to create '{full}' — check it doesn't already exist")
    # Record creation immediately so failures in local clone, file generation,
    # commit, or push report the correct remote cleanup/recovery state to the
    # caller.
    cfg["repo_created"] = True

    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_with_retry(["gh", "repo", "clone", full, str(repo_dir)])
    except subprocess.CalledProcessError:
        print("The repository was created on GitHub. Clean up with:", file=sys.stderr)
        print(f"  gh repo delete {full}", file=sys.stderr)
        _die(f"failed to clone into '{repo_dir}'")

    print(f"Writing {len(files)} files to {repo_dir}/…")
    for rel, content in files.items():
        dest = repo_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)

    print("Committing and pushing…")
    _run(["git", "-C", str(repo_dir), "add", "."])
    _run(["git", "-C", str(repo_dir), "commit", "-m", "chore: initial repo setup"])
    _run(["git", "-C", str(repo_dir), "push", "--set-upstream", "origin", "HEAD"])
    cfg["files_pushed"] = True


def configure_repo(cfg: dict):
    name = cfg["name"]
    owner = cfg["owner"]
    repo = f"{owner}/{name}"

    def set_var(key: str, value: str):
        if value:
            print(f"  var    {key}")
            # Value passed via stdin (not --body) to keep it out of the process
            # argument list and away from ps/audit logs.
            subprocess.run(
                ["gh", "variable", "set", key, "--repo", repo],
                input=value.encode(),
                check=True,
            )

    def set_secret(key: str, value: str):
        if value:
            print(f"  secret {key}")
            subprocess.run(
                ["gh", "secret", "set", key, "--repo", repo],
                input=value.encode(),
                check=True,
            )

    def api(method: str, endpoint: str, payload: dict, *, stderr=None):
        subprocess.run(
            ["gh", "api", endpoint, "--method", method, "--input", "-"],
            input=json.dumps(payload).encode(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        )

    print("\nConfiguring repository…")

    # --- variables and secrets ---
    set_var("RELEASE_PLEASE_CLIENT_ID", cfg.get("release_please_client_id", ""))
    set_secret("RELEASE_PLEASE_APP_KEY", cfg.get("release_please_app_key", ""))

    # --- merge strategy, PR branch updates, Projects ---
    # Squash-merge only: merge commits and rebase disabled so every squash
    # commit title = PR title = Conventional Commit subject (Release Please
    # parses this to determine version bumps and changelog entries).
    print("  merge strategy")
    api("PATCH", f"repos/{repo}", {
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": False,
        "delete_branch_on_merge": True,
        "squash_merge_commit_title": "PR_TITLE",
        "squash_merge_commit_message": "PR_BODY",
        "allow_update_branch": True,
        "has_projects": True,
    })

    # --- actions permissions ---
    # Only GitHub-owned and Marketplace-verified actions, plus an explicit
    # allowlist for third-party actions this repo's own workflows depend on
    # (amannn/action-semantic-pull-request, used by pr-title-check.yml;
    # sha_pinning_required rejects any workflow run that references an
    # action by tag or branch rather than a full commit SHA;
    # validate_templates.py's check_sha_pinned_actions() enforces the same
    # rule on generated workflows before they ever reach GitHub.
    print("  actions permissions")
    api("PUT", f"repos/{repo}/actions/permissions", {
        "enabled": True,
        "allowed_actions": "selected",
        "sha_pinning_required": True,
    })
    api("PUT", f"repos/{repo}/actions/permissions/selected-actions", {
        "github_owned_allowed": True,
        "verified_allowed": True,
        "patterns_allowed": [
            "amannn/action-semantic-pull-request@*",
        ],
    })
    api("PUT", f"repos/{repo}/actions/permissions/workflow", {
        "default_workflow_permissions": "read",
        # Generated Release Please workflows use a dedicated GitHub App token,
        # and no generated workflow approves pull requests. Keep the default
        # GITHUB_TOKEN unable to approve reviews.
        "can_approve_pull_request_reviews": False,
    })
    # Fork PR workflow controls only exist as a distinct API for private
    # repos; public repos gate fork PRs via a separate approval-policy
    # endpoint instead, which isn't part of what was asked for here.
    if cfg["private"]:
        api("PUT", f"repos/{repo}/actions/permissions/fork-pr-workflows-private-repos", {
            "run_workflows_from_fork_pull_requests": False,
            "send_write_tokens_to_workflows": False,
            "send_secrets_and_variables": False,
            "require_approval_for_fork_pr_workflows": False,
        })

    # --- branch protection on main ---
    # Required status check names are derived from the job names in the
    # workflow files this script just generated, so they are always correct.
    # The GitHub API accepts these before the checks have run; they show as
    # "Expected — Waiting" on PRs and enforce once the first run completes.
    # The policy shape is the operator's item-10 ruling; see
    # branch_protection_payload() and docs/branch-protection-runbook.md.
    print("  branch protection (main)")

    try:
        api("PUT", f"repos/{repo}/branches/main/protection",
            branch_protection_payload(cfg["repo_type"]), stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        cfg["branch_protection_failed"] = True
        stderr_text = (exc.stderr or b"").decode(errors="replace").strip()
        if "upgrade to github pro" in stderr_text.lower():
            cfg["branch_protection_plan_limited"] = True
            print("  warning: branch protection requires GitHub Pro for private repos; skipping.")
        else:
            print("  warning: branch protection could not be set automatically.")
            if stderr_text:
                print(f"    {stderr_text}")


def print_success(cfg: dict):
    name = cfg["name"]
    owner = cfg["owner"]
    print(f"\n{'=' * 60}")
    print(f"  https://github.com/{owner}/{name}")
    print(f"{'=' * 60}")

    missing = []
    if not cfg.get("release_please_client_id"):
        missing.append("RELEASE_PLEASE_CLIENT_ID (variable)")
    if not cfg.get("release_please_app_key"):
        missing.append("RELEASE_PLEASE_APP_KEY (secret)")
    if cfg.get("branch_protection_failed"):
        if cfg.get("branch_protection_plan_limited"):
            missing.append("branch protection on main (requires GitHub Pro for private repos)")
        else:
            missing.append("branch protection on main (failed — see warning above for details)")

    if missing:
        print("\n  Still needs manual setup:")
        for item in missing:
            print(f"    {item}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = parse_args()
    if not args.dry_run:
        check_dependencies()
    cfg = gather_config(args)

    # --- configure-only: apply GitHub config to an existing repo ---
    if cfg["configure_only"]:
        if cfg["dry_run"]:
            _die("--configure-only cannot be combined with --dry-run")
        full = f"{cfg['owner']}/{cfg['name']}"
        if subprocess.run(["gh", "repo", "view", full], capture_output=True).returncode != 0:
            _die(f"repository '{full}' not found — verify the name and org")
        print(f"\nAbout to configure: {full} ({cfg['repo_type']})")
        print("  Enforces: squash-merge only, delete branch on merge, required status checks on main")
        print("  Note: file generation is skipped — commit CLAUDE.md and AGENTS.md separately if needed")
        if not args.non_interactive:
            if not prompt_yn("\nProceed?", default=True):
                print("Aborted.")
                return
        try:
            configure_repo(cfg)
            print_success(cfg)
        except subprocess.CalledProcessError as exc:
            print(f"\nerror: command failed: {exc.cmd}", file=sys.stderr)
            sys.exit(1)
        return

    # --- normal flow: create repo, generate files, configure ---
    files = generate_files(cfg)

    if cfg["dry_run"]:
        print_dry_run(cfg, files)
        return

    vis = "private" if cfg["private"] else "public"
    print(f"\nAbout to create: {cfg['owner']}/{cfg['name']} ({cfg['repo_type']}, {vis})")
    print(f"  Local path: {cfg['repo_dir']}/")
    if cfg["repo_type"] == "nextjs":
        extras = []
        if cfg["postgres"]:
            extras.append("Postgres tests")
        if extras:
            print(f"  Extras: {', '.join(extras)}")
    print(f"  Files:  {len(files)}")

    if not args.non_interactive:
        if not prompt_yn("\nProceed?", default=True):
            print("Aborted.")
            return

    full = f"{cfg['owner']}/{cfg['name']}"
    cfg["repo_created"] = False
    cfg["files_pushed"] = False
    try:
        create_and_push(cfg, files)
        configure_repo(cfg)
        print_success(cfg)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = (
            f"command failed: {exc.cmd}"
            if isinstance(exc, subprocess.CalledProcessError)
            else str(exc)
        )
        print(f"\nerror: {detail}", file=sys.stderr)
        if cfg["files_pushed"]:
            # Configuration failed after a successful push. Don't delete the repo.
            print("Files were pushed successfully. Fix configuration manually:", file=sys.stderr)
            print(f"  gh repo edit {full}  # merge strategy", file=sys.stderr)
            print(f"  gh api repos/{full}/branches/main/protection --method PUT ...  # branch protection", file=sys.stderr)
        elif cfg["repo_created"]:
            print("The GitHub repository was created, but local setup or push failed.", file=sys.stderr)
            print("Inspect the cloned directory and retry, or clean up with:", file=sys.stderr)
            print(f"  gh repo delete {full}", file=sys.stderr)
        else:
            print("If the repository was created on GitHub, clean up with:", file=sys.stderr)
            print(f"  gh repo delete {full}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
