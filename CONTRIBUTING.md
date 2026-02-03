# Contributing to CodeClone

Thank you for your interest in contributing to **CodeClone**.

CodeClone is an **AST + CFG-based code clone detector** focused on architectural duplication,
not textual similarity.

Contributions are welcome — especially those that improve **signal quality**, **CFG semantics**,
and **real-world usability**.

---

## Project Philosophy

Before contributing, please understand the core principles of the project:

- **Low noise over high recall**
- **Structural and control-flow similarity**, not semantic equivalence
- **Deterministic and explainable behavior**
- Optimized for **CI usage and architectural analysis**

If a change increases false positives or reduces explainability,
it is unlikely to be accepted.

---

## Areas Open for Contribution

We especially welcome contributions in the following areas:

- Control Flow Graph (CFG) construction and semantics
- AST normalization improvements
- False-positive reduction
- HTML report UX improvements
- Performance optimizations
- Documentation and real-world examples

---

## Reporting Bugs

Please use the appropriate **GitHub Issue Template**.

When reporting bugs related to clone detection, include:

- minimal reproducible code snippets;
- the Python version used;
- whether the issue is primarily:
  - AST-related,
  - CFG-related,
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

If proposing changes to CFG semantics, please include:

- a description of the current behavior;
- the proposed new behavior;
- the expected impact on clone detection quality;
- concrete code examples.

Such changes often require design-level discussion and may be staged across versions.

---

## Development Setup

```bash
git clone https://github.com/orenlab/codeclone.git
cd codeclone
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Run tests:

```bash
pytest
```

Static checks:

```bash
mypy
ruff check .
ruff format .
```

---

## Code Style

- Python 3.10+
- Type annotations are required
- `mypy` must pass
- `ruff check` must pass
- Code must be formatted with `ruff format`
- Prefer explicit, readable logic over clever or implicit constructs

---

## Versioning

CodeClone follows **semantic versioning**:

- **MAJOR**: fundamental detection model changes
- **MINOR**: new detection capabilities (for example, CFG improvements)
- **PATCH**: bug fixes, performance improvements, and UI/UX polish

---

## License

By contributing to CodeClone, you agree that your contributions will be licensed
under the **MIT License**.
