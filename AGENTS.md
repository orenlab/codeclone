# AGENTS.md — CodeClone (AI Agent Playbook)

**Audience: autonomous agents.**

## Authority model of this document

**AUTH1 — Normativity is confined to owning rule blocks.**

Every obligation in this document belongs to exactly one **owning rule block**, identified by
a stable id (`P1`, `E3`, `W5`, `AP4`, …). A rule id MAY own a multi-sentence block.

1. **Only text inside an identified owning rule block is normative.** Text outside such a
   block — headers, routing tables, checklists, notes, prose — is **non-normative** and MUST
   NOT be relied on as a source of obligation.
2. **Every normative obligation MUST be expressed with RFC-2119 uppercase modality**
   (**MUST**, **MUST NOT**, **MAY**). An imperative without that modality is not an
   obligation, regardless of tone.
   **SHOULD** and **SHOULD NOT** are recognised, and they are **non-normative**: they mark a
   preference this project holds, they never constitute an obligation, and an agent MUST NOT
   treat them as one. A block whose only modality is SHOULD therefore states no obligation and
   is reported as such — that report is correct, and an agent MUST NOT resolve it by promoting
   the preference to MUST, which would silently widen what agents are bound by. Give the block
   its real obligation, or move the preference into a block that already carries one.
3. A summary MUST NOT state an obligation its owner does not contain. Where a summary and its
   owner disagree, an agent MUST follow the owner **and MUST report the divergence as a defect
   in this document** — silently following either side reproduces, inside our own governance,
   the defect class this project exists to catch (`G2`).
4. Agents MUST cite rule ids in briefs, reports, and reviews.

**AUTH2 — Mechanical conformance (required, not yet implemented).** `AUTH1` MUST be enforced by
a policy lint over this file. The lint MUST red on: an RFC-2119 uppercase modal outside an
owning block · one id owning two disjoint blocks · an owning block containing no modal · a
rule id cited anywhere in the file that no block defines.

*Current epistemic status of `AUTH1`, stated under `I5` discipline:* owning blocks have been
assigned by hand across every section containing modals. **The single-owner property is
therefore claimed manually and is rebuttable, not mechanically proven.** Until the lint exists,
an agent MUST NOT cite `AUTH1` as an established property of this file — only as its declared
intent. Building that lint is a nameable task, not an assumption.

**AUTH3 — Source precedence and conflict resolution.**

Code is the source of truth for implementation. Where this document and the code diverge, an
agent MUST follow the code and MUST report the divergence.

Where this document conflicts with a maintainer instruction in a pull request or issue thread,
an agent MUST ask for clarification in that thread and MUST default to this document until the
conflict is resolved.

Published contract pages are **TBD** during the docs migration. An agent verifying a claim MUST
prefer, in order: code · tests · `CHANGELOG.md` · `README.md` · surface-local READMEs and
skills. An agent MUST NOT cite removed documentation paths.

---

**CodeClone** is a deterministic **Structural Change Controller** for AI-assisted Python
development. It starts before a diff exists: an agent declares intent, CodeClone maps the
structural blast radius, bounds the edit, verifies the patch against one canonical report, and
leaves an auditable receipt.

> Goal: make AI-assisted structural change **explicit**, **bounded**, **remembered**, and
> **verifiable**, without turning model output into truth.

---

## 0) Start here

*Non-normative routing (`AUTH1.1`). Every obligation cited lives in its owner.*

### 0.1 Before any repository edit

```
analyze  →  declare intent + scope  →  read memory  →  EDIT  →  analyze  →  verify  →  receipt
                    │                                                          │
            edit_allowed == true                              accepted · scope reconciled
            is the ONLY permission                            · receipt · intent cleared
```

Pre-edit authorization and completion are owned by **`P7`**. Read it before your first edit.

### 0.2 The acceptance laws

| Law                   | One line                                                                                              | Owner     |
|-----------------------|-------------------------------------------------------------------------------------------------------|-----------|
| **Evidence**          | A green test proves nothing; only a kill on a semantic witness does.                                  | `E1`–`E8` |
| **Inventory**         | Completeness is relative to two declared analysis contracts; claims are bounded by the stage reached. | `I1`–`I7` |
| **Change acceptance** | Empirical calibration, normative policy, and correctness are three different paths.                   | `S1`–`S6` |

### 0.3 Routing

| What you are doing                              | Read                                 |
|-------------------------------------------------|--------------------------------------|
| editing any repository file                     | `P7`, `RPT1`, §19                    |
| writing or changing tests                       | §17                                  |
| touching baseline, cache, or report shape       | §4, `C1`, `MCP1`, `RP1`–`RP3`, `CR1` |
| touching MCP, CLI, or a client surface          | `ST1`, `SUR1`, `MCP1`, `CLI1`, `CR1` |
| changing a threshold, weight, band, or severity | `S1`–`S6`                            |
| reviewing, merging, or accepting work           | `AP1`–`AP8`, `A1`–`A9`               |
| implementing from a brief                       | `X1`–`X8`                            |
| auditing "all" of something                     | `I1`–`I7`, `AU1`–`AU3`               |
| recording something durable                     | `MEM1`–`MEM5`                        |

### 0.4 Definition of done

*Collects `P7`, `E5`, `E8`, `I5`, `X8`; defines nothing.*

---

## 1) Operating principles

**P1 — Public contracts MUST NOT break silently or without versioning.** Controller workflow
semantics, baseline, analysis cache, canonical report formats, Engineering Memory schemas and
governance, documented MCP payloads, and published client behavior are public APIs. A contract
change is permitted **only** when it is versioned, documented, and tested. An unversioned or
undocumented break is prohibited.

**P2 — Determinism, and the difference between results and identity.**

Identical canonical semantic inputs and versioned contract witnesses MUST produce
byte-identical semantic output. Volatile provenance — timestamps, durations, host and process
identifiers, run ordering artifacts, and any value that varies per execution — lies **outside**
semantic identity and MUST NOT affect canonical semantic bytes.

Two runs whose configuration, scope, contract activation, or comparison context differ are
**not** required to agree: their semantic inputs differ.

**Result equality is not identity equality.** Different semantic inputs **MAY** legitimately
produce identical semantic results — two different sources may each yield zero findings, and
nothing is wrong. The defect arises when an identity contract is **defined to distinguish**
those inputs and the identity input it consumes collapses them. Such inputs MUST NOT receive
the same identity (`G5`).

**P3 — Core owns facts; renderers present them.** No presentation-only heuristic MAY affect
gating. No renderer MAY display a value derived by logic that differs from the canonical
report.

**P4 — Filesystem safety.** An agent MUST NOT delete or overwrite files it does not own outside
the repository. It **MAY** create, write, and remove **its own** temporary artifacts — scratch
directories, detached worktrees required by `W1`, experiment copies — provided the agent created
them and no other party's data is inside. Writes that can be interrupted MUST be atomic.

**P5 — Golden tests are contract sentinels.** An agent MUST NOT refresh a snapshot to make a
test pass. A snapshot change requires an intentional, versioned, documented, approved contract
change.

**P6 — Fingerprint-adjacent work is never routine.** Performance work MUST NOT change AST
normalization, fingerprint inputs, or clone identity semantics while the fingerprint version is
unchanged. If a change can affect fingerprint bytes, clone identity, NEW-vs-KNOWN
classification, or baseline compatibility, it is a fingerprint contract change: version review
or bump, documentation, migration notes, explicit maintainer approval. Performance alone is
never sufficient justification.

**P7 — Pre-edit authorization and completion.**

An agent **MUST NOT** create, modify, or delete any tracked repository file until the controller
has returned `edit_allowed == true` for a declared intent and scope. This covers tests,
fixtures, documentation, CI configuration, and coverage work; task type never removes it.
Intent, scope, blast radius, do-not-touch boundaries, actual changed files, patch verification,
and the receipt are all part of the change contract, not post-hoc annotations.

An agent **MUST NOT** describe work as done, verified, or ready unless **all four** hold:

1. the controller returned an accepted status;
2. the declared scope reconciled with the files actually changed;
3. **the review receipt was produced and persisted** — where the accepted status already
   entails the receipt, this condition is satisfied by it, and the agent MUST NOT treat the
   receipt as optional on that basis;
4. the intent was cleared.

Leaving an active or recoverable intent behind is blocked cleanup, not completion. Where the
change-control surface is unavailable and the task requires it, the agent MUST stop and report
the blocker.

**P8 — Agent-authored code requires human ownership.** A human MUST inspect and understand the
complete diff, verify tests, contracts, security, and provenance, and accept maintenance
responsibility. Agent review, receipts, and green CI are evidence, never approval. An agent MUST
NOT describe any of them as a substitute for substantive human review. Material agent assistance
MUST be disclosed in the pull request.

---

## 2) Orientation

| Artifact                                       | Role                                              |
|------------------------------------------------|---------------------------------------------------|
| `codeclone.baseline.json`                      | trusted comparison snapshot for baseline-aware CI |
| `.codeclone/cache.json`                        | integrity-checked optimization — never truth      |
| `.codeclone/report.{html,json,md,sarif,txt}`   | deterministic projections of the canonical report |
| `.codeclone/intents/` or a configured registry | workspace coordination state                      |
| `.codeclone/db/audit.sqlite3`                  | optional passive controller evidence              |
| `.codeclone/memory/engineering_memory.sqlite3` | governed Engineering Memory                       |
| `.codeclone/memory/semantic_index.lance`       | optional semantic sidecar                         |
| `.codeclone/db/platform_observability.sqlite3` | opt-in local diagnostics for CodeClone itself     |

**ST1 — Two kinds of ephemeral state, never conflated.**

*Session-local state* is analysis runs held in memory and review markers: it exists inside one
server process and is never persisted. *Workspace coordination state* is the intent registry:
persisted, visible across processes, lease- and TTL-bound, and advisory coordination only.

Neither kind MAY leak into baseline, cache, or report artifacts. Neither MAY affect canonical
report digests, baseline admissibility, cache compatibility, or finding identity.

**SUR1 — One rule for every client surface.** IDE extensions, desktop bundles, editor plugins,
and CI actions are discovery, guidance, or view layers over the MCP server or the CLI contracts.
Each MUST NOT introduce a second analyzer, a second server, or a second truth path. The setup
CLI additionally MUST NOT declare intent, MUST NOT return `edit_allowed`, and MUST NOT write
baselines, cache, or canonical reports.

---

## 3) Validation stages

**V1 — Gate execution.**

```bash
uv run pre-commit run --all-files                        # hygiene, lint, types, baseline-aware CI run, docs fixer
uv run pre-commit run --hook-stage pre-push --all-files  # NOT run by the command above
uv run pytest -q --cov=codeclone --cov-report=term-missing --cov-fail-under=99
```

Hooks MAY rewrite files; an agent MUST re-inspect the diff afterward. An agent **MUST NOT** use
`--no-verify` or otherwise bypass a failing hook — the underlying issue MUST be fixed. Every gate
result MUST be reported with its exit code (`E5`). One red gate is a blocker (`W9`).

An agent MUST additionally **run** the surface-specific commands below when the corresponding
files were touched. This obligation is to *run* them; whether tests must also be *added or
changed* is owned by `CR1`.

| IF you touched                                                         | THEN also run                                                                                                                               |
|------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| baseline, cache, or report contracts; CLI/MCP audit surfaces           | the CLI audit path or the audit/MCP tests                                                                                                   |
| setup readiness CLI                                                    | `pytest -q tests/test_cli_setup.py tests/test_pyproject_writer.py`                                                                          |
| MCP surface                                                            | `pytest -q tests/test_mcp_service.py tests/test_mcp_server.py`                                                                              |
| memory, semantic retrieval, trajectories, experiences, projection jobs | nearest owning modules plus `tests/test_memory_*.py`, `tests/test_semantic_*.py`, MCP memory contract tests                                 |
| Platform Observability                                                 | `pytest -q tests/test_observability_*.py`                                                                                                   |
| Corpus Analytics                                                       | `pytest -q tests/test_analytics_*.py tests/test_config_analytics.py`                                                                        |
| CI action helpers                                                      | `pytest -q tests/test_github_action_helpers.py`                                                                                             |
| integration sync or distribution overlays                              | `pytest -q tests/test_sync_integrations.py` (dry-run first)                                                                                 |
| a plugin surface                                                       | that plugin's manifest JSON validation plus its plugin tests                                                                                |
| a Node-based extension or bundle                                       | `node --check` on each changed script, `node --test` on its test directory, plus the package or build smoke when packaging metadata changed |
| docs site or sample-report generation                                  | the documentation build in strict mode                                                                                                      |

---

## 4) Baseline contract (v3)

**B1 — Version constants are read from code.** Cross-surface constants live in
`codeclone/contracts/__init__.py`; subsystem-local wire versions live with their owning modules.
An agent MUST read every version value from code and MUST NOT copy one from any document,
including this one — a copied version number is an unexecuted claim that rots.

**B2 — Container shape.** The current schema is a lane container. An agent MUST NOT
reintroduce the flat pre-v3 top-level layout:

```json
{
  "format": "codeclone-baseline",
  "baseline_scope_id": "…",
  "meta": {
    "container_version": "…",
    "generator": {
      "name": "codeclone",
      "version": "…"
    },
    "python_tag": "…",
    "created_at": "…",
    "project_label": "…",
    "root_digest": {
      "domain": "…",
      "algorithm": "sha256",
      "value": "…"
    }
  },
  "contracts": {
    "…": "required contract versions sampled at write time"
  },
  "lanes": {
    "<lane name>": {
      "descriptor": {
        "name": "…",
        "payload_schema": "…",
        "algorithm_revision": "…",
        "required_contracts": []
      },
      "digest": {
        "domain": "…",
        "algorithm": "sha256",
        "value": "…"
      },
      "observation_digest": "…",
      "payload": "…",
      "required": false
    }
  },
  "observation_contract": {
    "enabled_lanes": [],
    "observation_digest_version": "…",
    "descriptors": []
  },
  "source": {
    "analysis_scope_digest": "…",
    "module_identity_manifest_digest": "…",
    "module_registry_digest": "…",
    "observation_digest": "…"
  },
  "transition": "one-shot epoch-transition evidence, when migrated"
}
```

`meta.container_version` is the baseline **schema** version, not the package version.

**B3 — Legacy path.** The only cross-version path is the one-shot legacy migration. It
authenticates the exact bytes of the prior artifact, records transition evidence, and imports
**no** lane data — every lane MUST be regenerated from the current run. Legacy bytes MUST be
preserved once as an immutable backup and MUST NOT be overwritten.

**B4 — Four separate concepts; never one word "trusted".** Collapsing these is how a surface
comes to publish confident answers about comparisons that never ran (`G3`). An agent MUST keep
them distinct in code, in payloads, and in prose.

| Level                                | Question                                                        | Binds                                                                |
|--------------------------------------|-----------------------------------------------------------------|----------------------------------------------------------------------|
| **Artifact admissibility**           | Is this artifact authentic and well-formed at all?              | schema version (exact) · format · integrity digests · generator name |
| **Comparison-context compatibility** | Is this artifact applicable to *this* run?                      | baseline scope id · python tag · global required contracts           |
| **Per-lane compatibility**           | Is *this lane* comparable under current contracts?              | lane required contracts · payload schema · algorithm revision        |
| **Comparison availability**          | Did a comparison actually run for *this family*, in *this run*? | executed comparison, per family                                      |

A valid, authentic artifact belonging to a different scope or python tag is **not
inadmissible**: it is admissible and **context-incompatible**. An agent MUST NOT report the
second as the first.

**B5 — Lane-level trust.** One incompatible lane MUST be reported unavailable and MUST NOT
condemn the whole container.

**B6 — Integrity.** Each lane carries a digest, the container carries a root digest over lane
digests, and comparisons MUST use constant-time equality.

**B7 — Novelty is baseline-relative, not patch-relative.** `novelty="known"` means a fingerprint
is accepted by the trusted baseline. It does **not** prove the current patch did not introduce or
reintroduce it. A patch-local regression claim MUST rest on clean before-run to after-run
evidence, never on a single run's novelty.

**B8 — Comparison availability is a published fact, not an inference.** A consumer MUST NOT
derive it from container presence, from lane compatibility, or from an empty difference set. **An
empty difference set with no comparison is not evidence of sameness.**

**B9 — Absence of a trusted comparison MUST be reported as comparison-unavailable.** It MUST NOT
be presented, digested, or classified as a completed comparison against an empty baseline. A
finding whose family had no comparison MUST NOT be classified `known`.

> *Non-normative note:* if the implementation performs a literal comparison against an empty
> baseline in non-gating mode, that is a code/document divergence to resolve deliberately.
> `AUTH3` governs what an agent does about it.

**B10 — Gating mode** MUST fail fast with the baseline gating exit code when the container is
inadmissible or context-incompatible, and the two cases MUST be distinguishable in the message.
Pre-v3 layouts are inadmissible, with explicit messaging and tests.

---

## 5) Cache contract

**C1** — Cache is an optimization, never truth. If it is invalid or oversized, an agent MUST
warn, MUST proceed without it, and MUST ensure report metadata reflects that the cache was
unused. An agent MUST NOT repair a cache by mutating it; regeneration is the only permitted
remedy.

---

## 6) Reports and explainability

**MCP1 — MCP boundary.** MCP MUST stay read-only with respect to repository source, baselines,
canonical and generated reports, and analysis cache. Bounded local state is permitted **only**
through its owning contract: session-local runs and review markers · workspace intent
coordination · optional audit evidence · governed memory drafts and projection metadata · opt-in
observability telemetry. None of these MAY alter canonical report identity, baseline
admissibility, cache compatibility, findings, gates, or edit authorization. MCP MUST NOT
re-synthesize design findings from raw metrics; it MUST read the canonical findings group.

**RP1 — Report invariants.** Ordering MUST be deterministic. Provenance MUST be consistent across
every format: baseline admissibility and context status, fingerprint and schema versions,
generator version, cache location and whether it was used — recorded as a **repository-relative
logical path**, never an absolute or machine-local one (`PR1`). SARIF line hashes MUST remain
stable across line-only shifts for the same finding identity.

A SARIF run automation identifier MUST be classified explicitly, and the classification MUST be
consistent across formats and releases:

- **either** it is derived deterministically from the run's semantic identity — in which case two
  runs with identical semantic inputs share it, and it MAY enter canonical semantic bytes;
- **or** it varies per execution — in which case it is **volatile provenance**, MUST be excluded
  from canonical semantic bytes, and MUST NOT affect any digest (`P2`).

An agent MUST NOT leave the classification implicit.

**RP2 — Absence MUST be distinguishable from emptiness.** A zero count that conflates "this lane
did not run" with "this lane ran and found nothing" is a forbidden third state: the consumer
cannot recover the difference and the digest will not move (`G4`, `B8`).

**RP3 — Explainability boundary.** The core supplies factual fields per clone group — match rule,
signature kind, window or segment size, merged-region flag and counts, normalized statement-type
sequence and histogram, control-flow presence, statement ratios, maximum consecutive counts. A
renderer MAY show a hint **only when the predicate is formal and exact**. No presentation-only
heuristic MAY affect gating (`P3`).

---

## 7) Noise policy

**N1** — An agent MUST NOT weaken detection to hide noisy patterns unless the weakening is
configurable, the default stays honest, it is justified against real-world repositories, and it
ships tests for false-negative risk. Merge- and report-layer improvements that do not change
gating, and better evidence surfaced to explain a match, are acceptable. For test-only false
positives an agent SHOULD refactor the tests to avoid long repetitive statement sequences rather
than weaken detection.

---

## 8) Reporting a change

**RPT1** — Around the controlled-change workflow (`P7`), an agent MUST report: the intent and the
user-visible problem it solves · allowed files, related context, forbidden paths · blast radius
and boundaries as inspected · the files actually touched and why each · contracts affected · tests
added or adjusted per `CR1` · every gate with its exit code (`E5`) · the **verification matrix**
when `E8` applies · **what was not done** (`X8`). An agent MUST NOT touch unrelated files unless
required.

---

## 9) CLI behavior and exit codes

**CLI1** — These semantics MUST be preserved.

| Code | Meaning                                                                                                     |
|------|-------------------------------------------------------------------------------------------------------------|
| 0    | success, including new findings in non-gating mode                                                          |
| 2    | baseline gating failure — inadmissible or context-incompatible container under CI, invalid output extension |
| 3    | analysis gating failure — threshold exceeded, or new findings under CI as designed                          |
| 5    | internal error — an unexpected exception escaped top-level handling                                         |

Changed-scope flags are contract-sensitive: changed-only mode keeps the canonical analysis and
report full while applying summary and threshold evaluation to the changed-file projection; the
diff-comparison flag requires it; the git-diff path flag implies it. The authoritative flag
inventory is the option specification module and the CLI help contract snapshot. A new exit reason
MUST be documented and tested.

A typed outcome MUST ship with help and an executable next step, and MUST NOT name a parameter the
tool does not expose: **an instruction the user cannot follow is a defect, not a message.**

---

## 10) Release hygiene

**REL1** — Before a release an agent MUST confirm baseline schema compatibility is unchanged or
properly versioned, MUST ensure the changelog carries user-facing changes and migration notes,
MUST validate built artifacts, and MUST smoke test a clean install.

---

## 11) Prohibited

**PR1** — An agent **MUST NOT**:

- introduce hidden behavior differences between report formats;
- make baseline compatibility depend on the package patch or minor version;
- add project-root hashes or machine-local fields to the baseline;
- embed suppressions into the baseline unless designed as a versioned contract;
- introduce nondeterministic ordering;
- make the base install depend on optional MCP runtime packages;
- let memory, trajectories, experiences, or observability authorize edits or override canonical
  facts;
- conflate the setup CLI with change control;
- emit **absolute or machine-local filesystem paths, usernames, or machine identifiers** into any
  public surface — published artifacts, issues, pull requests, marketplace metadata. Outgoing text
  MUST be scanned before posting. Repository-relative logical paths are permitted and are the
  required form for provenance (`RP1`).

Related prohibitions live with their owners: `P7` · `MCP1` · `P5` · `P8`.

---

## 12) Architecture and routing

*Non-normative routing map (`AUTH1.1`). Boundary obligations are owned by `DD1`.*

| Layer                            | Path                                                                                                                                         |
|----------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| Structural Change Controller     | controller mixins and intent/blast/patch/receipt helpers under `surfaces/mcp/`, `workspace_intent/*`, `analysis/blast_radius.py`, `budget/*` |
| CLI entry and orchestration      | `main.py` (minimal), `surfaces/cli/*`, `ui_messages/*`                                                                                       |
| Setup readiness CLI              | `surfaces/cli/setup/*` and its config, gitignore, atomic-write helpers                                                                       |
| Config                           | `config/*` — option specs, parsing, loading, precedence                                                                                      |
| Core orchestration               | `core/*` — bootstrap, discovery, workers, metrics, report and gate integration                                                               |
| Analysis                         | `analysis/*`, `blocks/*`, `paths/*`, `qualnames/*`, `scanner/*`                                                                              |
| Finding derivation               | `findings/*`, `metrics/*`, `meta_markers/*`                                                                                                  |
| Domain and contracts             | `models.py`, `contracts/*`, `domain/*`                                                                                                       |
| Persistence contracts            | `baseline/*`, `cache/*`                                                                                                                      |
| Canonical report and projections | `report/document/*`, `report/gates/*`, `report/renderers/*`                                                                                  |
| HTML rendering                   | `report/html/*` — render-only                                                                                                                |
| MCP interface                    | `surfaces/mcp/*`                                                                                                                             |
| Engineering Memory               | `memory/*`                                                                                                                                   |
| Platform Observability           | `observability/*`                                                                                                                            |
| Corpus Analytics                 | `analytics/*`                                                                                                                                |
| Controller insights              | `controller_insights/*`                                                                                                                      |
| Audit trail                      | `audit/*`                                                                                                                                    |
| Scripts and CI action            | `scripts/*`, action directory                                                                                                                |
| Client surfaces                  | extensions and plugins — governed by `SUR1`                                                                                                  |
| Tests                            | `tests/` — executable specification                                                                                                          |

---

## 13) Dependency direction

**DD1** — These boundaries MUST hold; they are partially enforced by architecture tests.

- The report layer MUST NOT import UI message modules, CLI surfaces, or HTML consumers outside the
  HTML package.
- Baseline and cache MUST NOT import CLI surfaces, UI messages, or HTML.
- Core MUST NOT import surfaces or config.
- Analysis, findings, and metrics MUST NOT import surfaces; analysis and findings MUST also stay
  independent of config and report-builder wiring.
- Shared models MAY import only contracts locally; domain modules MUST stay leaves.
- Memory MAY import contracts, utilities, blast-radius helpers, and report document types for
  ingestion; it MUST NOT import surfaces or UI messages.
- Observability is diagnostics-only and MUST NOT become a dependency that changes analysis,
  findings, gates, baselines, memory facts, or authorization.
- Core and domain MUST NOT depend on presentation or MCP. Renderers depend on the canonical
  payload; the canonical layers MUST NOT depend on renderers. Presentation MUST NOT recompute core
  facts (`P3`). Persistence semantics MUST stay in persistence and domain modules. MCP MAY depend
  on pipeline, report, and contracts; those layers MUST NOT depend on MCP.

Placement is a structural fact, not a preference: where a ring boundary and a cohesion signal
disagree, an agent SHOULD extract rather than force either one.

---

## 14) Suppression policy

**SUP1** — Inline suppressions are explicit local policy, not analysis truth. Binding scope MUST
be declaration-only; there is no file-wide or implicit global scope. Binding MUST be
target-specific (path, qualified name, declaration span, kind). Unknown or malformed directives
MUST be ignored safely — analysis MUST NOT fail on suppression syntax. Suppressed findings MUST be
excluded from active findings and health impact while remaining observable in report surfaces.
Suppressions MUST NOT alter unrelated finding families.

---

## 15) Change routing

**CR1 — Tests, documentation, and approval per zone.**

An agent MUST update `CHANGELOG.md` for every user-visible change.

An agent MUST **add or change** tests in a zone's listed modules when the change alters
**observable contract behavior** or leaves new behavior uncovered. An agent MUST NOT edit a test
that already correctly covers the changed behavior merely to demonstrate activity — the obligation
to *run* the zone's tests is owned by `V1`, and editing a correct test to satisfy a checklist is
process theater.

An agent MUST obtain explicit maintainer approval where the trigger column applies.

| Change zone                                                                  | Owning test modules                                                                   | Approval required when                                                                                            |
|------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| Baseline schema, admissibility, context compatibility, lane trust, integrity | baseline tests plus CI/CLI behavior tests                                             | schema, admissibility, or trust semantics, compatibility windows, payload integrity                               |
| Cache schema, profile, integrity                                             | cache tests plus pipeline/CLI integration                                             | schema, status, or profile compatibility                                                                          |
| Canonical report JSON shape                                                  | report contract coverage, branch invariants, format tests                             | finding, meta, or summary schema                                                                                  |
| CLI flags, help, exit behavior                                               | CLI unit, in-process, smoke tests, verified against the option spec and help snapshot | exit-code semantics, script-facing behavior, flag contracts                                                       |
| Setup readiness CLI                                                          | setup and config-writer tests plus the snapshot golden                                | lazy-load boundary, snapshot or plan shape, apply semantics, TTY contract, exit codes                             |
| Structural Change Controller                                                 | controller, verification-profile, patch-trail tests plus tool-schema snapshots        | edit authorization, scope or hygiene, verification profile, claims, receipt or patch-trail contract               |
| Fingerprint-adjacent analysis                                                | fingerprint, extractor, CFG, golden tests                                             | **always** (`P6`)                                                                                                 |
| Suppression semantics and reporting                                          | suppression, extractor, metrics, pipeline, report tests                               | declaration scope, rule effect, contract-visible counters                                                         |
| MCP interface                                                                | MCP service and server tests plus the tool-schema snapshot                            | tool or resource shapes, workflow payloads, read-only semantics, packaging                                        |
| Memory, retrieval, trajectories, experiences, projections                    | memory, semantic, projection, MCP memory tests plus schema snapshots                  | schema or governance transitions, retrieval semantics, trajectory quality, experience promotion, worker lifecycle |
| Platform Observability                                                       | observability tests plus boundary tests                                               | privacy or trust boundary, persisted schema, correlation, payload size, public projections                        |
| Audit and controller insights                                                | audit and insight projection tests                                                    | event core or schema, retention, payload footprint, collector semantics                                           |
| Corpus Analytics                                                             | analytics and config tests                                                            | store, export, representation contract semantics                                                                  |
| Client surfaces                                                              | that surface's commands from `V1`                                                     | discovery or runtime model, bundled configuration, bundled skill behavior, packaging metadata                     |
| CI action                                                                    | action helper tests plus an action smoke                                              | input interpolation, command construction, timeout, output, exit behavior                                         |
| Integration sync and distribution                                            | sync tests, then target-native smoke                                                  | deletion or copy boundary, target layout, launcher override, denylist, manifest provenance                        |
| Docs site and sample report                                                  | strict documentation build plus report tests if embeds change                         | published navigation, sample-report generation, publishing workflow                                               |

---

## 16) Public versus internal surfaces

**PS1 — Classification rule.** A surface is contract-sensitive when its shape, semantics,
ordering, exit behavior, or trust rules are observable outside this repository. **Where
classification is ambiguous, an agent MUST treat the surface as contract-sensitive** and MUST add
tests before merging.

*Contract-sensitive (non-exhaustive):* controller intent, permission, scope and hygiene, blast
radius, verification profile, claims, receipts, patch trail · CLI flags, defaults, exit codes,
stable script-facing messages · setup CLI subcommands, machine-readable projections, lazy-load
isolation, bounded apply scope, TTY semantics · baseline schema, admissibility, context
compatibility, lane compatibility, comparison availability, integrity · cache schema, status,
profile · canonical report JSON schema and documented projections · documented MCP install
behavior, tool names, resource URIs, read-only semantics, workflow payloads, verification profiles,
workspace coordination, queue and promote semantics, receipts · memory schema, governance,
retrieval and ranking semantics, sidecar format, trajectory quality, experience promotion,
projection jobs · observability environment contract, local schema and privacy boundary, bounded
sections, correlation · audit event core and shared insight payloads · session-local review state ·
documented client-surface behavior · documented finding families, kinds, ids, suppression-facing
fields · metrics baseline schema where consumed by CI · corpus analytics contracts · workspace
intent wire schema · benchmark schema and outputs when consumed as a reproducible contract.

*Internal:* local helpers and formatting utilities, private normalizers, orchestration
decomposition inside CLI support modules, and private refactors that change no public payload, exit
semantics, ordering, or trust rule.

---

## 17) Testing and the acceptance laws

**T1 — Taxonomy and placement.** Buckets: Unit · Contract · Golden · Determinism and invariant ·
Scenario and regression · Diagnostics. An agent MUST expand the closest bucket when changing
behavior, MUST include contract tests (not only unit tests) for a public-surface change, and MUST
place tests in the owning behavior module rather than a coverage-uplift dumping ground. Goldens
validate intended shifts and MUST NOT substitute for reasoning. Coverage is a guardrail and MUST
NOT be treated as a reason to execute lines without asserting behavior.

### 17.1 Evidence law

**E1 — A green test proves nothing.** Red-first proves a test was red once. Only **mutation**
proves it dies when the exact pinned behavior breaks. An agent MUST revert or corrupt that
behavior and observe the pinning test fail on its intended assertion. A surviving mutant is a
hollow test and MUST be strengthened until it dies.

**E2 — Both boundaries where a boundary exists.** Where a change corrects a value or a
classification, an agent MUST mutate in **both** directions.

**E3 — Semantic witness.** Each row of the verification matrix MUST be observable through a
**witness** — the concrete semantic difference the failure or probe reports, in the form
*expected X, observed Y*.

The witness, not the set of failing test names, is the normative signature. Failing-test identity
is unstable (an unrelated regression test changes it without changing evidentiary power) and
gameable (one narrow test per mutation). The witness is neither.

**A witness MUST be a natural observation of the contract under test.** An agent MUST NOT author
distinguishing error messages, add assertion text, or shape failure output for the purpose of
making witnesses differ. A manufactured witness is fabricated evidence and is the successor form of
the hollow test this law exists to prevent.

**Where witnesses MUST differ** is set by the profile in `E8`, not asserted universally: uniqueness
is required precisely where **the contract itself distinguishes those states**. Two implementation
mutants that legitimately violate one public invariant in the same way MAY share a witness — that is
a well-pinned contract test that does not localize the internal cause, and localization is not
always the contract's job.

**E4 — Direction of redness.** Where the profile requires it, restoring a defect and breaking the
same behavior **deeper** MUST produce different witnesses. Identical witnesses under that profile
mean the suite pins the shape of the code, not its behavior.

**E5 — A count without its exit code is not a result.** A crashed run truncates its own totals
plausibly. *No tests collected*, *usage error* (including a nonexistent path — the guard message may
still print), and *build error* each produce a plausible-looking run that is neither a pass nor a
kill. An agent MUST record the exit code alongside any count it reports, and MUST NOT
treat a run that did not execute as either a pass or a kill.

**E6 — Measure in the right scope.** A count taken at the wrong scope reads as a fact and can refute
a true finding. An agent MUST state the scope alongside the number.

**E7 — What is NOT proof.** An agent MUST NOT offer any of the following as evidence: a passing suite · an agent's account of why something failed · a stale
artifact that was not regenerated · pattern-matching a dangerous sink without a runtime reproduction
· "it looks fine on this repository" for anything that moves a reported score.

**E8 — Required artifact: the verification matrix.**

*Scope.* A change is **load-bearing** — and requires a matrix — when it changes observable behavior
of a surface classified contract-sensitive under `PS1`, fixes a defect, adds or modifies a guard, or
changes a classification, threshold, or identity input. A change is **not** load-bearing when it
alters only comments, formatting, or naming with no observable behavior change. `E8` is the sole
owner of this scope; other sections MUST reference it rather than restate it.

*Profile.* The implementer MUST declare the profile; the reviewer MUST check the declaration; where
the class is unclear the strictest applicable profile MUST be used.

| Profile                         | Required rows                                                                                                               | Witness uniqueness                                                                                                                    |
|---------------------------------|-----------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| **Value or classification fix** | defect restored · opposite error · broken deeper — all `mutation-kill`                                                      | **mandatory across all three** — the contract distinguishes these states, which is where the requirement was earned                   |
| **New or modified guard**       | guard bypassed (`mutation-kill`) · guard reached and tripped (`reachability-probe`) · sibling isolation (`isolation-probe`) | required between the bypass kill and the reachability probe                                                                           |
| **Generic contract fix**        | defect restored · an independent deeper corruption — both `mutation-kill`                                                   | required between the two                                                                                                              |
| **New capability**              | each declared guarantee negated in turn — all `mutation-kill`                                                               | required only between guarantees the contract itself distinguishes; there is no "defect restored" row for behavior that never existed |

*Artifact.* Each row MUST record:

| field           | content                                                                                                       |
|-----------------|---------------------------------------------------------------------------------------------------------------|
| `row kind`      | `mutation-kill` · `reachability-probe` · `isolation-probe`                                                    |
| `operation`     | for a kill: the exact production mutation. For a probe: the exact distinguishing input or isolation performed |
| `failure class` | `semantic` · `collection` · `import` · `syntax` · `usage` · `timeout` · `fixture` · `build`                   |
| `witness`       | expected → observed                                                                                           |
| `test path`     | the executed path                                                                                             |
| `exit code`     | the recorded code                                                                                             |

*Acceptance.* The matrix is accepted only when all hold:

1. **Every `mutation-kill` row is a semantic kill** — the relevant test path executed and failed on
   its intended semantic assertion or contract. Collection, import, syntax, usage, timeout,
   fixture-construction, and build failures are **NOT kills**: such a row is **void** and MUST be
   re-run, not counted. This criterion outranks the exit code — a plausible exit code on a crashed
   path is not evidence (`E5`).
2. **Every probe row demonstrates its claim.** A `reachability-probe` is accepted only if the guard
   demonstrably **executed and tripped** on the stated input; a `isolation-probe` is accepted only
   if the alternative mechanism was demonstrably **inactive** while the mechanism under test was
   observed. A probe that cannot fail is not evidence.
3. **Every row required by the declared profile is present.**
4. **Witness uniqueness holds wherever the profile requires it** (`E3`, `E4`), computed **among the
   rows the profile names**.
5. **Every row records its operation, failure class, test path, and exit code.**

Where a profile requires two or more `mutation-kill` rows and they yield a single distinct witness,
the change has one pin and no signature; an agent MUST state that explicitly rather than presenting
it as comprehensive.

*Scope of "informal".* Targeted manual mutations and probes, not necessarily a mutation-testing
framework. A full runner as a gate is a later candidate; the targeted manual form is mandatory now,
for implementers and reviewers alike.

### 17.2 Named hollow-test classes

**H1 — Relative-invariant hole: mutate the CONSTANT itself.** A set of relative invariants stays
green for **any** value of the underlying constant, so its justification silently drifts. Where a
number is derived from a stated rule but the derivation lives only in a comment, that comment is an
unexecuted engineering claim that will rot. An agent MUST pin the **derivation rule** — re-derive or
re-measure from its stated basis — and MUST NOT substitute a literal equality assertion, which
merely moves the magic number into the test. Mutating the constant MUST produce a witness.

**H2 — A guard that may be unreachable.** The most extreme hollow test is a guard whose protected
path cannot fire in **any** configuration — structurally dead, not merely misplaced.

An agent MUST NOT overstate the inference: if reverting the guarded behavior produces no observable
change, that proves only that **the mutation produced no distinguishing observation**.
Unreachability and masking (`H3`) remain **separate hypotheses** — the guard may have executed while
a sibling mechanism, a later overwrite, a fallback, or a lossy projection erased its effect.
Establishing unreachability MUST rest on reachability evidence: instrumentation, a trace, or
isolation of every alternative mechanism.

When adding a guard, an agent MUST exhibit an input that demonstrably reaches and trips it (`E8`
reachability-probe). A guard nothing can be shown to reach is theater.

**H3 — Success masked by a sibling.** A run may look green because a parallel mechanism did the
work. An agent MUST isolate and probe each mechanism alone. "The batch was green" is not "this rule
fired".

**H4 — A fixture in the reader's dialect.** A fixture written to match the consumer makes a **wrong**
consumer look right, and the suite stays green indefinitely. When fixing a consumer, an agent MUST
fix its fixture in the same change. Where a compatibility shim already exists elsewhere, that is
evidence the divergence was known and never propagated.

### 17.3 Change acceptance — three paths, never merged

**S1 — Classification is mandatory and explicit.** An agent MUST classify any change that moves a
reported number or verdict; an unclassified change is unaccepted by default, and a mixed change MUST
be split.

| Class                     | What it is                                                    | Acceptance |
|---------------------------|---------------------------------------------------------------|------------|
| **Empirical calibration** | a value derived from measurement of a population              | `S2`       |
| **Normative policy**      | a value chosen as a decision, not derived                     | `S3`       |
| **Correctness**           | a defect in how a value, delta, or classification is computed | `S6`       |

**S2 — Empirical calibration: blind external benchmark, after the recalibration.** A **blind** agent
MUST be given the measurement protocol, not the goal. It MUST run on **at least five frozen external
repositories** spanning orders of magnitude and coding styles, each pinned to a commit recorded
before the first run, using the **same** pinned measurement, with thresholds **unchanged**, reporting
raw distributions first. The external projects MUST attempt to **refute** the calibration, not re-fit
it. Self-repository validation alone MUST NOT be treated as acceptance: a self-calibrated scale
measures the morphology of the object that produced it.

**S3 — Normative policy: authority plus impact, never validation.** A benchmark **cannot sanction** a
normative decision; it can only show consequences. A policy change MUST carry explicit maintainer
authority as its source of correctness **and** an impact measurement as a mandatory witness of what
the decision does. An agent MUST NOT present a benchmark as evidence that a policy is *right*, and
MUST NOT adopt a policy without the impact witness.

**S4 — If external validity fails, that is a new fact, never a tuning signal.** It MUST be handled as
a reference-population redesign in a **separate** task. Re-fitting thresholds against the benchmark
repositories is forbidden.

**S5 — A policy threshold MUST be revised only from an independent policy basis**, never from the
current self-score.

**S6 — Correctness path.** A correctness change MUST carry a red test and a verification matrix
(`E8`), not a benchmark. An agent MUST NOT invoke `S2` to stall a correctness fix, and MUST NOT route
a calibration or policy change through the correctness path.

### 17.4 Inventory law

**I1 — Text search cannot establish completeness.** For a dialect defect it is **systematically blind
by construction**: searching for the producer's key finds every correct reader and never finds the
broken one, because the broken one spells it differently. Also invisible to text search: access
through a loop or runtime variable, aliasing, and reads through an intermediate mapping. Text search
MAY support an inventory; it MUST NOT be its source.

**I2 — Completeness is relative to TWO declared contracts.** An inventory is complete only within a
declared **structural-candidate contract** *S* and a declared **access-analysis contract** *A*. Both
MUST be named in the report. A claim of completeness that names neither is unbounded and MUST NOT be
made.

**I3 — Stages.**

```
1. producer            enumerate the keys and structures actually published
2. structural          candidate consumers, WITHIN structural contract S
3. structural-unresolved   wiring S cannot resolve: dynamic import, registry and plugin
                           lookup, reflection, generated wiring, runtime dispatch
4. access extraction   field- and key-level read sites in each candidate, WITHIN contract A
5. access-unresolved   sites A cannot resolve: computed attribute access, wrapper and
                       helper indirection, reflective reads
6. complement          classify everything in 3 and 5, and everything deliberately excluded
```

An agent MUST run these stages in order and MUST NOT skip one silently; a stage not
reached is reported as not reached (`I5`).

**I4 — A dependency graph yields candidates, not readers, and not all candidates.** Stage 2 alone
cannot prove that a module reads a specific field, and it cannot see a consumer wired dynamically. A
consumer missed at stage 2 never reaches stage 4 and so can never be declared unresolved. **An agent
MUST NOT treat stage 2 as complete**; whatever *S* cannot resolve MUST be enumerated at stage 3.
Treating either contract as total makes this law theater by `H2`.

**I5 — Permitted claims are bounded by the stage actually reached.**

| Reached                                                                                | The only phrasing permitted                                                      |
|----------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| 1–2                                                                                    | "producer-derived **candidate** inventory within *S*; completeness **unproven**" |
| 1–3                                                                                    | "candidates within *S*; *N* structurally unresolved wiring sites outstanding"    |
| 1–4                                                                                    | "reader inventory within *S* and *A*; unresolved sites not yet enumerated"       |
| 1–5                                                                                    | "reader inventory within *S* and *A*; *N* unresolved sites outstanding"          |
| 1–6 with **zero relevant unresolved sites**, or each one excluded by a proven argument | "class closed" **is permitted**                                                  |

An agent MUST NOT write "the class is closed" otherwise. Where tooling for stage 3 or stage 4 does
not exist for the case at hand, the agent MUST say so and MUST stop at the permitted phrasing —
building the missing analysis is a separate, nameable task, not an assumption.

**I6 — Audit the complement.** An audit that examines only what **is** written is half an audit. An
agent MUST ask what is **not** written — the missing lane, the unwired input, the guard nobody
reaches, the case no fixture covers — and MUST build that list mechanically from the code, not from
recall.

**I7 — Unresolved is a reported quantity, not a silence.** Unresolved sites MUST be carried into the
report as a count and a list. An inventory that omits them presents a bounded search as a complete
one.

### 17.5 Product invariants

**G1 — Presentation never recomputes.** Two computations of one number will diverge, and the user
will be shown the wrong one. A renderer MUST NOT compute what the canonical report already states.

**G2 — One signal, one place, one interpretation.** A fact classified in one layer and re-derived in
another produces two semantics for one thing, and they will drift apart. An agent MUST NOT
re-derive in one layer a fact that another layer already classifies. This applies to this
document as well (`AUTH1`).

**G3 — Two trust authorities over one artifact is a defect class.** Where a pessimistic gate declines
to compare, a downstream consumer MUST NOT evaluate the still-attached input independently and
publish a confident answer about a comparison that never ran (`B8`, `B9`).

**G4 — Absence MUST be distinguishable from emptiness.** A consumer MUST be able to tell
"did not run" from "ran and found nothing"; the obligation on report payloads is owned by
`RP2`.

**G5 — Bind identity to complete semantic-input identity, never to a lossy projection.** An identity
computed over a projection is an identity **of the projection**: inputs the identity contract is
defined to distinguish will collide whenever the projection maps them together (`P2`). Size is not
the property that matters — a small manifest may be lossy and a large one complete. The permitted
construction is:

```
exact input state  →  deterministic snapshot identity  →  compact complete witness  →  digest chain
```

An agent MUST NOT substitute a convenient projection for the snapshot identity at the base of that
chain.

---

## 18) Language and typing rules

**L1** — Repository policy; an agent MUST justify any violation in the pull request.

Code MUST run on every supported Python version in the declared range, with no reliance on
latest-version-only behavior without a fallback. Type hints are required for public functions, core
pipeline surfaces, and anything touching baseline, cache, fingerprints, report models,
serialization, or exit behavior. An untyped escape is permitted **only** at IO boundaries and MUST be
narrowed immediately into typed structures; an untyped value in core or domain code MUST carry a
reason comment and a removal note. Models crossing module boundaries MUST be explicitly typed,
immutable where possible, and validated at construction when user-provided. Exit codes are public
contract. An agent MUST NOT iterate an unordered container without sorting where it affects hashes,
identifiers, report ordering, baseline payloads, or output, and JSON output MUST use stable
formatting. Annotation evaluation semantics differ across versions; an agent MUST NOT rely on
evaluation timing.

*Non-normative preferences:* literal types and enums for finite sets; frozen, JSON-serializable
dataclasses for data models; abstract collection types for inputs; typed errors over string-typed
errors; avoiding unchecked casts without a nearby invariant check; splitting an overloaded module by
model, serialization, rules, and rendering.

---

## 19) Agent safety rules

### 19.1 Scope discipline

**SC1** — An agent MUST touch only files directly related to the current task.
**SC2** — An agent MUST NOT clean up, reformat, or refactor outside task scope.
**SC3** — An agent MUST NOT delete functions, classes, blocks, or files written by others unless
deletion is the explicit goal of the task.
**SC4** — An agent MUST report unrelated issues in its final message and MUST NOT fix them silently.
**SC5** — An agent MUST inspect the working tree before starting; uncommitted or untracked changes
MAY belong to a parallel agent or to the maintainer.
**SC6** — An agent MUST NOT delete what it did not create. Ownership MUST be *proven*, never inferred
from resemblance — a neighbouring project may share this language and layout. Foreign working
directories MUST be excluded from every inventory and cleanup.

### 19.2 Workspace protocol

**W1 — One change, one worktree.** An agent MUST use a detached worktree, MUST NOT create a branch,
MUST integrate fast-forward only, and MUST remove the tree afterward. Worktrees an agent creates are
its own temporary artifacts under `P4`.

**W2 — Change-control agents MUST be serialized.** An agent MUST NOT run two against one repository
root: they share run state, and the second silently destroys the first's intent.

**W3** — An agent MUST NOT run a tree-wide restore or clean in a shared checkout.

**W4 — The stash is repository-global.** It is visible from every worktree; an agent MUST check it
from the root before declaring a tree clean.

**W5 — Integration history and current containment are different questions.**

*Historical integration.* A source range counts as historically integrated when **every patch id in
that range is present in the target's history**. Branch-merged listings miss cherry-picks and MUST
NOT be used alone. A failed patch-id predicate is **never** evidence that work was lost: rework — a
branch revised before landing — changes the patch id while the work is present.

*Current containment.* **Historical integration does NOT prove the work is present now.** A patch may
be integrated and later reverted, overwritten, or refactored away. Any claim that work "is present"
or "was lost" is a statement about the **current tree** and MUST be established by content review of
the current tree, never by patch identity alone.

An agent MUST NOT delete a branch, worktree, or artifact on the patch-id predicate alone, in either
direction.

**W6 — Verify the server build before accepting its numbers.** Two servers with similar names can be
different processes running different builds. An agent MUST compare the reported code digest first,
and MUST terminate only processes in its own parent chain.

**W7** — A long-running analysis server against a changed engine produces corrupt runs. That is not a
code regression: an agent MUST restart and reproduce in a fresh process before flagging.

**W8** — An agent MUST NOT force-push, hard-reset, or check out over uncommitted work without explicit
maintainer approval. On conflict it MUST rebase or merge cleanly and MUST NOT silently drop the other
side.

**W9 — Every gate green, or it is a blocker.** An agent MUST treat a single red gate as a
blocker and MUST NOT integrate on a partially green run. There is no "mostly green".

**W10 — Run the full suite AFTER each merge.** An agent MUST run the full suite after every
merge. Two green branches with zero textual conflicts can produce a red merged tree. Textual mergeability is not semantic mergeability.

### 19.3 Documentation hygiene

**D1** — An agent MUST verify every documentation claim about code against **current** code before
writing it.
**D2** — Version constants MUST be read from the contracts module (`B1`); every version-shaped string
in an edited file MUST be verified, not only the one being changed.
**D3** — An agent MUST NOT remove narrative content it did not author; it MAY add or correct.
**D4** — An agent MUST NOT replace a multi-section document with a pointer stub unless explicitly
asked.
**D5** — An agent MUST NOT create speculative design documents inside the published documentation
tree.

### 19.4 Audit completeness

**AU1** — When asked to audit "all" of something, an agent MUST list every file it actually opened.
**AU2** — An agent MAY partition and parallelize where tooling allows. Coverage is the
contract, not effort: an agent MUST NOT present partial coverage as completeness.
**AU3** — An audit MUST include the complement (`I6`) and MUST state which inventory stage it reached
and under which contracts (`I2`, `I5`).

### 19.5 Shared helpers

**SH1** — Presentation helpers MUST be imported, never duplicated inside consuming modules; a missing
helper MUST be added to the shared module. Glossary terms live in the message catalog and the
renderer draws tooltips from it — a new labelled value without a catalog entry is a contract gap.

---

## 20) Roles

### 20.1 Architect / Orchestrator

**The reviewer's own measurement is the evidence; the implementer's report is an input to be checked,
never a substitute for a step.** Steps run in order.

**AP1 — Fix the base.** The reviewer MUST name the exact tree under review and MUST confirm it is the
**merged** tree (`W10`).

**AP2 — Read every hunk, including tests and fixtures.** A fixture or test hunk MUST receive the same
scrutiny as production code — that is where a wrong reader is made to look right (`H4`).

**AP3 — Name the invariant for every hunk.** A hunk with no named invariant is an unreviewed hunk and
MUST NOT be approved. A pure-move hunk still requires the invariant "behavior unchanged", and that
claim MUST be checked, not assumed.

**AP4 — Check the change complement. Always.** The reviewer MUST determine what the diff omitted that
its own change implies — adjacent call sites, the paired branch, the missing test, the documentation
the change invalidates — and MUST build this from the blast radius, never from the diff, which cannot
show what is missing from it.

**AP5 — Build the producer-derived consumer inventory only when it applies.** It is REQUIRED when the
review claims consumer completeness, closes a dialect or reader class, or the change alters a producer
contract or a published key. Where required, the stage and both contracts MUST be stated (`I2`, `I5`).
A local fix that makes no completeness claim MUST NOT be required to produce a field-level inventory.

**AP6 — Re-run the verification matrix yourself when `E8` applies.** The reviewer MUST re-run
it on the merged tree and MUST verify that each kill row is semantic and not void and that
each probe row demonstrates its claim.

**AP7 — Run every gate yourself.** The reviewer MUST execute every gate itself and MUST
record each exit code (`V1`, `E5`).

**AP8 — Check claims against the evidence profile, then rule.** Baseline novelty is never patch-local
proof (`B7`); comparison availability is never inferred (`B8`); phrasing is bounded by the inventory
stage (`I5`). The verdict MUST name what remains unverified. If any step could not be completed, the
outcome MUST be **BLOCKED** or **UNVERIFIED** with the exact missing step, and MUST NOT be a verdict
with a caveat attached.

**A1 — Never manufacture authority.** An orchestrator MUST NOT record as sanctioned anything the
maintainer did not sanction. The controller does not create permissions.

**A2 — Direction is not a launch order; a decision is not an open question.** An orchestrator MUST NOT
dispatch work on a statement of direction, and MUST NOT re-open as a question something already
decided. Where cost or irreversibility is involved it MUST require the explicit word.

**A3 — Arguing on facts is an obligation.** An orchestrator MUST raise an observed problem; silence is
a violation, not tact. Agreement MUST also be argued — a bare "correct" is worth zero.

**A4 — A ratified decision reopens on new reproducible evidence, not on preference.** A
**quantitative** claim requires a new measurement. A **structural** claim requires a new distinguishing
witness — a discovered consumer, a missing field, an unreachable remediation, an unaccounted producer
path, a counterexample, a violated type or domain law. A structural witness needs no number to
bind. An orchestrator MUST NOT reopen a ratified decision on preference alone, and MUST
produce the evidence it reopens on.

**A5 — A cause is a hypothesis until independently established.** An orchestrator MUST NOT relay an
implementer's explanation of a cause as fact. A cause becomes established by measurement **or** by a
distinguishing structural or causal witness (`A4`) — the two are equally admissible, and neither may
be replaced by an account.

**A6 — External audits are evidence, not findings.** An orchestrator MUST verify the cheapest claims
itself first, because they calibrate the author's method. Convergence between **independent methods**
is corroboration; repeated runs of one model MUST NOT be treated as independent auditors, because
they share their own blind spots.

**A7 — A brief MUST be dispatchable without rebuilding context.** It MUST carry the measured defect
with locations, the sanction verbatim, what to build, the ratchet specification, the protocol, what is
explicitly out of scope, and any correction that must not be smoothed over.

**A8 — Escalate only on boundaries.** An orchestrator MUST escalate scope expansion, protected
paths, a live foreign intent, baselines or generated state, and another agent's intent — and
MUST NOT escalate routine controller work.

**A9 — Report faithfully.** A failed gate MUST be reported with its output. A skipped step MUST be
named. An acceptance carrying external changes MUST be reported as an advisory and MUST NOT be
described as fully clean.

### 20.2 Implementer

**X1** — An agent MUST produce a red test before the fix for every claimed defect. A test written
after the fix and green on its first run is not evidence.

**X2** — An agent MUST stop at the scope boundary. If files outside declared scope are needed it MUST
stop before touching them and report. A preflight stop is a valued outcome, not a failure.

**X3** — An agent MUST stop when the brief encodes a false assumption. If a prescribed test would
encode the defect as an expectation, the agent MUST say so instead of implementing it.

**X4** — An agent MUST ship the verification matrix when `E8` applies, with its profile declared.

**X5** — An agent MUST NOT satisfy a guard by choosing what it cannot detect. It MUST either redesign
so the guarded thing does not exist, or take the honest heavy path.

**X6** — An agent MUST NOT refresh a golden snapshot to make a test pass (`P5`).

**X7** — An agent MUST report BLOCKED or UNVERIFIED with the exact missing step and the intent
identifier.

**X8** — An agent MUST name what it did not do: unverified assumptions, untested paths, skipped
checks.

### 20.3 Memory

**MEM1** — Conversation is not memory. Chat text is ephemeral across context compaction, new sessions,
and new processes; durable facts MUST be written to the governed store.

**MEM2** — An agent MUST record a constraint or trade-off at the moment of decision, not at the end of
the task.

**MEM3** — An agent MUST record rejected approaches together with their reasons.

**MEM4** — Memory grants nothing: it MUST NOT be used to authorize an edit, expand scope, or override
a finding. Draft and inferred records MUST NOT be treated as established facts.

**MEM5** — An agent MUST verify that a remembered file, function, or flag still exists before acting
on it.

---

## 21) Pull request checklist

*Non-normative (`AUTH1.1`). Each item cites its owner.*

- [ ] Intent and scope declared before editing; permission observed; receipt persisted; intent cleared (`P7`).
- [ ] Detached worktree; fast-forward-only integration (`W1`).
- [ ] Determinism holds in the sense of `P2`; contracts preserved or versioned (`P1`).
- [ ] Tests placed per `T1`; added or changed per `CR1`; **every gate reported with its exit code** (`V1`, `E5`).
- [ ] If within `E8` scope: verification matrix delivered with its profile declared, every kill row semantic and not
  void, every probe row demonstrating its claim, witness uniqueness where the profile requires it.
- [ ] Every diff hunk carries a named behavioral invariant (`AP3`).
- [ ] Change complement checked (`AP4`); consumer inventory built with stage and both contracts stated **if** a
  completeness claim is made (`AP5`, `I2`, `I5`).
- [ ] Any change moving a reported number classified (`S1`) and accepted through its class path.
- [ ] Golden snapshots not updated to satisfy failing tests (`P5`).
- [ ] Reports distinguish comparison-unavailable from empty (`RP2`, `B9`); no absolute or machine-local paths emitted (
  `PR1`).
- [ ] What was not done is stated explicitly (`X8`).
- [ ] Material agent assistance disclosed; a human reviewed the complete diff (`P8`).

---

*Conflicts between this document and a maintainer instruction are resolved by `AUTH3`.*
