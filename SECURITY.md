# Security policy

## Reporting a vulnerability

Please report security issues through GitHub's private vulnerability reporting:
open the repository's **Security** tab and choose **Report a vulnerability**.
That keeps the report private until a fix is available. Please don't open a
public issue for anything exploitable.

A proof of concept in a private advisory is welcome — it is the one exception to
the "no code in issues" rule in [CONTRIBUTING.md](CONTRIBUTING.md). It is used to
**reproduce and confirm** the report; it will not be merged, and neither will a
suggested patch. Remediation is implemented independently, consistent with the
contribution policy. Reporters are credited in the advisory and release notes.

## Scope

`bootstrap.py` runs locally, on the operator's own machine, under their own
authenticated `gh` CLI session. It has no server component and stores no
credentials — it reads GitHub App secrets from prompts
or environment variables and passes them to `gh` over stdin (never as
command-line arguments, so they stay out of the process list).

The most useful things to report:

- A path where a secret is written to disk, logged, or passed as an argv element.
- A generated workflow that grants more `GITHUB_TOKEN` scope than it needs, is
  triggerable by an untrusted fork PR, or interpolates untrusted input into a
  `run:` block.
- Repository configuration applied by `configure_repo()` that is weaker than the
  README describes.

Findings in the *generated* templates matter as much as findings in the
bootstrapper: those files are copied into every repository this tool creates.
