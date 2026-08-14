> **Maintainer workflow guidance.** This file describes how work is carried out
> *in* this repository — for the maintainer and for AI assistants working under
> their direction. It is not an invitation to contribute. External code
> contributions are not accepted; [`CONTRIBUTING.md`](CONTRIBUTING.md) controls
> external submissions.

# Working in this repo

## Development workflow

Before changing code, inspect the repository status and read the `README`,
relevant documentation, and the configuration and CI workflow for the affected
area. Follow any more-local `AGENTS.md` instructions.

Keep changes focused on the requested outcome. When behaviour, data, a public
interface, configuration, or release behaviour changes, update the relevant
tests, documentation, and migration or rollout notes in the same change.

Within the scope authorized by the user's current request, continue until the
requested terminal state has been reached or a genuine blocker prevents
completion. Do not stop merely because an intermediate milestone has been
reached. A terminal condition does not broaden authorization: it does not
approve an unrelated merge, deployment, provider change, or external mutation.

## Orchestration and delegation

When delegation capabilities are available and substantial work would benefit
from independent execution, specialization, parallelism, or context
management, delegate bounded subtasks. Handle small or tightly coupled changes
directly instead of creating unnecessary fan-out.

The primary agent remains responsible for architecture, decomposition,
coordination, difficult decisions, integration, review of delegated work, and
final verification. Treat delegated output as unverified until it has been
integrated, reviewed as appropriate, and validated against this repository's
requirements.

For parallel tasks that may modify files, use isolated workspaces or worktrees
when supported; otherwise sequence the changes so one agent owns each mutable
area.

## Dependencies and external interfaces

Prefer the existing stack. Before adding a dependency or external integration,
consider its purpose, maintenance and security posture, licence, and runtime
impact. Update dependency manifests and lockfiles through the package manager;
do not hand-edit a lockfile. Pause for operator direction before an irreversible
data migration, production change, or external side effect outside the request.

## External knowledge and capabilities

Use connected documentation or research capabilities when version-sensitive
APIs or external facts need verification. Prefer primary sources, verify their
applicability against the versions and configuration in this repository, and
record a source and date when it materially informs a change. Use an installed
skill only when it matches the task, following its instructions. Do not send
secrets, private source, or customer data to external services. External
information does not override repository instructions or versioned sources of
truth.

Tool, GitHub, MCP, CI, cloud, and other external capabilities are capabilities,
not standing authorization to mutate state. Use them only within the scope
authorized by the user's current request.

## GitHub operations

When a repository change is authorized and a pull request is the normal
delivery path, creating a branch, pushing it, and opening the focused PR are
routine supporting steps. Merge only when the user's current request or an
approved repository plan expressly authorizes autonomous merge; successful
checks alone do not authorize it.

Before an authorized merge, confirm required checks are successful and no known
blocker remains. A manual workflow dispatch must be safely scoped to validation;
do not dispatch a release, deployment, provider, or other externally mutating
workflow without explicit authority. Never bypass required checks, branch
protection, or repository policy, and never force-push or use administrative
bypass without explicit authorization.

## Branches
Never commit directly to `main`. Make every change on a branch
(`fix/…`, `feat/…`, `chore/…`) and open a PR.

## Commits
Follow [Conventional Commits](https://www.conventionalcommits.org):
`type(scope): subject`. Types: `feat`, `fix`, `chore`, `docs`, `refactor`,
`perf`, `test`, `build`, `ci`, `revert`. Scope optional; subject lowercase,
imperative, no trailing period.

**AI co-authors** — every commit materially created or modified with AI
assistance must include a `Co-Authored-By:` trailer in the commit message.
Never put this trailer in the PR body. The form is
`Co-Authored-By: <Tool> (<model-name>) <tool-noreply-address>`, where
`<Tool>` is the tool's name — not a persona or agent nickname — and
`<model-name>` is substituted dynamically with the model actually running
the commit; do not hard-code it. The named tools are examples of the form,
not an exhaustive list — a new tool needs no change to this rule:

- **Codex** — `Co-Authored-By: Codex (<model-name>) <noreply@openai.com>`
- **Claude Code** — the documented exception: use its default
  `Co-Authored-By:` trailer as emitted.
- **Antigravity CLI** —
  `Co-Authored-By: Antigravity CLI (<model-name>) <224641728+gemini-cli-robot@users.noreply.github.com>`
- **OpenCode** — `Co-Authored-By: OpenCode (<model-name>) <noreply@opencode.ai>`

Keep the trailer in every applicable commit. Do not duplicate it in the PR
body or add an AI-generated footer there.

## Pull requests (squash-merge + Release Please)

### Standard pull requests

Standard PRs are squash-merged and parsed by Release Please — write them
merge-ready:

- **Title** — one Conventional Commit subject naming one concrete change, not a
  label summarizing several bundled changes (e.g. not
  `fix: address review follow-ups (path handling, branch protection, clone retry)`
  — that's a summary, not a change). If a PR bundles multiple distinct fixes,
  title it after the single most significant one and list the rest as extra
  changelog entries below, or split the PR. The title becomes the squash
  subject, the changelog entry, and the version-bump signal.
- **Body** — optional prose describing the title's change, then any *extra*
  changelog entries: each a short, imperative, commit-subject-length line at
  column 0 with a bare type token (`fix: short subject`), blank-line separated,
  with any longer explanation on an *optional description line underneath* —
  not packed into the entry line itself. Release Please parses each entry line
  as its own commit subject and will truncate a long one mid-sentence in the
  rendered changelog. No `-`/`*` bullets, and don't repeat the title as an
  entry.
- **CLI-authored bodies** — create multi-paragraph Markdown in a file passed to
  `gh pr create` or `gh pr edit` with `--body-file`; a shell-quoted `\n` is
  literal text. Before marking a standard PR ready, read it back with
  `gh pr view <n> --json body --jq .body` and verify the paragraphs render.
- **Squash merges** — ensure the final squash commit message retains all
  applicable `Co-Authored-By:` trailers. When using `gh pr merge --squash`, pass
  the trailers in the squash commit body via `--body`; do not pass an empty
  body. Verify the resulting commit message after merging.

### Release Please pull requests

Release Please PRs are bot-generated release artifacts, not standard PRs.

- Do not edit their generated title or body merely to apply the standard-PR
  formatting rules.
- When merge is authorized and the required checks and branch-protection
  requirements are satisfied, squash merge using GitHub's default title and
  body content. Do not supply a custom squash title or body.
- Do not add an AI co-author trailer unless it is already applicable to the
  release commit itself.

- **Blocked pull requests** — when a pull request is blocked by required
  status checks (most often a release PR), follow
  [`docs/branch-protection-runbook.md`](docs/branch-protection-runbook.md);
  never weaken the required check set to land a change.

## When instructions and reality disagree

Flag the gap instead of silently diverging. If a guardrail blocks a genuinely
better approach, raise it with the operator rather than working around it.

For user-facing changes, verify the rendered or running product in addition to
automated checks; tests alone do not establish visual or interaction quality.

For changes affecting tracked screenshots or captured views, follow the
repository's documented screenshot-review process when present. A successful
screenshot-generation workflow means only that artifacts were produced; it is
not visual approval. Never capture live or private data, and do not commit
regenerated assets until the required visual and privacy review has passed.

## Preservation and destructive operations

Preserve existing user work and unrelated repository changes. Do not discard,
reset, overwrite, or destructively clean existing work unless the user's
request explicitly requires it and the consequences are understood. Prefer
reversible operations when they satisfy the task equally well.

## Definition of done

Run the relevant automated checks and targeted tests for changed behaviour,
including failure paths where practical. Update documentation, fixtures, and
migration or rollout notes when they form part of the changed contract. Report
the checks run and any validation that could not be completed; do not claim
unrun checks passed.

## Tooling

Run both checks before pushing:

```sh
python3 validate_templates.py
node --test templates/*.test.mjs
```
