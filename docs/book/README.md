# CodeClone Contracts Book

This book is the contract-level documentation for CodeClone v1.x.

All guarantees here are derived from code and locked tests.
If a statement is not enforced by code/tests, it is explicitly marked as non-contractual.

## How to read

- Start with **Intro → Architecture map → Terminology**.
- Then read the **contract spine**: Exit codes → Core pipeline → Baseline → Cache → Report.
- Everything else is supporting detail, invariants, and reference.

## Table of Contents

- [00-intro.md](00-intro.md)
- [01-architecture-map.md](01-architecture-map.md)
- [02-terminology.md](02-terminology.md)

### Contracts spine

- [03-contracts-exit-codes.md](03-contracts-exit-codes.md)
- [04-config-and-defaults.md](04-config-and-defaults.md)
- [05-core-pipeline.md](05-core-pipeline.md)
- [06-baseline.md](06-baseline.md)
- [07-cache.md](07-cache.md)
- [08-report.md](08-report.md)

### Interfaces

- [09-cli.md](09-cli.md)
- [10-html-render.md](10-html-render.md)

### System properties

- [11-security-model.md](11-security-model.md)
- [12-determinism.md](12-determinism.md)
- [13-testing-as-spec.md](13-testing-as-spec.md)
- [14-compatibility-and-versioning.md](14-compatibility-and-versioning.md)

### Appendix

- [appendix/a-status-enums.md](appendix/a-status-enums.md)
- [appendix/b-schema-layouts.md](appendix/b-schema-layouts.md)
- [appendix/c-error-catalog.md](appendix/c-error-catalog.md)