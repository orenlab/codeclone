---
title: "Upgrading from 2.1.0a1 to 2.1.0a2"
audience: public
doc_type: guide
status: draft
source_commit: "47b7ef37dbe958c40753b933af18beb9480a8b80"
---

# Upgrading from 2.1.0a1 to 2.1.0a2

Three things change in a way you must act on: the baseline, four config keys,
and two removed flags. Health numbers may also move — that is expected, and the
last section explains why.

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

Old baselines are contract-incompatible. Reading a 2.1.0a1 baseline with the new
version exits 2:

```text
CONTRACT ERROR:
Invalid baseline file.
legacy baseline format
Please regenerate the baseline with --update-baseline.
```

Regeneration is mandatory, not advisory. A legacy baseline that is transitioned
has its exact original bytes authenticated and recorded as transition evidence,
so the epoch change stays auditable instead of being silently overwritten.

The analysis cache is also superseded. It invalidates itself and reports it —
`Cache version mismatch / found 2.10 / ignoring cache` — so no action is needed.

## `baseline_scope_id` is now required

Baseline update and baseline-relative gating both require a stable canonical
UUID:

```toml
[tool.codeclone]
baseline_scope_id = "0189f1a2-3b4c-7d8e-9f01-234567890abc"
```

Without it:

```text
CONTRACT ERROR:
baseline_scope_id is required for baseline update and gating; set a stable
canonical UUID under [tool.codeclone].
```

Generate it once (`python -c "import uuid; print(uuid.uuid4())"`), commit it, and
never change it — it is what stops one project's baseline being compared against
another's.

## Removed flags

| Removed | Use instead |
|---------|-------------|
| `--metrics-baseline [FILE]` | `--baseline [FILE]` |
| `--update-metrics-baseline` | `--update-baseline` |

Clone findings and metrics are now lanes in one baseline container, so one flag
pair governs both. See [Baseline container and lane trust](../concepts/baseline-container.md).

## New keys and flags

| Key | Flag | Effect |
|-----|------|--------|
| `baseline_scope_id` | — | Required for baseline update and gating |
| `semantic_authority` | `--semantic-authority` | Report-only authority candidates |
| `fail_on_authority_violation` | `--fail-on-authority-violation` | Exit 3 on a governed-contract violation |
| `near_miss` | `--near-miss` | Advisory near-miss clone channel |
| `[[tool.codeclone.authority]]` | — | The reviewed authority registry |

## Contract versions

| Contract | Version |
|----------|---------|
| Baseline schema | `3.0` |
| Baseline fingerprint | `3` |
| Wire | `2` |
| Cache | `3.2` |
| Report schema | `3.0` |
| Metrics baseline schema | `1.3` |

## Health may drop — lower but truer

Expect health scores to move, and expect some to move down. The semantics got
honest; the code did not get worse.

- **Complexity rose.** V(G) is now full McCabe over the normalized CFG.
  Exception dispatch, `finally` routing and context-manager suppression are real
  control flow and are counted. Values are higher than tools that ignore those
  paths report, and higher than 2.1.0a1 reported.
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
- [Full-McCabe complexity](../concepts/complexity.md)
- [Health explainability](../concepts/health-explainability.md)
- [CI integration](ci-integration.md)
