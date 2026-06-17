## Scope-Aware Patch Contract Verification

When a change intent is active, `check_patch_contract(mode="verify")` attributes
regressions and gate changes to the declared scope rather than treating the
entire workspace as one undifferentiated surface.

### Regression attribution

Regressions from `compare_runs` are partitioned into two sets:

- `intent_regressions` — findings whose file paths fall inside the declared
  `allowed_files` or `allowed_related`.
- `external_regressions` — findings whose file paths are entirely outside
  the declared scope.

Only `intent_regressions` produce `structural_regressions` contract violations.
External regressions are reported as informational context without failing the
contract.

Findings with no extractable file paths are conservatively classified as
intent-scope to avoid false-negative accepts.

Without an active intent, all regressions are treated as intent-scope and
behavior is unchanged from the base contract.

### Scope matching vs verify attribution

Scope **check** (`unexpected_files`) uses exact membership in `allowed_files` /
`allowed_related`. Verify regression attribution uses `fnmatchcase` on those
patterns (and treats path-less findings as in-scope). Do not assume identical
matching rules across check and verify — declare literal paths in scope lists.

### Gate-delta logic

Gate evaluation uses a two-layer attribution model:

1. **Gate delta** — only gate *changes* between before-run and after-run are
   contract-relevant. A gate that was already failing before the edit is
   pre-existing, not a new violation. `gate_worsened` is true only when
   `before_gate.would_fail` is false and `after_gate.would_fail` is true.

2. **Gate attribution** — when `gate_worsened` is true and an intent is active,
   the contract checks whether the gate-triggering signals come from intent
   scope: intent-scope regressions or intent-scope worsened metric symbols. If
   neither exists, the gate failure is external and does not produce a contract
   violation.

### Status values

| Status                           | Meaning                                                                  |
|----------------------------------|--------------------------------------------------------------------------|
| `accepted`                       | No intent-scope regressions, no gate worsening                           |
| `accepted_with_external_changes` | Intent scope is clean but external signals exist                         |
| `violated`                       | Intent-scope regressions, intent-caused gate failure, or scope violation |
| `unverified`                     | Missing before or after run                                              |
| `expired`                        | Report digest mismatch since declaration                                 |

The `accepted_with_external_changes` status signals that another agent or
concurrent edit introduced regressions outside the current intent scope. The
verify response includes `intent_regressions`, `external_regressions`,
`intent_worsened`, `external_worsened`, `gate_worsened`, and `before_gate`
fields for full attribution visibility.

??? info "Decision table"

    | Intent | Intent regressions | External regressions | Gate worsened | Intent caused gate | Scope check | Status                           |
    |--------|--------------------|-----------------------|---------------|--------------------|-------------|----------------------------------|
    | no     | any                | —                     | any           | any                | —           | current logic unchanged          |
    | yes    | > 0                | any                   | any           | any                | any         | `violated`                       |
    | yes    | 0                  | any                   | yes           | yes                | clean       | `violated`                       |
    | yes    | 0                  | any                   | yes           | no                 | clean       | `accepted_with_external_changes` |
    | yes    | 0                  | > 0                   | no            | —                  | clean       | `accepted_with_external_changes` |
    | yes    | 0                  | 0                     | no            | —                  | clean       | `accepted`                       |
    | yes    | 0                  | any                   | any           | any                | violated    | `violated` (scope violation)     |

### Baseline abuse

`detect_baseline_abuse` stays workspace-global. Baseline hygiene is a
repository-level signal: if the baseline was updated while any regressions exist
(even external), that is suspicious regardless of whose regressions they are.
