
## Tooling
Run all checks before pushing:

```sh
ruff format .   # format
ruff check .    # lint (matches CI)
mypy .          # type check
pytest          # tests
```

Install dependencies first — use `pip install -r requirements-dev.txt`,
`pip install -r requirements.txt`, or `pip install -e ".[dev]"` as appropriate.

CI picks the same order automatically. For the `pyproject.toml` case it
detects a PEP 621 `[project.optional-dependencies] dev = [...]` extra and
installs `.[dev]` only when that extra is actually declared, falling back to
a plain `pip install -e .` otherwise. Projects that declare dev dependencies
through tool-specific metadata instead (e.g. Poetry's
`[tool.poetry.group.dev.dependencies]`) aren't detected by this check — add a
`requirements-dev.txt` to have CI install that dependency set explicitly.
