---
title: "Health score"
audience: public
doc_type: concept
status: draft
source_commit: "d88c17f0f19cf753b9d43870528e0747b3161b9c"
---

## What it is

Health score is a composite metric that measures Python code quality across multiple structural dimensions. It combines seven weighted factors into a single 0–100 score on a normalized scale where higher is better: clones, complexity, cohesion, coupling, coverage, dead code, and dependency cycles.

Health score is a summary, not a replacement for looking at findings. A score drop tells you *that* something regressed; the underlying structural analysis findings tell you *what* and *where*.

## Why it exists

Seven separate metrics are hard to reason about together, and harder still to gate a CI pipeline on. Health score exists to answer one question cheaply: "did this change make the codebase's structure better or worse, overall?" — without requiring every reviewer to understand the interaction between complexity thresholds, coupling limits, and dead-code detection individually.

It should not be treated as an absolute target, because the weighting reflects CodeClone's defaults, not a universal notion of correctness. High health also does not imply functional correctness or security — it measures structural properties only, and is meant to sit alongside tests and security review, not replace them.

## How it fits together

| Dimension | Weight | Fed by |
|-----------|--------|--------|
| Clones | 25% | [Structural analysis](structural-analysis.md) clone detection |
| Complexity | 20% | Cyclomatic/cognitive complexity per function |
| Cohesion | 15% | Method dispersion within a class |
| Coupling | 10% | Fan-in/fan-out between modules |
| Coverage | 10% | Untested-hotspot detection |
| Dead code | 10% | Reachability analysis |
| Dependencies | 10% | Dependency-cycle detection |

```mermaid
graph LR
    A["Structural analysis findings"] --> B["Health score (0-100)"]
    B --> C["Reports and baselines"]
    B --> D["CI gate (--fail-health)"]
```

Health score is computed fresh on every run and stored as part of the [report](reports.md) for that run; comparing scores across runs only makes sense when both runs analyzed the same repository root.

## Related pages

- [Run the first analysis](../guides/first-analysis.md) — where the score appears in the report
- [Structural analysis](structural-analysis.md) — the seven underlying dimensions
- [CI integration](../guides/ci-integration.md) — gating a pipeline on health score
