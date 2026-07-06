# CodeClone review rubric — v2

## Always-on review vectors

Every unit must assess runtime correctness, behavior preservation, error surfacing, test
adequacy, scope honesty, contract consistency, determinism, and the proof triad below.

## Test proof triad

A changed critical behavior is not adequately tested unless evidence addresses all
applicable categories:

### Contract proof

Does the promised behavior work through the real public/domain path with representative
runtime values rather than only simplified mocks?

### Invariant proof

Are required properties preserved: identity, ordering, dimensions, determinism, round-trip,
read/write symmetry, idempotency, scope, atomicity, and stable output types?

### Failure proof

Do invalid, legacy, partial, unknown, malformed, and third-party values fail or degrade via
the intended domain error and recovery surface, without accidental exceptions or silent loss?

Coverage percentage alone does not satisfy this rubric.

## Conditional vectors

Activate vectors based on behavior and packet `surface_hints`, not filenames alone:

- engine core / analysis / findings / metrics: fingerprint stability, clone identity,
  baseline novelty semantics, determinism;
- persisted data: legacy records, migrations, repair, read/write symmetry, rollback/restart;
- public CLI/MCP/API and client integrations: inputs, outputs, exit/error contracts,
  machine-output isolation, launcher fidelity;
- typing/model narrowing: runtime domain, coercion, unknown values, third-party scalar/container types;
- cache/identity/digest: invalidation, canonicalization, backward compatibility, versioning;
- filesystem mutation: symlinks, traversal, stale plans, atomicity, partial failure;
- concurrency: races, cancellation, cleanup, replay, ownership;
- dependencies/packaging: added/upgraded packages, optional extras, installability, lock consistency;
- integration distribution: storefront layout parity, manifest provenance, client contract drift;
- performance: amplification, boundedness, allocation, repeated I/O.

### Docs transitional policy

When `packet.docs_review.enabled` is `false`, do not treat `docs/**` or stray `.md` files as
mandatory review surfaces. Record them as `not_applicable` unless the caller explicitly
re-enabled docs review for a docs-only audit.

### Review orchestration surfaces

Changes under `.claude/review/**` and the review coordinator agents/skills route through the
`review_orchestration` surface. Treat packet builder, policy routing, shell launcher, schema,
and rubric as contract-sensitive review infrastructure — not disposable helper scripts.

## Severity

- P0: destructive, security-critical, unrecoverable corruption, or release-invalidating contract break.
- P1: shipped critical capability broken, silent broad regression, persisted/public incompatibility.
- P2: material defect with bounded impact or clear workaround; normally blocks affected release scope.
- P3: advisory, maintainability, or missing non-critical proof; non-blocking unless policy says otherwise.

## Evidence quality

Strong evidence combines code-path inspection with runtime or fixture proof. Green typing proves
static consistency, not runtime compatibility. Green tests prove only the exercised scenarios.
Mocks must reproduce the relevant shape and types of the real dependency.

## Candidate ledger discipline

Every investigated concern ends as finding, dismissed_with_evidence, needs_more_evidence, or
not_applicable. A reviewer must state why. Missing confidence is not permission to omit.

## Decomposition quality

A review unit must be independently understandable and bounded by one coherent behavior or
contract owner from `policy.yaml` `contract_owners`. Avoid arbitrary chunks by file count.
Record overlaps and cross-surface edges. A critical surface that is merely sampled blocks an
aggregate CLEAN verdict.

## Unmapped paths

If `packet.change.unmapped_paths` is non-empty, the aggregate verdict cannot be `CLEAN`.
Either expand the review tree to cover those paths or record explicit `needs_more_evidence`
release-risk candidates with the exact paths listed.
