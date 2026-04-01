# Contributing to CodeClone

Thank you for your interest in contributing to **CodeClone**.

CodeClone provides **structural code quality analysis** for Python, including clone detection,
quality metrics, baseline-aware CI governance, and an optional MCP agent interface.

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
- Quality metrics (complexity, coupling, cohesion, dead-code, dependencies)
- False-positive reduction
- HTML report UX improvements
- MCP server tools and agent workflows
- GitHub Action improvements
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
    - metrics-related,
    - MCP-related,
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

### Baseline contract (v2)

- The baseline schema is versioned (`meta.schema_version`, currently `2.0`).
- Compatibility/trust gates include `schema_version`, `fingerprint_version`, `python_tag`,
  and `meta.generator.name`.
- Integrity is tamper-evident via `meta.payload_sha256` over canonical payload.
- The baseline may embed a `metrics` section for metrics-baseline-aware CI gating.

### When baseline regeneration is required

- Regenerate baseline with `codeclone . --update-baseline` when
  `fingerprint_version` **or** `python_tag` changes.
- Regeneration is **not** required for UI/report/CLI/cache/performance-only changes
  if both `fingerprint_version` and `python_tag` are unchanged.

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

## Versioned schemas

CodeClone maintains several versioned schema contracts:

| Schema           | Current version | Owner                               |
|------------------|-----------------|-------------------------------------|
| Baseline         | `2.0`           | `codeclone/baseline.py`             |
| Report           | `2.1`           | `codeclone/report/json_contract.py` |
| Cache            | `2.2`           | `codeclone/cache.py`                |
| Metrics baseline | `1.0`           | `codeclone/metrics_baseline.py`     |

Any change to schema shape or semantics requires version review, documentation, and tests.

---

## MCP Interface

CodeClone includes an optional **read-only MCP server** (`codeclone[mcp]`) for AI agents.

When contributing to MCP:

- MCP must remain **read-only** — it must never mutate baselines, source files, or repo state.
- Session-local review markers are the only allowed mutable state (in-memory, ephemeral).
- MCP reuses pipeline/report contracts — do not create a second analysis truth path.
- Tool names, resource URIs, and response shapes are public surfaces — changes require tests and docs.

See `docs/mcp.md` and `docs/book/20-mcp-interface.md` for details.

---

## GitHub Action

CodeClone ships a composite GitHub Action (`.github/actions/codeclone/`).

When contributing to the Action:

- Never inline `${{ inputs.* }}` in shell scripts — pass through `env:` variables.
- Prefer major-tag pinning for actions (e.g., `actions/setup-python@v5`).
- Add timeouts to all `subprocess.run` calls.

---

## Development Setup

```bash
git clone https://github.com/orenlab/codeclone.git
cd codeclone
uv sync --all-extras --dev
uv run pre-commit install
```

Run tests:

```bash
uv run pytest
```

Static checks:

```bash
uv run pre-commit run --all-files
```

Build documentation (if you touched `docs/` or `mkdocs.yml`):

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict
```

Run MCP tests (if you touched `mcp_service.py` or `mcp_server.py`):

```bash
uv run pytest -q tests/test_mcp_service.py tests/test_mcp_server.py
```

---

## Code Style

- Python **3.10 – 3.14**
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

By contributing code to CodeClone, you agree that your contributions will be
licensed under **MPL-2.0**.

Documentation contributions are licensed under **MIT**.
