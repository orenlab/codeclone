---
title: "Exit codes"
audience: public
doc_type: reference
status: draft
source_commit: "d88c17f0f19cf753b9d43870528e0747b3161b9c"
---

## What it is

CodeClone exits with a numeric code that signals whether the run succeeded, encountered a configuration error, failed a quality gate, or crashed internally. These codes integrate with CI systems, shell scripts, and automated workflows.

## When to use it

- **CI pipelines:** branch protection rules that block on exit code 3 (gating failures)
- **Local verification:** checking whether a patch meets structural requirements
- **Automation:** conditional logic in deployment or merge workflows
- **Debugging:** distinguishing configuration problems from structural findings

## Basic workflow

Run CodeClone and check the exit code:

```bash
codeclone --patch-verify --fail-on-new
echo $?  # prints the exit code
```

Exit codes are deterministic: the same input always produces the same code.

## Exit codes reference

| Code | Meaning | Cause | Action |
|------|---------|-------|--------|
| **0** | Success | No structural findings, no gate violations, no errors | Patch is approved |
| **2** | Contract error | Untrusted/invalid baseline, invalid output configuration, incompatible versions, unreadable sources in CI/gating mode | Fix configuration or baseline before proceeding |
| **3** | Gating failure | New clones, threshold violations, or metrics quality gate failures | Address findings or adjust thresholds before merge |
| **5** | Internal error | Unexpected exception | Report the error with `--debug` output |

## Key commands

**Understand why a run failed:**

```bash
# Verbose output with details
codeclone --patch-verify --fail-on-new --verbose
# Exit code 3 + detailed finding listings

# Debug internal crashes
codeclone --debug
# Exit code 5 + traceback and environment info
```

**Strict vs. relaxed gating:**

```bash
# CI preset: fail fast on new clones, metrics regression
codeclone --ci

# Relaxed profile: report findings but allow threshold violations
codeclone --patch-verify --strictness relaxed
```

## Common mistakes

- **Treating code 2 as a gate failure:** Code 2 is a contract violation (broken baseline, bad config). Fix the configuration, don't adjust thresholds.
- **Ignoring code 5 in production:** Code 5 signals an unexpected internal error. Collect `--debug` output and report it.
- **Running without `--patch-verify` in CI:** Without `--patch-verify`, CodeClone runs full analysis and will not gate on new findings. Use `--ci` or `--patch-verify --fail-on-new` for blocking checks.

## Next steps

- Review the `--fail-*` gating flags in the [CLI reference](cli.md) to configure threshold and gating behavior.
- Use `codeclone --help` to see all available flags for exit-code control.
