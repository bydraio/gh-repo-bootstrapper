# __REPOSITORY_NAME__

> A Python project bootstrapped with GitHub Actions, Release Please, and
> Dependabot. Replace this sentence with the project’s purpose and intended users.

| Detail | Value |
|---|---|
| Status | Initial setup |
| Runtime | Python __PYTHON_VERSION__ |

## Start here

The bootstrapper supplies repository automation, but deliberately does not
choose a package layout or dependency manager. Add the application or library,
its tests, and either `pyproject.toml` or requirements files before shipping.

## Local development

### Preferred: uv

Create and activate an isolated environment with [uv](https://docs.astral.sh/uv/):

```sh
uv venv
source .venv/bin/activate
```

After adding project dependencies, use the matching `uv` command — for example,
`uv sync` for a uv-managed `pyproject.toml`, or
`uv pip install -r requirements-dev.txt` for a requirements-based project.

### Standard-library alternative

If `uv` is not available, create the same environment with Python:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install the project’s declared dependencies after activating the environment.

## Verification

Once the project has code and tests, run the local quality checks below. CI
runs `ruff check`, `mypy`, and `pytest`.

```sh
ruff format --check .
ruff check .
mypy .
pytest
```

## Project guide

- `AGENTS.md` — branch, commit, pull-request, and validation workflow.
- `docs/branch-protection-runbook.md` — how to unblock required GitHub checks.
