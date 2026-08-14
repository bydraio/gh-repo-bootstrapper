# Current work

**Status:** one cross-fleet workflow-compatibility item remains.

## `baseline-review.yml` and actionlint

The canonical Next.js `baseline-review.yml` requests
`vulnerability-alerts: read`, and `validate_templates.py` requires that exact
permission because the scheduled review queries Dependabot alert data. Current
actionlint reports `vulnerability-alerts` as an unknown permission scope.

Resolve this centrally in the bootstrapper, not through divergent application
repository edits:

1. Verify the least-privilege, supported GitHub Actions permission needed by
   the scheduled Dependabot-alert query.
2. Update the canonical workflow and its validator together, or record a
   precise, upstream-supported actionlint exception if the permission is valid
   but unsupported by actionlint.
3. Validate the template and all rendered Next.js workflows with actionlint.
4. Verify the scheduled workflow can still read the intended alert data before
   propagating the canonical change to application repositories.

**Completion gate:** template validation and actionlint agree, the scheduled
review retains its intended read-only behaviour, and generated repositories do
not carry per-repository permission workarounds.
