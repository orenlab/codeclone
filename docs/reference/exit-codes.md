---
title: "Exit codes"
audience: public
doc_type: reference
status: published
source_commit: "60eac9c367d74deeba1478521461addfedd8e681"
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
| **0** | Success | No gate violations and no errors. Findings may still be present — exit `0` means nothing enabled gated on them, not that the report is empty | Run succeeded; review findings if any |
| **2** | Contract error | Untrusted/invalid baseline, invalid output configuration, incompatible versions, unreadable sources in CI/gating mode, a path argument CodeClone cannot use | Fix configuration or baseline before proceeding |
| **3** | Gating failure | New clones, threshold violations, or metrics quality gate failures | Address findings or adjust thresholds before merge |
| **4** | Unverified | The environment prevented the analysis from running: the worker pool could not start, no worker ran, and the operating system's error proves it refused (see the table below). Nothing was measured: no verdict, no report and no baseline are written | Run sequentially with `--processes 1` (or `processes = 1` under `[tool.codeclone]`), or lift the limit |
| **5** | Internal error | Unexpected exception, or an analysis that could not be completed: a file whose isolated retry after a worker death died or timed out, a retry process that could not be started, or a result that breaks an internal invariant. The message keeps every failure, the first one first -- for example the worker crash, then why the retry failed -- and gives the files confirmed, the culprit (`UNKNOWN` when no file was in flight) with the attempts on it, and the files not processed; no report or baseline is written | Report the error with `--debug` output |

## Why a worker pool could not start

Execution unavailable is not invalid input, and neither is it proof of an
internal defect. Exit 4 needs positive proof that the environment refused: an
error number the operating system set while the pool created its processes
(its construction, or the start of its workers). Any other cause -- an error
without a number, a number not listed here, an error raised by anything but
process creation -- keeps its own exit code, so exit 4 never hides a defect.

| Error number | Meaning | Exit |
|--------------|---------|------|
| `EAGAIN` | A process or thread limit was reached (what a real process limit raises on every start method) | 4 |
| `ENOMEM` | Not enough memory to start a worker process | 4 |
| `EMFILE`, `ENFILE` | The per-process or system-wide limit on open files was reached | 4 |
| `EPERM`, `EACCES` | The operating system or a sandbox refused a process or a resource the pool needs | 4 |
| `ENOSYS`, `ENOSPC` | The platform lacks, or has no room for, the process-shared semaphores the pool needs | 4 |
| Any other cause | Not proven to be the environment's | 5 |

| Situation | Exit |
|-----------|------|
| The pool never started, an error number above proves why, no worker ran | 4 |
| A worker died and the isolated retry succeeded | The full result |
| A worker died and the retry process could not be started -- even for `EAGAIN` | 5 |
| A worker died and the retry died, hung or broke the protocol | 5 |
| Some workers ran, then the pool was refused | 5 |
| `--processes 1` (sequential mode) | Starts no pool |

## Inputs that are a contract error, not a crash

These inputs used to end in the internal-error handler (exit 5) or, for the
`setup` and `memory` subcommands, in a raw traceback. Each is now refused with a
message that names the input, or handled as described:

| Input | Now |
|-------|-----|
| A path that names an unknown user's home, such as `--baseline ~nobody/b.json`, `--cache-path`, a report flag (`--html`, `--json`, …), or `setup`/`memory --root` | Exit 2, `Invalid … path` / `Repository root …` |
| A path or error text containing Rich markup brackets, such as `--html 'out[/x].htm'`, a missing root `no[/x]`, or `memory --root 'p[/x]'` | Exit 2; the text is printed as written |
| A `.gitignore` that is not UTF-8 | `setup` and MCP analysis run; the `.gitignore` append is blocked and names the decoding error |
| A baseline whose stored digest is not ASCII | Baseline status `integrity_failed`, as for any other digest mismatch: ignored with a warning, exit 2 under `--ci` |
| A stored report whose digest is not ASCII | Refused as a digest mismatch of that tier; `memory init` runs a fresh analysis |
| An empty `[project.scripts]` value (`x = ""`) | Ignored; the other entry points still resolve |
| A worker process that dies mid-run | The files it never returned are retried once, in a separate child process; nothing is counted twice. If the retry dies or times out too, the run ends with exit 5 (above) |

`codeclone setup apply --json` without `--yes` or `--dry-run` is also exit 2:
`--json` output is one JSON document and cannot carry an interactive prompt.

A parallel worker pool the environment refuses is exit 4 (above). It used to
fall back to sequential analysis in the main process with a warning.

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
