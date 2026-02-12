# AGENTS.md — CodeClone (AI Agent Playbook)

This document is the **source of truth** for how AI agents should work in this repository.
It is optimized for **determinism**, **CI stability**, and **reproducible changes**.

> Repository goal: maximize **honesty**, **reproducibility**, **determinism**, and **precision** for real‑world CI usage.

---

## 1) Operating principles (non‑negotiable)

1. **Do not break CI contracts.**
   - Treat baseline, cache, and report formats as **public APIs**.
   - Any contract change must be **versioned**, documented, and accompanied by tests.

2. **Determinism > cleverness.**
   - Outputs must be stable across runs given identical inputs (same repo, tool version, python tag).

3. **Evidence-based explainability.**
   - The core engine produces **facts/metrics**.
   - HTML/UI **renders facts**, it must not invent interpretations.

4. **Safety first.**
   - Never delete or overwrite user files outside repo.
   - Any write must be atomic where relevant (e.g., baseline `.tmp` + `os.replace`).

---

## 2) Quick orientation

CodeClone is an AST/CFG-informed clone detector for Python. It supports:
- **function clones** (strongest signal)
- **block clones** (sliding window of statements, may be noisy on boilerplate)
- **segment clones** (report-only unless explicitly gated)

Key artifacts:
- `codeclone.baseline.json` — trusted baseline snapshot (for CI comparisons)
- `.cache/codeclone/cache.json` — analysis cache (integrity-checked)
- `.cache/codeclone/report.html|report.json|report.txt` — reports

---

## 3) One command to validate your change

Run these locally before proposing changes:

```bash
uv run ruff check .
uv run mypy .
uv run pytest -q
```

If you touched baseline/cache/report contracts, also run the repo’s audit runner (or the scenario script if present).

---

## 4) Baseline contract (v1, stable)

### Baseline file structure (canonical)

```json
{
  "meta": {
    "generator": { "name": "codeclone", "version": "X.Y.Z" },
    "schema_version": "1.0",
    "fingerprint_version": "1",
    "python_tag": "cp313",
    "created_at": "2026-02-08T14:20:15Z",
    "payload_sha256": "…"
  },
  "clones": {
    "functions": [],
    "blocks": []
  }
}
```

### Rules

- `schema_version` is **baseline schema**, not package version.
- Compatibility is tied to:
  - `fingerprint_version`
  - `python_tag`
  - `generator.name == "codeclone"`
- `payload_sha256` is computed from a **canonical payload**:
  - stable key order
  - clone id lists are **sorted and unique**
  - integrity check uses constant‑time compare (e.g., `hmac.compare_digest`)

### Trust model

- A baseline is either **trusted** (`baseline_status = ok`) or **untrusted**.
- **Normal mode**:
  - warn
  - ignore untrusted baseline
  - compare vs empty baseline
- **CI gating mode** (`--ci` / `--fail-on-new`):
  - fail‑fast if baseline untrusted
  - exit code **2** for untrusted baseline

### Legacy behavior

- Legacy baselines (<= 1.3.x layout) must be treated as **untrusted** with explicit messaging and tests.

---

## 5) Cache contract (integrity + size guards)

- Cache is an **optimization**, never a source of truth.
- If cache is invalid or too large:
  - warn
  - proceed without cache
  - ensure report meta reflects `cache_used=false`

Never “fix” cache by silently mutating it; prefer regenerate.

---

## 6) Reports and explainability

Reports come in:
- HTML (`--html`)
- JSON (`--json`)
- Text (`--text`)

### Report invariants

- Ordering must be deterministic (stable sort keys).
- All provenance fields must be consistent across formats:
  - baseline loaded / status
  - baseline fingerprint + schema versions
  - baseline generator version
  - cache path / cache used

### Explainability contract (core owns facts)

For each clone group (especially block clones), the **core** should be able to provide factual fields such as:

- `match_rule`
- `signature_kind`
- `window_size` (block size) / `segment_size`
- `merged_regions` flag and counts
- `stmt_type_sequence` (normalized)
- `stmt_type_histogram`
- `has_control_flow` (if/for/while/try/match)
- ratios (assert / assign / call)
- `max_consecutive_<type>` (e.g., consecutive asserts)

UI can show **hints** only when the predicate is **formal & exact** (100% confidence), e.g.:
- `assert_only_block` (assert_ratio == 1.0 and consecutive_asserts == block_len)
- `repeated_stmt_hash` (single stmt hash repeated across window)

No UI-only heuristics that affect gating.

---

## 7) Noise policy (what is and isn’t a “fix”)

### Acceptable fixes
- Merge/report-layer improvements (e.g., merge sliding windows into maximal regions) **without changing gating**.
- Better evidence surfaced in HTML to explain matches.

### Not acceptable as a “quick fix”
- Weakening detection rules to hide noisy test patterns, unless:
  - it is configurable
  - default remains honest
  - the change is justified by real-world repos
  - it includes tests for false-negative risk

### Preferred remediation for test-only FPs
- Refactor tests to avoid long repetitive statement sequences:
  - replace chains of `assert "... in html"` with loops or aggregated checks.

---

## 8) How to propose changes (agent workflow)

When you implement something:

1. **State the intent** (what user-visible issue does it solve?)
2. **List files touched** and why.
3. **Call out contracts affected**:
   - baseline / cache / report schema
   - CLI exit codes / messages
4. **Add/adjust tests** for:
   - normal-mode behavior
   - CI gating behavior
   - determinism (identical output on rerun)
   - legacy/untrusted scenarios where applicable
5. Run:
   - `ruff`, `mypy`, `pytest`

Avoid changing unrelated files (locks, roadmap) unless required.

---

## 9) CLI behavior and exit codes

Agents must preserve these semantics:

- **0** — success (including “new clones detected” in non-gating mode)
- **2** — baseline gating failure (untrusted/missing baseline when CI requires trusted baseline; invalid output extension, etc.)
- **3** — analysis gating failure (e.g., `--fail-threshold` exceeded or new clones in `--ci` as designed)

If you introduce a new exit reason, document it and add tests.

---

## 10) Release hygiene (for agent-assisted releases)

Before cutting a release:

- Confirm baseline schema compatibility is unchanged, or properly versioned.
- Ensure changelog has:
  - user-facing changes
  - migration notes if any
- Validate `twine check dist/*` for built artifacts.
- Smoke test install in a clean venv:
  - `pip install dist/*.whl`
  - `codeclone --version`
  - `codeclone . --ci` in a sample repo with baseline.

---

## 11) “Don’t do this” list

- Don’t add hidden behavior differences between report formats.
- Don’t make baseline compatibility depend on package patch/minor version.
- Don’t add project-root hashes or unstable machine-local fields to baseline.
- Don’t embed suppressions into baseline unless explicitly designed as a versioned contract.
- Don’t introduce nondeterministic ordering (dict iteration, set ordering, filesystem traversal without sort).

---

## 12) Where to put new code

## 13) Python language + typing rules (3.10 → 3.14)

These rules are **repo policy**. If you need to violate one, you must explain why in the PR.

### Supported Python versions
- **Must run on Python 3.10, 3.11, 3.12, 3.13, 3.14**.
- Do not rely on behavior that is new to only the latest version unless you provide a fallback.
- Prefer **standard library** features that exist in 3.10+.

### Modern syntax (allowed / preferred)
Use modern syntax when it stays compatible with 3.10+:
- `X | Y` unions, `list[str]` / `dict[str, int]` generics (PEP 604 / PEP 585)
- `from __future__ import annotations` is allowed, but keep behavior consistent across 3.10–3.14.
- `match/case` (PEP 634) is allowed, but only if it keeps determinism/readability.
- `typing.Self` (3.11+) **avoid** in public APIs unless you gate it with `typing_extensions`.
- Prefer `pathlib.Path` over `os.path` for new code (but keep hot paths pragmatic).

### Typing standards
- **Type hints are required** for all public functions, core pipeline surfaces, and any code that touches:
  baseline, cache, fingerprints, report models, serialization, CLI exit behavior.
- Keep **`Any` to an absolute minimum**:
  - `Any` is allowed only at IO boundaries (JSON parsing, `argparse`, `subprocess`) and must be
    *narrowed immediately* into typed structures (dataclasses / TypedDict / Protocol / enums).
  - If `Any` appears in “core/domain” code, add a comment: `# Any: <reason>` and a TODO to remove.
- Prefer **`Literal` / enums** for finite sets (e.g., status codes, kinds).
- Prefer **`dataclasses`** (frozen where reasonable) for data models; keep models JSON‑serializable.
- Use `collections.abc` types (`Iterable`, `Sequence`, `Mapping`) for inputs where appropriate.
- Avoid `cast()` unless you also add an invariant check nearby.

### Dataclasses / models
- Models that cross module boundaries should be:
  - explicitly typed
  - immutable when possible (`frozen=True`)
  - validated at construction (or via a dedicated `validate_*` function) if they are user‑provided.

### Error handling
- Prefer explicit, typed error types over stringly‑typed errors.
- Exit codes are part of the public contract; do not change them without updating tests + docs.

### Determinism requirements (language-level)
- Never iterate over unordered containers (`set`, `dict`) without sorting first when it affects:
  hashes, IDs, report ordering, baseline payloads, or UI output.
- Use stable formatting (sorted keys, stable ordering) in JSON output.

### Key PEPs to keep in mind
- PEP 8, PEP 484 (typing), PEP 526 (variable annotations)
- PEP 563 / PEP 649 (annotation evaluation changes across versions) — avoid relying on evaluation timing
- PEP 585 (built-in generics), PEP 604 (X | Y unions)
- PEP 634 (structural pattern matching)
- PEP 612 (ParamSpec) / PEP 646 (TypeVarTuple) — only if it clearly helps, don’t overcomplicate



Prefer these rules:

- **Domain / contracts / enums** live near the domain owner (baseline statuses in baseline domain).
- **Core logic** should not depend on HTML.
- **Render** depends on report model, never the other way around.
- If a module becomes a “god module”, split by:
  - model (types)
  - io/serialization
  - rules/validation
  - ui rendering

Avoid deep package hierarchies unless they clearly reduce coupling.

---

## 14) Minimal checklist for PRs (agents)

- [ ] Change is deterministic.
- [ ] Contracts preserved or versioned.
- [ ] Tests added for new behavior.
- [ ] `ruff`, `mypy`, `pytest` green.
- [ ] CLI messages remain helpful and stable (don’t break scripts).
- [ ] Reports contain provenance fields and reflect trust model correctly.

---

If you are an AI agent and something here conflicts with an instruction from a maintainer in the PR/issue thread, **ask for clarification in the thread** and default to this document until resolved.
