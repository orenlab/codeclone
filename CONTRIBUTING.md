# Contributing to CodeClone

Thank you for your interest in contributing to **CodeClone**.

CodeClone is an **AST + CFG-based code clone detector** focused on architectural duplication,
not textual similarity.

Contributions are welcome — especially those that improve **signal quality**, **CFG semantics**,
and **real-world CI usability**.

---

## Project Philosophy

Core principles:

- **Low noise over high recall**
- **Structural and control-flow similarity**, not semantic equivalence
- **Deterministic and explainable behavior**
- Optimized for **CI usage** and architectural analysis

If a change increases false positives, reduces determinism, or weakens explainability,
it is unlikely to be accepted.

---

## Areas Open for Contribution

We especially welcome contributions in the following areas:

- Control Flow Graph (CFG) construction and semantics
- AST normalization improvements
- Segment-level clone detection and reporting
- False-positive reduction
- HTML report UX improvements
- Performance optimizations
- Documentation and real-world examples

---

## Reporting Bugs

Please use the appropriate **GitHub Issue Template**.

When reporting issues related to clone detection, include:

- minimal reproducible code snippets (preferred over screenshots);
- the CodeClone version;
- the Python version (`python_tag`, e.g. `cp313`);
- whether the issue is primarily:
    - AST-related,
    - CFG-related,
    - normalization-related,
    - reporting / UI-related.

Screenshots alone are usually insufficient for analysis.

---

## False Positives

False positives are **expected edge cases**, not necessarily bugs.

When reporting a false positive:

- explain **why the detected code is architecturally distinct**;
- avoid arguments based solely on naming, comments, or formatting;
- focus on **control-flow, responsibilities, or structural differences**.

Well-argued false-positive reports are valuable and appreciated.

---

## CFG Semantics Discussions

CFG behavior in CodeClone is intentionally conservative in the 1.x series.

If proposing changes to CFG semantics, include:

- a description of the current behavior;
- the proposed new behavior;
- the expected impact on clone detection quality (noise/recall);
- concrete code examples;
- a note on determinism implications.

Such changes often require design-level discussion and may be staged across versions.

---

## Security & Safety Expectations

- Assume **untrusted input** (paths and source code).
- Prefer **fail-closed in gating modes** and **fail-open in normal modes** only when explicitly intended.
- Add **negative tests** for any normalization/CFG change.
- Changes must preserve determinism and avoid introducing new false positives.

---

## Baseline & CI

### Baseline contract (v1)

- The baseline schema is versioned (`meta.schema_version`).
- Compatibility/trust gates include `schema_version`, `fingerprint_version`, `python_tag`,
  and `meta.generator.name`.
- Integrity is tamper-evident via `meta.payload_sha256` over canonical payload:
  `clones.functions`, `clones.blocks`, `meta.fingerprint_version`, `meta.python_tag`.
  (`created_at` and `meta.generator.version` are informational only.)

### When baseline regeneration is required

- Regenerate baseline with `codeclone . --update-baseline` **only when `fingerprint_version` changes**.
- Regeneration is **not** required for UI/report/CLI/cache/performance-only changes
  if `fingerprint_version` is unchanged.

### Gating behavior

- In `--ci` (or explicit gating flags), **untrusted baseline states fail fast** as a contract error (exit 2).
- Outside gating mode, an untrusted/missing baseline is ignored with a warning and comparison proceeds
  against an empty baseline.

### Exit codes contract

- **0** — success
- **2** — contract error (e.g., missing/untrusted baseline in gating, invalid output path/extension, incompatible
  versions)
- **3** — gating failure (new clones detected, `--fail-threshold` exceeded)
- **5** — internal error (unexpected exception; please report)

---

## Development Setup

```bash
git clone https://github.com/orenlab/codeclone.git
cd codeclone
uv sync --all-extras --dev
```

Run tests:

```bash
uv run pytest
```

Static checks:

```bash
uv run mypy .
uv run ruff check .
uv run ruff format .
```

---

## Code Style

- Python **3.10–3.14**
- Type annotations are required
- `Any` should be minimized; prefer precise types and small typed helpers
- `mypy` must pass
- `ruff check` must pass
- Code must be formatted with `ruff format`
- Prefer explicit, readable logic over clever or implicit constructs

---

## Versioning

CodeClone follows **semantic versioning**:

- **MAJOR**: fundamental detection model changes
- **MINOR**: new detection capabilities (e.g., new detectors or major CFG/normalization behavior shifts)
- **PATCH**: bug fixes, performance improvements, and UI/UX polish

Any change that affects detection behavior must include documentation and tests,
and may require a `fingerprint_version` bump (and thus baseline regeneration).

---

## License

By contributing to CodeClone, you agree that your contributions will be licensed
under the **MIT License**.
