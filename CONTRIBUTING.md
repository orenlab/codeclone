# Contributing to CodeClone

Thank you for your interest in contributing to **CodeClone** 🙌  
CodeClone is an **AST + CFG-based code clone detector** focused on architectural duplication, not textual similarity.

Contributions are welcome — especially those that improve **signal quality**, **CFG semantics**, and **real-world
usability**.

---

## 🧭 Project Philosophy

Before contributing, please understand the core principles:

- **Low noise over high recall**
- **Structural and control-flow similarity**, not semantic equivalence
- **Deterministic and explainable behavior**
- Optimized for **CI usage and architectural analysis**

If a change increases false positives or reduces explainability, it is unlikely to be accepted.

---

## 🧩 Areas Open for Contribution

We especially welcome contributions in:

- CFG construction and semantics
- AST normalization improvements
- False-positive reduction
- HTML report UX improvements
- Performance optimizations
- Documentation and examples

---

## 🐞 Reporting Bugs

Please use the appropriate **GitHub Issue Template**.

When reporting bugs related to clone detection:

- provide **minimal reproducible code snippets**
- specify whether the issue is:
    - AST-related
    - CFG-related
    - reporting/UI-related

Screenshots alone are usually insufficient.

---

## ⚠️ False Positives

False positives are **expected edge cases**, not failures.

If reporting a false positive:

- explain **why the detected code is architecturally distinct**
- avoid arguments based solely on naming or comments
- focus on **control-flow or responsibility differences**

---

## 🧠 CFG Semantics Discussions

CFG behavior is intentionally conservative in v1.x.

If proposing CFG changes:

- describe current behavior
- describe desired behavior
- explain impact on clone detection quality
- include code examples

These discussions often require design-level decisions and may be staged across versions.

---

## 🧪 Development Setup

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
mypy codeclone
```

---

## 🧹 Code Style

- Python 3.10+
- Type annotations are required
- `mypy --strict` must pass
- Prefer explicit logic over cleverness

---

## 📦 Versioning

CodeClone follows **semantic versioning**:

- `MAJOR`: fundamental detection model changes
- `MINOR`: new detection capabilities (e.g. CFG improvements)
- `PATCH`: bug fixes and UI improvements

---

## 📜 License

By contributing, you agree that your contributions will be licensed under the **MIT License**.

Thank you for helping improve CodeClone ❤️
