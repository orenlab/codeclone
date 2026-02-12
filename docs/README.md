# CodeClone Docs

This directory has two documentation layers.

- [`docs/book/`](book/): **contract-first** documentation. This is the canonical source for **schemas**, **statuses**, *
  *exit codes**, **trust model**, and **determinism guarantees**. Everything here is derived from code + locked tests.
- [`docs/architecture.md`](architecture.md), [`docs/cfg.md`](cfg.md): **deep-dive narrative** docs (architecture and CFG
  semantics). These may include rationale and design intent, but must not contradict the contract book.

## Start Here

- Contracts and guarantees: [`docs/book/00-intro.md`](book/00-intro.md)
- Architecture map (components + ownership): [`docs/book/01-architecture-map.md`](book/01-architecture-map.md)
- Terminology: [`docs/book/02-terminology.md`](book/02-terminology.md)

## Core Contracts

- Exit codes and failure policy: [`docs/book/03-contracts-exit-codes.md`](book/03-contracts-exit-codes.md)
- Config and defaults: [`docs/book/04-config-and-defaults.md`](book/04-config-and-defaults.md)
- Core pipeline and invariants: [`docs/book/05-core-pipeline.md`](book/05-core-pipeline.md)
- Baseline contract (schema v1): [`docs/book/06-baseline.md`](book/06-baseline.md)
- Cache contract (schema v1.2): [`docs/book/07-cache.md`](book/07-cache.md)
- Report contract (schema v1.1): [`docs/book/08-report.md`](book/08-report.md)

## Interfaces

- CLI behavior, modes, and UX: [`docs/book/09-cli.md`](book/09-cli.md)
- HTML report rendering contract: [`docs/book/10-html-render.md`](book/10-html-render.md)

## System Properties

- Security model and threat boundaries: [`docs/book/11-security-model.md`](book/11-security-model.md)
- Determinism policy: [`docs/book/12-determinism.md`](book/12-determinism.md)
- Tests as specification: [`docs/book/13-testing-as-spec.md`](book/13-testing-as-spec.md)
- Compatibility and versioning rules: [
  `docs/book/14-compatibility-and-versioning.md`](book/14-compatibility-and-versioning.md)

## Deep Dives

- Architecture narrative: [`docs/architecture.md`](architecture.md)
- CFG design and semantics: [`docs/cfg.md`](cfg.md)

## Reference Appendices

- Status enums and typed contracts: [`docs/book/appendix/a-status-enums.md`](book/appendix/a-status-enums.md)
- Schema layouts (baseline/cache/report): [`docs/book/appendix/b-schema-layouts.md`](book/appendix/b-schema-layouts.md)
- Error catalog (contract vs internal): [`docs/book/appendix/c-error-catalog.md`](book/appendix/c-error-catalog.md)