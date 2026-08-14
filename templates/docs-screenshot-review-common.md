# Screenshot review guidance

This guidance is capability-conditional. Use only screenshot capture and review
capabilities that the application repository actually provides; the
bootstrapper does not add capture dependencies, screenshot workflows, or
tracked image assets.

## Safety boundary

Never capture live, private, customer, or credential-bearing data. Keep
temporary captures outside version control until visual and privacy review is
complete. A successful capture or test run proves only that artifacts were
produced; it is not visual or privacy approval.

## Review workflow

Before accepting a screenshot, confirm that it represents the intended local
or fixture-backed state, contains no sensitive information, and is reproducible
with capabilities already present in the repository. Record repository-specific
capture commands and review decisions in the application repository, not in
this generic generator guidance.

For the shared maintainer boundaries, see [AGENTS.md](../AGENTS.md).

# <<PLATFORM_GUIDANCE>>
