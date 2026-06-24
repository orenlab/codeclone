---
name: codeclone-architecture-triage
description: Rank demonstrated architectural problems from one canonical run plus targeted source verification. Read-only; priorities are response-local heuristics, never CodeClone findings.
---

# CodeClone Architecture Triage

**CodeClone emits facts. This skill enforces evidence order, defect classification, and contract-honest ranking.**

Return architectural **problems**, not a refactor checklist.

```text
structural prominence ≠ change risk ≠ architectural defect
```

## 1. Use and routing

Use for architecture shape, coupling hubs, ownership, package boundaries, duplicated application workflows, or
domain/application semantics leaking into surfaces.

| Need                          | Use instead                                             |
|-------------------------------|---------------------------------------------------------|
| Health / baseline regressions | `codeclone-production-triage`                           |
| One metric / hotspot          | `codeclone-hotspots`                                    |
| Pre-edit blast                | `codeclone-blast-radius` / `get_implementation_context` |
| Full findings / gates         | `codeclone-review`                                      |
| Context for one edit          | `codeclone-implementation-context`                      |
| Any write                     | `codeclone-change-control`                              |

## 2. Evidence protocol

**Invariant:** one response = one absolute `root` + one stored `run_id`; reuse that run for all structural projections.

```text
resolve/reuse run_id
→ analyze_repository(root=<abs>) only if no run exists,
  needs_analysis is returned, or fresh analysis is requested
→ get_report_section(run_id, "module_map")
→ get_report_section(run_id, "metrics")
→ build independent shortlists:
    structural ≤5: hubs / overloaded / unwind
    policy ≤3: surfaces / adapters / integration modules
→ metrics_detail only for shortlisted structural candidates
→ get_implementation_context(
    root=<abs>, run_id=<run_id>, paths=[single_subject],
    mode="impact", depth=1,
    include=["module_role", "imports", "importers", "blast_radius"],
    budget=80,
  )
→ targeted source/rule verification
→ classify → validate → finalize → render
```

Policy candidates do not consume the structural limit. Include small modules that import or implement lifecycle,
authorization, budgeting, sync, recovery, scope, persistence, transaction, domain-model, or orchestration semantics.

Rules:

- MCP is authoritative for CodeClone facts; do not substitute CLI output or parsed reports.
- Source reads verify rules, ownership, duplicated semantics, responsibility boundaries, and policy/entity placement.
- `module_map` gives shape; impact context gives named importers and subject blast.
- Disclose truncation, drift, unavailable facets, and `dataflow not_available`.
- Preserve metric scale; distinguish total fan-in from verified production importers.
- Size, fan-in, blast, private naming, hub shape, and sink role are evidence of prominence/risk only.

## 3. Defect model

Each ranked item has exactly **one named subject path** and one primary signal.

| Signal                             | Defect predicate                                                                            | Eligible tiers                       |
|------------------------------------|---------------------------------------------------------------------------------------------|--------------------------------------|
| `boundary_violation`               | Production edge violates an explicit architecture rule/test                                 | A; C/D/E with independent evidence   |
| `dependency_inversion`             | Direction conflicts with a verified layer/ownership rule                                    | A; C/D/E with independent evidence   |
| `hidden_contract`                  | Private contract crosses its implementation owner or meaningful production package boundary | B; C/D/E with independent evidence   |
| `ownership_drift`                  | Current owner and different required owner are both evidenced                               | B; C/D/E with independent evidence   |
| `domain_logic_leakage`             | Surface/adapter owns reusable policy or domain-entity semantics                             | B; C/D/E with independent evidence   |
| `duplicated_application_semantics` | Multiple owners implement the same reusable workflow/defaults/validation/recovery           | B; C/D/E with independent evidence   |
| `responsibility_overload`          | Correctly placed module combines independently evolving responsibilities                    | D/E; C from named-subject high blast |
| `blast_hotspot`                    | Named subject has high blast plus an independent defect                                     | C only; never standalone             |
| `import_hub`                       | Production hub reinforces an independent defect                                             | D only; never standalone             |

Constraints:

- A literal import proves the edge, not automatically the defect.
- A large module in the correct package is not `ownership_drift`.
- Same-package modules/mixins are not automatically a `hidden_contract`.
- Two surfaces using one backend do not prove duplicated semantics.
- Correctly placed sinks, composition roots, config owners, and internal hubs belong in the watchlist unless another
  defect is demonstrated.
- Private imports raise suspicion but do not prove a boundary violation.

## 4. Policy and entity leakage

Run this test for **every policy-shortlist candidate**, even if small or low-fan-in:

```text
Does this module only adapt protocol/input/output,
or does it decide reusable policy or define/mutate domain meaning?
```

Classify each cited behavior:

- **reusable policy/entity semantics** — domain/application/controller ownership;
- **surface adaptation** — adapter ownership.

Tier B requires at least one directly demonstrated reusable policy/entity semantic.

Reusable semantics include lifecycle/authorization decisions, budget/eligibility/default selection,
sync/bootstrap/recovery policy, scope/identity/state-transition rules, persistence/transaction decisions, reusable
validation/normalization, transport-neutral workflow order, and creation/mutation/interpretation/invariants of domain
entities.

Not leakage alone: parsing, routing, serialization, payload shaping, transport errors, display guidance, protocol DTO
conversion, surface-only checks/enrichment, or reading immutable domain entities through a stable application API.

```text
domain_logic_leakage = reusable policy/entity meaning lives in a surface
ownership_drift      = contract belongs to the wrong owner
duplication          = same reusable semantics exist in multiple owners
```

Do not call mere exposure of a domain type leakage. The surface must define, mutate, validate, default, sequence, or
interpret reusable semantics.

## 5. Confidence

Confidence applies to the **defect**, not the metrics.

- `verified`: explicit rule/test/contract or literal duplicated/policy behavior establishes the defect.
- `supported`: facts are verified; architectural consequence is strong but not explicitly mandated.
- `tentative`: more source verification is required; cap at P2.

Defaults: responsibility overload is usually supported; private cross-package imports are usually supported unless
forbidden; leakage is usually supported unless the policy/entity boundary is explicit or literal.

## 6. Scoring

Response-local only; never a CodeClone metric/finding/gate.

| Tier | Points | Condition                                                                                         |
|------|-------:|---------------------------------------------------------------------------------------------------|
| A    |    +40 | Verified boundary violation or dependency inversion                                               |
| B    |    +25 | Supported/verified hidden contract, ownership drift, leakage, or duplicated application semantics |
| C    |    +15 | High blast for the single named subject                                                           |
| D    |    +10 | Import hub or responsibility overload reinforces the defect                                       |
| E    |     +5 | Unwind/bottleneck increases demonstrated risk                                                     |
| F    |    -10 | Tests-only evidence; no production importer                                                       |

Hard rules:

1. Each tier applies once; same-tier signals do not stack.
2. Responsibility overload never receives B.
3. Dependency inversion receives B only through a separately classified, independently supported B-eligible signal.
4. C comes only from the named subject's own impact result; never from compound scope, package, neighbor, or composition
   root.
5. Bands: P0 ≥50; P1 35–49; P2 20–34; P3 <20.
6. Tie-breakers order within a band only: production importers → blast → affected packages.
7. Heading band must equal validated arithmetic.

For multi-owner defects, choose the subject containing the criticized implementation—not the participant with the
highest blast. Cite other owners as counterparts.

## 7. Final validation

Before prose, finalize:

```text
subject | signal(s) | confidence | eligible tiers | awarded tiers | total | band
```

Reject, fix, or move to watchlist unless:

1. one named subject exists;
2. a defect predicate is demonstrated;
3. every tier is eligible for an explicit signal;
4. confidence matches defect evidence;
5. C uses that subject's impact result;
6. leakage separates reusable semantics from adaptation;
7. responsibility overload has no B;
8. tie-breakers do not change score/band;
9. heading and triage basis match;
10. no visible recalculation or band revision remains.

Render only from this finalized table.

## 8. Output

Rank ≤7 problems. Put correct hubs and unproven opportunities in a one-line watchlist. If none qualify, say the
architecture is healthy.

Disclose policy-scan coverage:

```text
Policy scan: inspected <subjects>; not exhaustive when candidates remain.
```

Absence of leakage means “not demonstrated in inspected candidates,” never “no leakage exists.”

For multi-module evidence separate direct subject importers, direct hub importers, and transitive consumers.

```markdown
## Architecture triage summary

- Run / root / health
- Overall shape
- Evidence limits
- Policy scan coverage
- Heuristic: response-local only; not CodeClone findings

### 1. [P2] <title> — `<signal>` / <track>

- **Confidence:** …
- **Subject:** `path`
- **Evidence:** facts, edge kinds, subject blast, verified rules
- **Defect predicate:** …
- **Policy/entity boundary:** reusable semantics vs adaptation (leakage only)
- **Triage basis:** B = 25 → P2
- **Why it matters:** …
- **Expected effect:** …
- **Not sufficient:** …
```

Omit `Policy/entity boundary` for non-leakage items unless explaining why leakage was not awarded. Do not imply an
unclassified secondary defect.

Tracks: Core architecture · Refactoring / modernization · Dependency & boundary hygiene. Tracks do not score.

One-sentence direction is allowed. No implementation checklist unless asked. Any implementation uses
`codeclone-change-control`.

## 9. Prohibitions

Do not edit, declare intent, verify patches, replace `codeclone-review`, invent debt from prominence alone, substitute
`rg` frequency for MCP evidence, claim CodeClone assigned priorities, award A without an applicable explicit rule, award
B to responsibility overload, score compound blast, alter bands narratively, or classify transport/UI adaptation or mere
domain-type exposure as leakage.
