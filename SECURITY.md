# Security policy

## Reporting a vulnerability

GitHub private vulnerability reporting is the sole security channel for this
repository. Open the repository's **Security** tab and choose **Report a
vulnerability**. Do not open a public issue for anything exploitable or for
information that would make exploitation easier.

A proof of concept may be included in the private advisory when it is needed
to reproduce and confirm the report. It will not be merged, and neither will a
suggested patch; remediation is implemented independently under the policy in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

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
