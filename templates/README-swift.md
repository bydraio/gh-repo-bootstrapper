# __REPOSITORY_NAME__

> A Swift project bootstrapped with GitHub Actions, Release Please, and
> Dependabot. Replace this sentence with the project’s purpose and intended users.

| Detail | Value |
|---|---|
| Status | Initial setup |
| Test scheme | `__SCHEME__` |

## Start here

Add the project source, tests, and package or Xcode project before shipping.
The generated workflows enforce formatting and test the configured scheme.

## Local development

Open the project in Xcode, or use the command line after selecting a compatible
Xcode toolchain. See `AGENTS.md` for the generated-project workflow and the
configured simulator destination.

## Verification

Run formatting and tests before opening a pull request:

```sh
xcrun swift-format lint --recursive --strict .
xcodebuild test \
  -scheme __SCHEME_SHELL__ \
  -destination "__DESTINATION_EXAMPLE__"
```

## Project guide

- `AGENTS.md` — branch, commit, pull-request, and validation workflow.
- `docs/branch-protection-runbook.md` — how to unblock required GitHub checks.
