---
title: "Upgrading from 2.1.0a1 to 2.1.0a2"
audience: public
doc_type: guide
status: draft
source_commit: "c302179335b082f30d58f29e4a238165c28e04bc"
---

# Upgrading from 2.1.0a1 to 2.1.0a2

Three things change in a way you must act on: the baseline, seven config keys
plus the authority table array, and two removed flags. Health numbers may also
move — that is expected, and the last section explains why.

## Upgrade in order

1. Upgrade every machine that runs CodeClone **before** adding the new config
   keys.
2. Add `baseline_scope_id` to `[tool.codeclone]`.
3. Regenerate the baseline with `--update-baseline` and commit it.

Step 1 is not optional. 2.1.0a1 rejects the new keys outright:

```text
CONTRACT ERROR:
Unknown key(s) in tool.codeclone: authority, baseline_scope_id,
fail_on_authority_violation, semantic_authority
```

Exit code 2. An unknown key is a contract error, not a warning, so a CI runner
still on the old version fails the moment the new config lands — before it
analyzes anything.

## Baselines must be regenerated

Old baselines are contract-incompatible. What happens when you read one depends
on whether you gate.

**Without baseline-aware gate flags the run completes, exit 0.** The baseline is
refused and ignored:

```text
Invalid baseline file.
legacy baseline format
Please regenerate the baseline with --update-baseline.
Baseline is not trusted for this run and will be ignored.
Baseline-relative novelty is unavailable for this run.
Run: codeclone . --update-baseline
```

Analysis still runs and metrics still print — but every clone group reports
`unavailable` novelty, so a green exit code here means nothing was compared.

**With a baseline-aware gate such as `--fail-on-new`, exit 2:**

```text
Invalid baseline file.
legacy baseline format
Please regenerate the baseline with --update-baseline.
...
CONTRACT ERROR:
Baseline-aware gates require a trusted baseline.
Run: codeclone . --update-baseline
```

Regeneration is mandatory, not advisory. A legacy baseline that is transitioned
has its exact original bytes authenticated and recorded as transition evidence,
so the epoch change stays auditable instead of being silently overwritten.

The analysis cache is also superseded. It invalidates itself and reports it, so
no action is needed:

```text
Cache version mismatch
  found 2.10
  ignoring cache
```

## `baseline_scope_id` is now required

Baseline update and baseline-relative gating both require a stable canonical
UUID:

```toml
[tool.codeclone]
baseline_scope_id = "<a UUID of your own>"
```

The value has to be yours: it is the discriminator that stops one project's
baseline being compared against another's, so two projects must never share one.
Do not copy the placeholder above.

You do not have to invent it. Run CodeClone without the key and it names the
command that writes one first, then hands you a generated UUID for anyone who
would rather paste it, together with the file it belongs in and whether the
section already exists:

```text
CONTRACT ERROR:
baseline_scope_id is required for baseline update and gating; set a stable
canonical UUID under [tool.codeclone].

Run setup to write it (codeclone setup plan previews every change):

    codeclone setup apply -y

Or add this line to [tool.codeclone] in /srv/acme/pyproject.toml:

    baseline_scope_id = "0f5c6f3d-9d2e-4a2a-9a5f-6b0f9a1a2b3c"

That UUID was generated for this run. Commit it and never change it: it is what
keeps this project's baseline from being read as another's.
```

`codeclone setup apply -y` is offered when a `pyproject.toml` exists; with no
file there is nothing for setup to merge into, and only the paste is offered.
Either way, commit the key and never change it.
(`python -c "import uuid; print(uuid.uuid4())"` produces one too.)

## Removed flags and keys

| Removed CLI flag | Use instead |
|------------------|-------------|
| `--metrics-baseline [FILE]` | `--baseline [FILE]` |
| `--update-metrics-baseline` | `--update-baseline` |

The matching **pyproject keys were removed too**, and they fail harder than the
flags: an obsolete key is rejected before analysis starts.

```text
CONTRACT ERROR:
Unknown key(s) in tool.codeclone: metrics_baseline, update_metrics_baseline
```

Exit 2. Delete `metrics_baseline` and `update_metrics_baseline` from
`[tool.codeclone]` as part of the upgrade — leaving them in place blocks every
run, not just gated ones.

Clone findings and metrics are now lanes in one baseline container, so one flag
pair governs both. See [Baseline container and lane trust](../concepts/baseline-container.md).

## New keys and flags

Seven new keys, plus the authority array of tables:

| Key | Flag | Effect |
|-----|------|--------|
| `baseline_scope_id` | — | Required for baseline update and gating |
| `project_label` | — | Project name recorded in the published baseline metadata |
| `source_roots` | — | Explicit import roots for module identity |
| `semantic_authority` | `--semantic-authority` | Report-only authority candidates |
| `fail_on_authority_violation` | `--fail-on-authority-violation` | Exit 3 on a governed-contract violation |
| `fail_on_unresolved_dead_code` | `--fail-on-unresolved-dead-code` | Exit 3 on unresolved external overrides |
| `dead_code_world` | `--dead-code-world` | World contract for dead-code verdicts (`open` by default): a symbol consumers outside the repository could reach is reported as `unresolved`, never asserted dead on internal evidence alone; `closed` calls it dead |
| `near_miss` | `--near-miss` | Advisory near-miss clone channel |
| `[[tool.codeclone.authority]]` | — | The reviewed authority registry |

Add these only after every runner is on 2.1.0a2 — 2.1.0a1 rejects all of them.

## Contract versions

| Contract | Constant | Version |
|----------|----------|---------|
| Baseline schema | `BASELINE_SCHEMA_VERSION` | `3.0` |
| Baseline fingerprint | `BASELINE_FINGERPRINT_VERSION` | `3` |
| Wire | `WIRE_VERSION` | `2` |
| Cache | `CACHE_VERSION` | `4.2` |
| Report schema | `REPORT_SCHEMA_VERSION` | `3.6` |
| Metrics baseline schema | `METRICS_BASELINE_SCHEMA_VERSION` | `1.3` |

## Health may drop — lower but truer

Expect health scores to move, and expect some to move down. The semantics got
honest; the code did not get worse.

- **Complexity counts authored decisions.** `cyclomatic_complexity` — the
  value health, risk bands and gates read — is a source-level count of the
  decisions written in each function (`if`/`elif`, ternaries, `and`/`or`,
  loops, comprehension clauses, `except` clauses, `match` cases, `assert`).
  Exception routing, `finally` and context managers add nothing to it. Full
  McCabe over the normalized CFG is reported beside it as the diagnostic
  `cfg_cyclomatic_complexity` and never feeds health or a gate. The 2.1.0a1
  values are not comparable and are treated as untrusted, not diffed.
- **Every function is measured.** Clone-lane size floors no longer decide which
  functions carry a complexity fact, so small functions now count toward the
  population.
- **Complexity and coupling are bounded.** Each dimension spends its points
  across four bounded terms instead of tracking a single worst offender. A
  dimension previously pinned at its floor by one outlier can now move.
- **Design-metric values are not comparable across the epoch.** The design
  metrics algorithm revision moved from `1` to `2`, so old values are treated as
  untrusted rather than diffed against new ones.

If you gate on `--fail-health`, re-read the score after regenerating the baseline
and re-tune the threshold once, rather than treating the first post-upgrade run
as a regression.

## Related pages

- [Baseline container and lane trust](../concepts/baseline-container.md)
- [Complexity: two metrics, one owner each](../concepts/complexity.md)
- [Health explainability](../concepts/health-explainability.md)
- [CI integration](ci-integration.md)
