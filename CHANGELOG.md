# Changelog

## [2.1.0a2] - Unreleased

Baselines become one versioned container with per-lane trust, semantic contracts become governable, and health scoring
gets honest about control flow. Upgrading requires action — see the "Upgrading from 2.1.0a1 to 2.1.0a2" guide.

- **Text and markdown reports honor the metric-family declaration, and its interpretation
  gets one owner.** The wave that fixed the HTML reader left the text and markdown renderers
  reading `metrics.families` raw, so a `--skip-metrics` run (and the implicit clones-only run
  a bare invocation falls into) still printed every zero-filled family as measured facts —
  `health: score=0`, `dependencies: ... cycles=0` in text, `### Health` / `- cycles: 0`
  sections in markdown. The three-state law of `meta.computed_metric_families` (key absent
  keeps every family, non-empty filters strictly, declared-empty keeps none) also lived
  inline in the HTML context, one dialect away from every next consumer. The interpretation
  now has a single owner (`codeclone/api/metric_families.py: presentation_metric_families`);
  the HTML context, text renderer, and markdown renderer all filter through it, and a
  declared-empty run renders one absence sentence — the existing `METRICS_SKIPPED` owner
  ("Metrics are skipped for this run.") — instead of family sections. Metrics runs are
  unchanged byte-for-byte on all three surfaces.
- **A skip-metrics HTML report says metrics were skipped instead of rendering zeros as
  measurements.** A `--skip-metrics` run (and the implicit clones-only run a bare invocation
  falls into without a metrics flag or metrics baseline) honestly declares
  `meta.computed_metric_families: []` while `metrics.families` still carries every family
  filled with zeros. The HTML context reader filtered families by declaration *truthiness*,
  so the honest empty declaration read the same as a legacy document with no declaration at
  all — keep everything — and the report presented fabricated figures (`Cycles: 0; avg
  depth: n/a`, `0 candidates total; 0 high-confidence items`, `High-complexity: 0`) for
  metrics that never ran, while the five "Metrics are skipped for this run." insights were
  unreachable from any real document. The reader now distinguishes the three declaration
  states by key presence: key absent (legacy document) keeps every family, a non-empty
  declaration filters strictly to the declared names (unchanged), and a declared-empty run
  keeps none — so `metrics_available` turns false and all five sections speak the absence
  sentence. Metrics runs are unchanged byte-for-byte.
- **The two multi-site section absence sentences get one vocabulary owner each.** "Metrics are
  skipped for this run." was spelled at five HTML section sites — three inline literals
  (quality, dependencies, dead code) and two independent private `_METRICS_SKIPPED` constants
  (module map, review) — and "Dependency graph is not available." at two (a dependencies
  inline literal and the module map's private `_EMPTY_GRAPH_MESSAGE`). Renaming any one owner
  left the sibling sites silently behind. Both sentences now live in one cross-section owner
  each (`report/messages/sections.py`: `METRICS_SKIPPED`, `DEPENDENCY_GRAPH_UNAVAILABLE`),
  the private duplicates are deleted, all seven sites read the owners by import, and the tests
  that pin these surfaces import the owners instead of respelling the substrings. Visible
  output is unchanged byte-for-byte.
- **The "coverage join did not run" fact gets one vocabulary owner per register.** The same
  absence was spelled three ways in three files: the HTML coverage-join panel said "Coverage
  Join is unavailable for this run.", the quality insight one panel over respelled it as
  "Coverage join unavailable.", and the CLI metrics line carried `join unavailable` as a bare
  literal with no named constant. The HTML wording now lives in one owner
  (`report/messages/coverage_join.py: COVERAGE_JOIN_UNAVAILABLE`) read by both the
  coverage-join panel and the quality insight, and the CLI term gets a named owner
  (`_COVERAGE_JOIN_ABSENCE`) beside its API-surface sibling; the tests that pin these
  surfaces import the owners instead of respelling the substring. One visible change: the
  quality insight's sentence converges to the canonical "Coverage Join is unavailable for
  this run." — every other surface is unchanged byte-for-byte.
- **The changed-scope summary stops swallowing the third novelty state.** The changed-scope
  counting owner (`_changed_clone_gate_from_report`) counted only `novelty == "new"` and
  `"known"`, so a run whose findings carry the third contractual value `unavailable` printed
  `findings=N new=0 known=0` on the compact line and `N total · 0 new · 0 known` on the rich
  block — a breakdown whose sum silently disagreed with its own total, readable as "nothing
  new" for comparisons that never ran. `ChangedCloneGate` and `ChangedScopeSnapshot` now carry
  `findings_unavailable`, counted explicitly by vocabulary value (never as the
  `total - new - known` remainder, which would silently absorb any future novelty value), and
  both CLI surfaces name the term — `unavailable=N` / `N unavailable` — exactly when the count
  is above zero. At zero both lines are unchanged byte-for-byte, and the `--fail-on-*` gate
  semantics (`new_func`/`new_block`) are untouched.
- **Every surface can now say that the API-surface baseline comparison did not run.** The
  availability fact existed (`api_surface.summary.baseline_diff_available`) but no surface could
  pronounce it: the quiet (non-TTY) summary printed `breaking=0  added=0` for a withheld
  comparison — byte-identical to "compared, no breaking changes" — the rich `Public API` line
  rendered a withheld run as bare `symbols · modules`, indistinguishable from compared-and-clean,
  and the HTML API card silently dropped its Breaking/Added rows. The CLI `MetricsSnapshot` now
  transports `api_surface_diff_available` from the comparison owner (`codeclone.api.comparison`),
  the compact line omits the `breaking=`/`added=` terms when the comparison never ran (current-run
  facts `symbols=`/`modules=` stay), the rich line says `baseline comparison unavailable`, and the
  HTML card states "Baseline comparison is unavailable for this run." as a muted fact. Runs whose
  comparison ran are unchanged byte-for-byte on every surface.
- **A run that did not observe its whole input universe no longer publishes an API surface
  comparison.** `api_surface_diff_available` asked only whether the metrics baseline was trusted
  and carried an API snapshot; the current run's own population was not part of the question. The
  API comparison is a set-membership diff, and membership manufactures facts from absence: an
  `unmeasured` run (files found, none read) published every public symbol of the stored baseline
  as `change_kind: "removed"` breaking changes beside `baseline_diff_available: true`, and a
  `partial` run fabricated the same removal pointwise for each unread module. The availability
  owner (`codeclone.api.comparison.build_comparison_context`) now consults
  `population_universe_observed` — a new named owner in `codeclone.contracts` beside
  `population_carries_score`, collapsing the four population states to "was everything there
  observed": `complete_nonempty` and `complete_empty` publish, `partial` and `unmeasured` withhold
  (`baseline_diff_available: false`, zero counts, no fabricated rows). `complete_empty` staying
  available is the other boundary, not an accident: a scope that genuinely holds no source file
  anymore has really torn down the API the baseline remembers, and that signal survives. This is
  a different question from the score-existence satellite the adoption family gained earlier —
  `partial` keeps its health score and its adoption deltas by design and loses only the
  set-theoretic API comparison.
- **A refusal run no longer publishes adoption permille deltas, and the compact summary line stops
  grading it.** A current run that observed nothing (empty scope, or files present and none read)
  against a good baseline published `param_delta`/`return_delta`/`docstring_delta` of `-1000` in
  `metrics.families.coverage_adoption.summary` beside `baseline_diff_available: true` — the refusal
  itself became a measured regression, and `--fail-on-typing-regression` /
  `--fail-on-docstring-regression` failed the build on it. The typing and docstring permilles now
  carry the refusal the way the health score has since the symmetric-health fix: absent rather than
  zero, on both halves — a run whose population carries no verdict measures no permille, and a
  baseline whose adoption lane arrived unreadable is no longer read as 0‰. The deltas are never
  subtracted against an absent half, and the adoption family's `baseline_diff_available` flips to
  `false` when the current half withheld its verdict. The quiet (non-TTY) `Metrics` summary line
  printed `health=0(F)` for the same refusal run while the rich line honestly said "not measured";
  it now prints the same absence sentence as its rich twin, from the same wording table (for
  example `health=not measured (no source file in scope)`). Measured runs are unchanged: real
  deltas and the `health=98(A)` form survive byte-identically.
- **`passive_context_capabilities()` is gone from `codeclone.surfaces.mcp._context_governance`.** The
  accessor served the observe-mode capability table, which the envelope stopped carrying when the
  envelope named its own shape; no tool published it afterwards and no production code called it.
  The declaration itself is unchanged — only the unused accessor around it was removed. Nothing in
  the MCP tool contract, the response envelope or the CLI referenced it.
- **The MCP context envelope names its own shape.** Dropping the invariant capability and drill-down
  tables from every response changed the envelope's key set while `contract_version` still said
  `1.0`. Both readers compare that field by exact equality and fall back to their own estimator when
  it differs, so two shapes under one version could not be told apart by the only consumer that
  reads it. The version is now `1.1`, and the published key set is pinned beside it: changing the
  shape reds, and the increment stays a human decision.
- **The MCP response envelope states each continuation fact once (`contract_version` `1.2`).** A
  heavy `finish_controlled_change` cycle measured end-to-end still overflowed its own budget after
  packing (2422 estimated units against the 2200 limit) because every omitted lane restated its
  retrieval route in `context_governance.omitted` while `_continuation.lanes[]` carried the same
  route, and the embedded verify payload restated the top-level `scope_check` — a strict
  fact-superset of the embedded copy — inside `verification`. Omission records now keep their facts
  (counts, reason, field); the executable drill-down rides the `_continuation` index once, and a
  finish response carries one authoritative `scope_check`. The same measurement caught the envelope
  claiming `patch_trail_retrieval_unavailable` for a packed patch trail whose durable audit route it
  published in the same response — the blocker now answers retrievability, not lane reducibility.
  Re-measured on the same heavy cycle after the change: the default finish delivers 2191 of 2200
  units with nothing omitted and the enforcement claim intact (it delivered 2422 with the claim
  withdrawn before), and the full-detail finish packs 3135 raw units to 2149.
### Breaking changes

- **Report schema advanced to `3.2`.** `novelty_reason` — carried beside `novelty` on every clone and design finding —
  gained the value `comparison_unavailable`, for a lane that is comparable under current contracts and was not compared
  in this run. Before it, that case was answered `known`, which asserted a comparison that never ran, so the value set a
  consumer could see did not cover the honest answer. A consumer switching on `novelty_reason` must treat
  `comparison_unavailable` as "no comparison was executed for this family" and keep `lane_unavailable` as "this lane is
  not comparable at all" — the two are different absences and the report no longer conflates them. A report written by
  an earlier release is refused by `codeclone memory init --from-report`, which applies an exact schema policy; re-run
  the analysis to regenerate it.
- **Report schema advanced to `3.1`.** The health population fact —
  `metrics.families.health.summary.population`, and the `data-health-population` attribute in the HTML report — changed
  its value set: `complete` became `complete_nonempty`, and `complete_empty` joined it. One word was carrying two
  facts: a population that exists and was not read, and a scope holding no source file at all. Only the first is a
  broken run; the second is a complete measurement of an empty area, and reporting it as "unmeasured" blamed the run
  for the repository. A consumer matching `population == "complete"` now matches nothing, so update it to
  `complete_nonempty` and treat `complete_empty` as "there was nothing to measure" rather than as a failure. A report
  written by an earlier release is refused by `codeclone memory init --from-report`, which applies an exact schema
  policy; re-run the analysis to regenerate it.
- Baseline format advanced to **3.0** and older baselines are refused. Without a baseline-aware gate the run still
  completes, but every clone group reports `unavailable` novelty; with one, it exits `2`. Regenerate once with
  `--update-baseline`. A legacy file's exact bytes are authenticated and kept as transition evidence, so the change of
  epoch stays auditable instead of being silently overwritten.
- `--metrics-baseline` and `--update-metrics-baseline` are removed, together with their `pyproject.toml` keys. Clone and
  metrics findings are now lanes of one baseline, governed by `--baseline` and `--update-baseline`.
- `baseline_scope_id` — a stable canonical UUID under `[tool.codeclone]` — is required for baseline update and
  baseline-relative gating. It is what stops one project's baseline being compared against another's.
- Upgrade every machine that runs CodeClone **before** adding the new configuration keys. 2.1.0a1 treats an unknown key
  as a contract error, so a stale CI runner exits `2` before it analyzes anything.
- Complexity is now two explicitly distinct metrics. The public `cyclomatic_complexity` — the one health, risk bands
  and gates use — counts authored decisions in the source over AST constructs (`if`/`elif`, loops, comprehension
  generators and filters, short-circuit boundaries in any expression position, `except` clauses, `match` cases and
  guards, `assert`), independent of control-flow normalization and reachability. A separate diagnostic
  `cfg_cyclomatic_complexity` reports full McCabe `E − N + 2P` over the complete normalized control-flow graph —
  exception dispatch, `finally` routing and suppression included — and never enters health or gates. Every function is
  measured rather than only clone-sized ones. Values move against older CodeClone releases; stored complexity
  observations from older baselines are reported untrusted for that lane (`COMPLEXITY_ALGORITHM_REVISION`) rather than
  silently diffed. Re-tune `--fail-health` once after regenerating the baseline.
- The health complexity dimension's elevated/extreme reference shares were re-measured for the source-decision metric.
  They are a generated calibration artifact — computed by a reproducible procedure over a pinned reference distribution,
  not hand-picked — so the health scale reads the new metric honestly. Only these two reference shares moved; the risk
  bands (10 / 20) and the complexity gate are unchanged. Health scores shift accordingly.
- The design dependency-cycle finding kind `cycle` is replaced by `import_cycle` and `deferred_cycle`, classified by
  import binding time — see the Fixed entry below. A consumer matching `kind == "cycle"` on a `design` finding now
  matches nothing instead of failing loudly, so update automation, CI scripts, and agent workflows to the new kinds.
  The `metrics.families.dependencies.summary.cycles` metric is unchanged.
- **`--fail-cycles` now fails on import-time cycles only.** A cycle closed purely by deferred, lazy, or
  `TYPE_CHECKING` imports cannot raise at interpreter start, so it is reported without failing the build. A
  repository whose only cycles are deferred now exits `0` where it previously exited `3`. The same rule governs
  regression gating under `--fail-on-new-metrics`: a new `import_cycle` fails, a new `deferred_cycle` does not, and a
  `deferred_cycle` that hardens into an `import_cycle` fails because the crash risk is new even though the members
  are not. There is deliberately no flag to gate on every cycle — a good default beats another policy surface. The
  two cycle gate messages now name "import-time" so the failing count can be reconciled against the reported total.
- The dependencies lane advances to payload schema `7`. The wire form is unchanged, but cycle membership and cycle
  kind derived from a schema-`6` artifact do not agree with a `7` reader's, and those now decide health, gating, and
  novelty — so an existing baseline is untrusted for that lane until regenerated with `--update-baseline`.
  `HEALTH_INPUT_MANIFEST_VERSION` advances to `2`: health consumes two cycle inputs where it consumed one.

### Added

- **Analysis no longer silently skips files with unsupported syntax.** A file whose parsed syntax the canonical wire
  refuses (for example, syntax newer than the engine) is now a typed, attributed outcome instead of an untyped
  "unexpected error": the console summarizes «N files not analyzed: unsupported syntax (…)» naming the construct, the
  run summary counts the file under `skipped`, and the JSON report carries a per-file witness
  (`inventory.files.unsupported_constructs`, with `unsupported_construct_skipped` also shown by the text and Markdown
  renderers). Exit-code semantics are unchanged.
- **Forward-compatible parsing of Python 3.15 lazy imports (PEP 810).** The wire contract understands the new
  `is_lazy` field on `import` and `from … import`: the eager default is normalized away, so wires and fingerprints
  stay byte-identical with every earlier interpreter, while `lazy import` emits an explicit marker and fingerprints
  distinctly. Python 3.15's dict-unpacking comprehensions `{**d for d in ds}` (PEP 798) are also represented instead
  of crashing the analyzer. This is forward-compatible parsing only; 2.1.0a2 does not claim Python 3.15 support.
- Coupling facts are now interpreter-independent: the builtin-name exclusion used by CBO is a pinned registry covering
  CPython 3.10–3.15 rather than `dir(builtins)` of the running interpreter, so the same repository yields the same
  coupling facts on every supported Python.
- **Semantic authority governance** — declare reviewed contracts in `[[tool.codeclone.authority]]`, gate violations
  with `--fail-on-authority-violation`, and triage ranked candidates in a new report tab or through `check_authority`.
- `--near-miss` reports function pairs whose normalized statement sequences differ by exactly one statement. Advisory
  only; it never enters clone gates or the baseline.
- Near-miss clone detection now counts statement edits accurately — one true insertion, deletion, or replacement each
  cost exactly one edit (sequence edit distance), the reported differing statement is chosen by one documented
  deterministic law even when identical statements repeat, and the near-miss algorithm revision (`3`) is published in
  the report payload.
- `--renamed-structure` reports a new advisory clone tier: functions identical up to a bijective, consistent renaming
  of local bindings and receiver attributes, detected as an exact match in the tier's own canonical digest domain — no
  similarity score. Imported identities, proven globals, terminal callees, and attribute-chain structure stay rigid.
  Advisory only; it never enters clone gates or the baseline, and its algorithm revision (`1`) is published in the
  report payload.
- Near-miss clones are now also detected across consistently renamed structure: the same one-statement budget and
  witness law run a second time over statement tokens canonicalized by the renamed-structure rules, so a copy that
  renames locals and receiver attributes consistently and adds one true statement is found. Each reported pair names
  the token space that certified it (`token_domain: "y8" | "renamed"`), a pair confirmable in both spaces is reported
  once as `y8`, and everything the tier reported before is unchanged. Advisory confinement is inherited unchanged.
- Dead-code analysis reports unreachable statements, and `--fail-on-unresolved-dead-code` gates on public methods
  inheriting from a base outside the analysis root — abstentions that are never counted as dead code.
- Files are classified as production, tests, fixtures, or other, so golden fixtures are suppressed on a named channel
  with a visible count instead of disappearing.
- Baseline trust is per lane: each lane is trusted or unavailable with a stated reason, and clone novelty is `new`,
  `known`, or explicitly `unavailable` instead of assumed.
- The report explains the arithmetic behind the health score instead of only publishing the number.
- `project_label` records an operator-facing project name in published baseline metadata.
- Engineering Memory statements accept a safe Markdown subset (one `## ` title line, code spans, bold/italic, depth-1
  lists, compact tables, blockquotes, bare URLs) that memory UIs render and plain text preserves. Images, raw HTML, and
  `[text](url)` links are rejected at write time as render-surface security risks, and new records carry a
  `statement_format: "md-v1"` marker so legacy plain-text notes are never markdown-rendered; the marker now rides
  every statement-bearing reader surface, derived at read time for unstamped md-titled legacy records.
- MCP memory responses (`get_relevant_memory`, `query_engineering_memory`) carry a `store_provenance` witness —
  which resolution branch produced the store and the count of approved records visible — so a freshly
  bootstrapped hollow store is distinguishable from a knowledge-bearing one, and an unresolvable git state carries an
  explicit `resolution_warning` instead of a silent per-root fallback.

### Changed

- **A baseline published on one CPython version is now usable on another.** The interpreter tag stopped being a
  condition of baseline trust. Previously any difference between the tag stamped in `meta.python_tag` and the running
  interpreter made all ten lanes unavailable at once, printed `Invalid baseline file.` for an artifact that was
  authentic and root-verified, and exited `2` under a baseline-aware gate — so a team on mixed 3.10–3.14 machines could
  not share one baseline. Measured across CPython 3.10, 3.11, 3.12, 3.13 and 3.14 on the same bytes: all ten lane
  digests and all ten lane payloads are byte-identical, and 3 of 163179 container leaf fields differ — `created_at`,
  `python_tag`, and the root digest the tag feeds. No observational field differs, because the analysis wire normalizes
  the interpreters' AST differences away. Substituting the tag alone into a 3.10 container reproduces the exact root
  digest of each of the other four, which is what identifies the tag as the whole of the difference. On this
  repository's own package, cross-reading a baseline restored all 148 `known` recognitions that the tag check was
  rejecting, and the run's novelty distribution became identical to the same-interpreter run.
  - The tag is **not** removed: it stays in `meta.python_tag` and stays an input to the root digest, so it remains
    signed provenance that cannot be rewritten without breaking authentication.
  - Where a usable baseline came from is now reported instead of being silently dropped: the CLI prints
    `Baseline was taken on cp313; this run is cp314.` as a note about origin, not about trust, and the report and MCP
    payload continue to publish `baseline_python_tag` beside the runtime tag.
  - **`baseline_scope_id` is unchanged** and still condemns a whole container: it says which input universe the
    artifact describes, which is a different question from where it was produced.
  - **The real cross-version protection is unchanged.** A run that could not read every file it found is still refused
    publication (`truncated_run`), unconditionally. That guard keys on what was actually read rather than on a version
    string, which is why it — and not the tag comparison — is what protects against an older interpreter failing to
    parse newer syntax.
- **Dependency cycles are reported with their kind split beside the total.** The CLI metrics line reads
  `Cycles  2 detected (1 import, 1 deferred)` and the compact line
  `cycles=2(import=1,deferred=1)`, because the total alone no longer predicts the exit code. A deferred-only run is
  styled as a warning rather than a failure. `metrics.families.dependencies.summary` gains `import_cycles`,
  `deferred_cycles`, `new_import_cycles`, and `new_deferred_cycles`; `cycles` and `new_cycles` keep their meanings,
  and the two kind counts always partition the total.
- **Baseline diffs distinguish a new cycle from a cycle that changed kind.** The dependencies lane remembers each
  cycle's kind, so gaining an import cycle and converting an import cycle into a deferred one — semantically opposite
  events that both left the count unmoved — are no longer both reported as unchanged. The metrics diff carries
  `new_import_cycles`, `new_deferred_cycles`, and `cycle_kind_changes` alongside `new_cycles`.
- Health prices the two cycle kinds through two separate constants. `HEALTH_DEPENDENCY_CYCLE_PENALTY` (25) applies to
  import cycles exactly as before, and a new `HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY` applies to deferred ones.
  **No health score moves in this release**: the deferred penalty is deliberately set to the same 25, so the change
  creates the calibratable seam without touching the scale. Choosing its real value is a separate task that requires
  an independent blind benchmark over frozen external repositories.
- **Cache trust envelope hardened; `CACHE_VERSION` → 3.7.** Three cache-integrity changes land together under one
  version bump (the same combined generation also carries Wave D's widened 18-column unit row — see the complexity entry
  above — and cycle-honesty's dependency-row binding-time and PEP 810 laziness schema, `payload_schema` 7). (1) The
  integrity checksum now covers the versioned pre-image `{v, payload}` instead of `payload` alone,
  bringing the generation gate `v` inside the checksummed scope: a migration, backup, or edit-in-place that rewrites the
  top-level `v` without re-checksumming is now refused as an integrity failure instead of being trusted as a payload it
  never covered under that mark. (2) The keyless "signature" vocabulary is retired to checksum/integrity names and the
  on-disk envelope key `sig` is renamed `checksum`, telling the truth that this is a corruption/desync integrity check —
  not authentication against a local adversary who already controls the analyzed source. (3) The module-dependent
  cache-reuse profile now versions the design-metrics algorithm revision and the security-surface, runtime-reachability,
  and structural-findings detector catalogs, so expanding any of those closed catalogs can no longer serve a stale
  dependent-lane fact — a security or reachability false negative — from a warm cache hit. Every earlier cache is refused
  at the version gate and re-analysed once; no user action is required.
- **Dead-code liveness policy advanced to version 2** with two new life proofs, closing two classes of
  false dead-code findings. A PEP 484 explicit re-export — `from x import y as y`, the `as`-same-name
  spelling — now keeps `y` live on its own, independently of `__all__`; a renaming import
  (`from x import y as z`) does not, a `TYPE_CHECKING`-guarded import never does, and a dynamically
  built `__all__` still proves nothing — only static membership counts. Functions and methods decorated
  with pluggy hook markers are now live when the marker is proven: `hookspec = pluggy.HookspecMarker(...)`
  followed by `@hookspec` marks a live extension declaration, `@hookimpl` a live implementation — each on
  its own, spec and impl never required to pair up. A decorator that merely shares the `hookspec` name
  does not count. Cached analyses re-derive liveness automatically after upgrade; symbols these proofs
  cover disappear from the dead-code lane on the next run.

- **The Engineering Memory store is now shared across git worktrees of a repository.** Default store paths
  (`memory.db_path` and the semantic sidecar) anchor at the main checkout, resolved lexically from the git common
  directory, so an agent in a linked worktree reads the repository's approved knowledge and its drafts survive
  worktree removal. Project identity anchors the same way (same repository → same `project_id` from any worktree).
  Non-git roots and submodules keep per-root stores; explicit `memory.db_path` or `CODECLONE_MEMORY_DB_PATH` keeps
  per-checkout resolution unchanged. Concurrent worktree writers are safe: the store opens in WAL journal mode with a
  busy timeout. Audit journal, workspace intents, analysis cache, and reports remain per-checkout by design.

- Terminal output follows one design system across every command: consistent number formatting and pluralization,
  one color and glyph vocabulary, and error messages that always name an executable next step. Bracketed details in
  warnings (such as `[Errno 2]`) are no longer lost, and every CLI option now documents itself in `--help`. Machine
  outputs (`--json`, SARIF, Markdown, `--ci` lines) are unchanged.
- The default cache size limit (`max_cache_size_mb`) is raised from 50 MB to 256 MB so large repositories keep their
  warm-cache path. A repository whose cache exceeds the limit falls back to full re-analysis on every run.
- Report tables are ordered by operational risk rather than by file path.
- New documentation chapters cover the baseline container, full-McCabe complexity, and health explainability, alongside
  the upgrade guide.

### Performance

- Published baselines are **86% smaller** (14.8 MB to 2.0 MB on this repository) after the data lanes moved to a
  columnar encoding.
- Report generation holds far less memory: rendered artifacts travel as bytes end to end and the document is hashed
  once, cutting peak memory 24% on JSON runs and a further 14% on multi-artifact runs. The report document is also built
  only when a consumer actually needs it.
- Engineering Memory staleness checks batch their subject lookups instead of issuing one query per record.

### Fixed

- **A scoped memory retrieval that fits now fits, and comes back with records in it.** Every MCP response carried the
  same invariant drill-down table and capability declaration inside `context_governance` — 491 estimated context units,
  22% of the 2200-unit budget, identical in every answer. On top of that the top-level `_continuation` index restated
  the base64 continuation cursor that `continuation.lanes.*.page.cursor` already owned, so one fact arrived twice with
  two authorities that could drift. The two together crowded out the payload they were describing: measured on this
  repository's own memory store, `get_relevant_memory` scoped to four files estimated 3209 units against a 2200 limit
  while showing **zero** of 59 available records — it had shed every lane to nothing and still overflowed. The static
  tables have left the envelope: the drill-down table remains the single owner of the routes and now projects the exact
  continuation route onto each omitted lane, where a consumer actually needs it, and `_continuation` points at the
  cursor by `cursor_path` instead of copying it. The same retrieval now estimates 2115 units and returns records.
  `context_governance.capabilities` and `context_governance.drill_down` are no longer present in responses; read them
  from the omitted lane's `drill_down` entry, which carries `tool`, `route` and `cursor_path`.
- **A memory lane the retrieval returned in full is no longer incompressible by accident.** The response packer could
  only shed a lane that already had a continuation cursor, and a lane returned complete has none — nothing was omitted
  at retrieval time. Such a response could not be made to fit at all: it was returned whole, over the limit. The packer
  now mints that lane's cursor from the same projection request the retrieval registered, so a lane can be paged
  whenever its tail stays reachable, and refuses to shed a lane whose tail it cannot address.
- **An over-budget response no longer reports its budget as enforced.** `context_governance` raised
  `mandatory_overflow` on an enforcing response that exceeded its limit while `enforcement.response_budget` beside it
  still said `true` — one fact with two answers, and the claim was the one that lied. The overflow observation stays;
  the enforcement claim is now withdrawn to `false` and `enforcement_blocked.response_budget` names
  `response_exceeds_limit_after_packing`.
- **Memory retention no longer leaves orphan rows in the search index.** `memory_records_fts` has no triggers and is
  maintained by hand, and the retention delete touched only `memory_records`. Every retired record left its index row
  behind: search results stayed correct because the query joins back to `memory_records`, but the store kept growing
  and the orphans still counted in the bm25 corpus that ranks scoped retrieval. Retention now removes the index row
  with the record it deletes, and only for the records it deletes.

- **The HTML provenance panel reads the interpreter-provenance owner instead of deciding again.** The panel rendered a
  green "matches runtime" badge beside the baseline's Python tag by comparing that tag — stripped — against a stripped
  runtime tag of its own. `api.comparison.foreign_interpreter_provenance` already owns that difference and is what the
  CLI note and the MCP run summary publish, and it does not strip: on a baseline tag differing from the runtime tag only
  in surrounding whitespace the panel told the operator the reference was taken here while the owner called the same
  artifact foreign. Measured across eleven tag pairs, the panel and the owner disagreed on nine; the three
  whitespace-bearing cases are now the owner's answer, and the panel and the MCP surface agree on all eleven. The badge
  itself is unchanged — same wording, same colours, same three states, with silence still meaning "no two tags on
  record" rather than "same". Separately, the badge was dispatched on the row's displayed label text, so renaming the
  row would have removed it with nothing red; it is now routed by row identity.

- **An unmeasured current run no longer publishes the stored health score as a regression.** The current half of the
  defect fixed for unreadable baseline lanes below: `compute_health` honestly withholds the number over a population
  that carries no score — an empty analysis scope, or a run that read no file — but the current-run snapshot converted
  that refusal through a field typed `int`, so it arrived at the comparison as a measured `0`. Against a good baseline
  the report then published the whole stored score as movement — measured end to end: an emptied tree against a
  baseline of **96** reported a **−96** health delta beside `baseline_diff_available: true`, with the run's own health
  honestly withheld as `score: null` in the same summary block. The snapshot now carries the refusal (`None`, the same
  mechanism as the baseline half), the diff reports no movement against an absent current term, and the health family's
  `baseline_diff_available` reads `false` for such a run — lane trust can only vouch for the baseline term of the
  subtraction, and `delta: 0` beside `true` would state "compared, unchanged" about a comparison that never ran. The
  metric gates were already protected by the population refusal and are unchanged. No weight, band, reference or
  threshold moved.

- **An unreadable baseline lane no longer publishes a health comparison that never ran.** Health is derived from seven
  lanes, and the report keyed its `baseline_diff_available` on `risk_observations` alone. When any of the other six was
  opaque — authentic bytes recorded under a payload schema this release no longer parses — the reader turned the
  unreadable lane into *zero observations*, the baseline's stored health was recomputed over evidence nobody had, and
  the difference against it was published as an available comparison. Measured end to end: with `module_identity`
  opaque, a run that had genuinely improved by **2** points reported **+96**, because the baseline half of the
  subtraction had collapsed to `0`; with `dead_code` opaque, the same run reported a **−4** regression that no code
  caused. Both are now reported as `baseline_diff_available: false` with a `0` delta — the shape the other metric
  families already use for a comparison that did not run. The refusal also travels through `MetricsSnapshot`, whose
  health fields became optional, so the gate summary, the MCP run summary, the review receipt and Claim Guard — none of
  which consult lane trust — stop seeing a fabricated improvement. Lane authenticity is unchanged: an opaque lane is
  still authenticated by its own digest, and only what is *reported about* it moved. No weight, band, reference or
  threshold moved.

- **Suppressed clone groups are read through one owner, so the report stops stating two numbers for one fact.** The
  canonical document nests `findings.groups.clones.suppressed` one level deeper than its sibling lists, and three
  consumers each re-derived that shape from the raw document with a different idea of it. The review receipt spelled the
  bucket keys in the singular against a container that spells them in the plural and counted **zero** suppressed groups
  on a document publishing **seventeen**, so it never recorded that it had not checked suppressed clones for regression.
  The implementation-context projection ran a sequence coercion over that mapping, silently got nothing, and could not
  see a suppressed group at all. The HTML suppressed panel asked items for `filepath` — a key only the *active* clone
  projection produces — so its File column was empty in every row of every report, and was then dropped as having
  nothing to show. All three now read `codeclone.api.finding_groups`, which answers on the group's own terms: bucket keys
  are read structurally rather than by name, so a consumer cannot lose groups by mis-spelling one, and an absent
  container stays distinguishable from an empty one. The same walk also fixes the category every finding is reported
  under: it was taken from the JSON key holding the groups, so every design and structural finding in the
  implementation-context projection was labelled `groups` rather than `complexity`, `coupling`, or
  `duplicated_branches`. Suppressed groups remain excluded from active findings, health, and gates; they carry no
  baseline comparison term and so are still, correctly, not reported as baseline-sensitive.
- **The declared configuration-delivery contract is now enforced, and the surface it named but never wired goes through
  it.** The contract listed four delivery surfaces, and the `codeclone memory init` analysis path was one of them — yet
  that path read `pyproject.toml` and applied it through the canonical owners directly, bypassing its own declaration on
  both edges. Nothing failed, because no key was withheld from that surface yet: the declaration decided nothing, so a
  withholding added for it would simply not have applied. The memory-init path and the MCP loader now both go through
  the door, and an architecture ratchet computes which modules deliver repository configuration into a run and fails
  when that set and the declaration disagree in either direction — an undeclared delivery site and a declaration whose
  surface stopped delivering are the same lie about coverage. The CLI keeps resolving directly, because it must pass the
  flags the user actually typed; that exemption is now declared as a rule carrying its reason rather than left as an
  absence. No analysis result changes: every surface delivers exactly what it delivered before.
- **A baseline taken on another interpreter says so again, and the run summary publishes that as a fact.** Dropping the
  interpreter tag as a trust condition also dropped the only signal the VS Code extension used to decide whether to show
  the tags at all: it gated them on `compared_without_valid_baseline`, which is `false` for a trusted cross-interpreter
  baseline, so the provenance went silent exactly where it became the only thing worth saying. The MCP run summary's
  `baseline` object now carries an additive `interpreter_provenance` field, computed by the same owner the CLI note
  already uses — `foreign` when the baseline was taken elsewhere (its tag stays in `baseline_python_tag`), `same` when it
  was taken on this interpreter, and `unknown` when one of the two tags is not on record. `same` and `unknown` are
  deliberately different words: both mean "no remark", but one says the origin is known and identical while the other
  says nobody recorded it. Consumers render the published state instead of deriving provenance from a verdict about
  trust, so a healthy run reports no interpreter row rather than repeating `cp314 · cp314`.
- **The VS Code overview stops gating the resolved MCP runtime source on baseline trust.** Which launcher the extension
  resolved is a fact about its own connection; it was shown only while a baseline was untrusted — a condition unrelated
  to it, which hid the row on healthy runs while the session view reported the same fact unconditionally.
- **A clone whose lane was never compared is no longer reported as known baseline debt.** `novelty="known"` means a
  trusted baseline accepted that fingerprint; the report document derived it from an empty difference set, which is the
  same value a comparison that never ran produces. The MCP surface hit exactly that: after it declined to trust a
  baseline container it still handed the container to the report, passed an empty difference set, and the classifier
  answered `known` for clones the baseline had never seen — beside its own `trusted: false` and a null clone diff in the
  same payload. Absence and emptiness are now different values on that wire: a lane that was not compared reports
  `novelty="unavailable"` with the new `novelty_reason="comparison_unavailable"`, which is distinct from
  `lane_unavailable` (the lane itself is not comparable under current contracts) so a reader can tell "regenerate the
  baseline" from "nothing was compared". A comparison that ran and found nothing still reports `known`.
- **The novelty word has one owner in the report document.** `baseline.sorted_novelty_facts` decided it inline, in
  parallel with the findings groups, and an inline re-derivation folds the absent-comparison case into `known` — so one
  artifact could carry `state: "untrusted"` beside `novelty: "known"` for the same clone. Both projections now read the
  same classifier, and the per-finding `novelty_reason` comes from it rather than from a third copy of the rule.
- **MCP reports the adoption and API-surface baseline comparisons it actually ran.** Both families were published as
  `baseline_diff_available: false` on every MCP run, including runs against a fully trusted baseline whose metrics diff
  had just been computed, because the surface never passed those two availability facts to the report builder. The CLI
  passed them all along, so one fact had two answers.
- **One stale baseline lane no longer takes the MCP run's other comparisons with it.** MCP resolved the baseline
  container all-or-nothing, so a single outdated lane — `api_surface`, say — made the whole container untrusted for
  diffing: the clone comparison was skipped and six metric families (`complexity`, `coupling`, `coverage_adoption`,
  `dead_code`, `dependencies`, `health`) reported `baseline_diff_available: false` for comparisons that were
  legitimately available. It now degrades per lane, as the CLI already did: the opaque lane is named in the run
  warnings and takes only its own family, while a lane an active gate depends on still fails the run closed. A
  container that does not describe this run at all — different `baseline_scope_id`, different interpreter tag — is
  still condemned as a whole, because comparison-*context* compatibility has one answer for the whole container rather
  than one per lane.
- **Both surfaces now decide "was this compared" in one place.** The comparison decision moved to a new typed door,
  `codeclone.api.comparison`, which the CLI and MCP both read; each used to decide on its own terms, which is how one
  degraded lane came to produce opposite novelty for the same clone on the two surfaces in the same repository state.
- **Dependency cycles are classified by import binding time instead of being uniformly critical.** Every import edge
  now carries when it binds — `import_time` (top level, class body, module-scope dynamic load), `deferred_function`
  (function or method body), `deferred_getattr` (module-level PEP 562 `__getattr__`), `type_checking`
  (`TYPE_CHECKING` guard), or `lazy_syntax` (PEP 810 `lazy import`, Python 3.15) — statically derived from the AST.
  A cycle is `import_cycle` (critical) exactly when the subgraph of import-time edges still cycles; otherwise it is
  `deferred_cycle` (warning) — real, but unable to crash at import. Typing-only edges no longer create runtime
  cycles at all, while staying visible in the edge list with their kinds. Finding copy states what was measured.
  The dependencies lane advances to payload schema `7` and the analysis cache to `3.7`; pre-upgrade cache entries
  re-analyze on the next run.
- **The cycle kind now reaches every layer that decides, not just the prose.** The classification above previously
  stopped at the suggestion text and the `cycle_details` payload: health, `--fail-cycles`, regression gating, the
  baseline lane, and the summary all kept reading one undifferentiated count. A deferred cycle was therefore
  described as a warning and then scored and failed the build exactly like a fatal one — two meanings for one fact.
  Each of those layers now consumes the split. See the breaking-change and Changed entries for the behaviour that
  moves.
- **The baseline no longer forgets how a cycle was bound.** Reconstructing metrics from a stored baseline dropped each
  dependency row's binding, so every remembered edge read as eager: every reconstructed cycle came back
  `import_cycle`, and a `TYPE_CHECKING`-only cycle sat in the baseline's cycle set where it could mask a real runtime
  one. The stored binding is now carried through, so a baseline and a fresh run classify the same repository
  identically, and both sides of a diff agree on what a cycle is.
- **Cycle findings no longer invent file paths for package modules.** A cycle member resolves through the
  module-identity inventory — a package reports `pkg/__init__.py`, never the phantom `pkg.py` whose link 404s —
  and a member without a resolvable file keeps its module identity with no path claim. The same law now governs
  every module-to-path projection surface (report, HTML overview, blast radius, memory fingerprints).
- Controlled-change verification resolves runs at the intent's own workspace, so parallel same-commit worktrees no
  longer fail `start_controlled_change` or `finish_controlled_change` with a multi-root run-id ambiguity.
- The report file registry is deduplicated by path, so it no longer lists more files than the run found.
- The review queue no longer reports a finding as known without baseline evidence.
- The error for a missing `baseline_scope_id` names the configuration table correctly.
- Warm runs count cached files in health denominators, so a cached run no longer scores differently from a cold one.
- Memory candidates proposed from a finished change now carry that change's attested evidence — the review receipt
  digest, the audit patch-trail digest, and the commit — as durable `memory_evidence` rows, instead of being approved
  with only a bare `human_approval` warrant that recorded no digest. Records approved before this fix are left as they
  are; their digests were never captured and are not invented after the fact. Existing memory stores load and behave
  unchanged (additive rows only, no schema change).
- `get_run_summary` now reports the dead-code tri-state in a new additive `dead_code` block — the count of
  unresolved-external-override abstentions, alongside the dead total and live roots — read from the same
  `metrics.families.dead_code.summary` block the gates treat as authority. Previously the run summary carried only the
  top-level findings totals, so a public method that abstains (neither dead nor live, because it inherits from a base
  outside the analysis root) was invisible to every consumer, its absence indistinguishable from zero. The block
  appears only when metrics ran; a clones-only run omits it rather than reporting misleading zeros.
- `get_report_section(section="metrics_detail", family="dead_code")` now surfaces that family's `summary` — carrying the
  `unresolved_external_override` tri-state counter — and its `unresolved_overrides` abstention list, paginated. The
  family branch previously returned only `items`, so a targeted family query dropped the summary entirely: passing
  `family` was exactly the argument that hid the counter, its surfaced absence indistinguishable from zero. Additive and
  gated on real presence — a family that carries no summary/overrides shows the honest zero rather than a fabricated
  block, and a clones-only (metrics-skipped) run omits the summary rather than reporting a misleading zero.

## [2.1.0a1] - 2026-07-09

CodeClone 2.1 introduces intent-first structural change control, persistent engineering context, agent workflow
evidence, platform self-observability, and broader IDE/agent integration.

### Added

- **Structural Change Controller** with `start_controlled_change` / `finish_controlled_change`, bounded edit scope,
  blast-radius checks, patch verification, claim validation, multi-agent intent coordination, and deterministic review
  receipts.
- **Live Implementation Context** via `get_implementation_context`, including bounded structural context, call
  relationships, contract-oriented truth maps, freshness, test anchors, and active intent boundaries. Context remains
  read-only and never authorizes edits.
- **Engineering Memory**, **Trajectory Memory**, **Patch Trail**, and **Experience Layer** for typed repository
  knowledge, historical agent workflows, change evidence, reusable patterns, and human-governed promotion.
- **Semantic retrieval** with optional LanceDB hybrid search, FTS5/BM25, vector search, and deterministic Reciprocal
  Rank Fusion.
- **Platform Observability** for development-time tracing of CLI, MCP, analysis phases, database activity, semantic
  indexing, worker chains, memory/CPU use, MCP payload pressure, and costly no-ops.
- **Corpus Analytics** for offline intent clustering, interpretability, versioned profiles, sweep comparison, maintainer
  selection, and inspectable JSON/HTML outputs.
- **Module Map** as a deterministic report-only package/module graph with cycle, hub, overloaded-module, and
  unwind-candidate views.
- **Guided Finding Review** as a prioritized report-only review queue with shared finding cards, filters, progress
  tracking, and reviewed-state persistence.
- **Native agent and IDE integrations** for VS Code, Claude Desktop, Claude Code, Codex, and Cursor, including
  governance, audit, memory, trajectory, and structural-review workflows.
- **`codeclone setup`** — lazy-loaded CLI readiness surface (`status`, `doctor`, `plan`, `apply`, `wizard`) with
  capability-aware snapshots, read-only diff preview, and bounded `pyproject.toml` / `.gitignore` merges (no MCP
  intent, no baseline or report writes). The CLI also gains a guided `--help` tour.
- Expanded controller, memory, trajectory, analytics, semantic-search, observability, blast-radius, patch-verification,
  and diagnostic CLI/MCP surfaces. The default MCP server surface is now **38 tools** (**40** when VS Code enables the
  IDE governance channel).
- Reorganized documentation into a task-oriented site (concepts, guides, reference, integrations) with unified
  integration guidance and explicit edition tiers.
- MCP schemas now include parameter descriptions, deterministic `next_tool` guidance, token-budget tracking, workspace
  hygiene warnings, and documentation-contract linting.
- MCP response governance now advertises `context_governance` metadata for bounded agent replies. Workflow, memory, and
  implementation-context responses preserve mandatory control facts inline, compact recoverable evidence under
  `partial_enforce`, disclose omitted lanes, and expose exact drill-down through durable receipt, Patch Trail, blast
  artifact, memory continuation, and implementation-context page retrieval.

### Contract changes

- Cache schema advanced to **2.9** for the rebuildable per-function relationship-fact projection and to **2.11** for
  intra-module, class-method, and receiver-aware call resolution.
- Engineering Memory schema advanced to **1.7** for trajectory and Patch Trail evidence.
- Semantic index format advanced to **3** for LanceDB rows with `source_revision`; existing semantic sidecars should be
  rebuilt.
- Corpus Analytics store schema advanced to **1.2**.
- Corpus Analytics JSON export schema advanced through **1.2** and **1.3**.
- Corpus Analytics representation contract advanced to **3**.
- Corpus Analytics control-plane contract introduced at **1.0**.
- MCP response governance contract introduced at **1.0** with deterministic `utf8_bytes_div_4_v1` context-unit
  estimation and explicit `observe` / `partial_enforce` modes.
- `compare_runs` parameters are unified to `before_run_id` / `after_run_id`.
- `derived.module_map` and `derived.review_queue` remain report-only projections excluded from the integrity digest;
  they add no analysis pass, metrics family, or report schema bump.
- Live Implementation Context relationship facts remain off the canonical report and do not change canonical report
  identity.

### Changed

- Default project workspace moved from `.cache/codeclone/` to `.codeclone/`; legacy paths emit a migration warning.
- Documentation builds now use Zensical with strict clean builds.
- `pydantic` is now a base dependency.
- LCOM4 excludes Protocol methods and Pydantic validation/serialization hooks; `computed_field` remains included.
- Repository coverage is enforced at **>=99%**.

### Performance

- Relationship facts are collected during the primary module walk instead of a second traversal (cold-cache
  `phase_relationship` −28%), and reachability facts replay captured handler nodes instead of a third full AST pass.
- MCP hot paths are bounded: findings are paged before decoration, hotspot and intent-scoped blast projections are
  capped, analysis no longer round-trips through the report, and cache loads retain less transient memory.

### Fixed

- Engineering Memory writes are durable, batch ingestion is atomic, and memory/trajectory/Patch Trail lifecycle
  handling avoids premature staleness, duplicate projections, stale workflow rows, and broken evidence links.
- Best-effort audit and memory-proposal failures are now observable instead of silently swallowed.
- Implementation-context misses return a compact actionable payload instead of empty scaffolding.
- Workspace hygiene, intent attribution, continuation of owned work, queue handling, and recoverable-intent behavior
  were corrected.
- Patch verification now rejects identical before/after runs where required, surfaces health regressions, and warns on
  overstated review claims.
- Semantic retrieval now preserves lexical/vector relevance, avoids source crowding, loads embeddings lazily, and
  coalesces redundant projection work.
- Blast-radius graph logic moved into `codeclone/analysis/blast_radius.py`, removing the CLI-to-MCP dependency
  violation.
- `respect_pyproject=false` no longer reports golden-fixture clone groups as false new regressions.
- Documentation URLs, integration references, and contract tests were aligned with the reorganized site.

## [2.0.2] - 2026-05-19

`2.0.2` is a focused patch release for VS Code extension packaging metadata,
README link behavior, and dead-code runtime reachability precision.

### Enhancements

- Extend runtime reachability with exact Aiogram `Router`/`Dispatcher`
  observer decorators, Starlette `BaseHTTPMiddleware.dispatch` hooks,
  Flask/Blueprint routes, aiohttp `RouteTableDef` route decorators, FastAPI
  route decorator factories, and SQLAlchemy `TypeDecorator` runtime hooks to
  reduce false-positive dead-code findings without name-only heuristics.
- Exclude `node_modules` from the default Python scanner so vendored frontend
  dependencies do not appear as project dead-code findings.

### Bug Fixes

- Fix HTML report PyCharm/IntelliJ source links so they preserve line
  navigation when opening files from report tables.
- Fix README package badges so PyPI/status/download/Python-version links open
  the PyPI project page instead of scrolling to the installation section.
- Treat `__all__` re-exports, PEP 562 lazy `_EXPORTS` modules, and guarded
  dynamic `getattr(..., "method")` callable dispatch as dead-code reachability
  evidence.
- Show a one-time interactive CLI migration note when a trusted `2.0.1`
  baseline is analyzed by `2.0.2`, clarifying that fewer dead-code findings are
  expected after the refined reachability model.

### Internal

- Bump cache schema to `2.8` so projects rebuild cached dead-code and runtime
  reachability facts after the refined framework model.
- Bump the Python package and composite GitHub Action default install version to
  `2.0.2`.
- Record the VS Code extension `0.2.7` metadata that matches the Marketplace
  build carrying Coverage Join hotspot support and workspace-root
  `coverage.xml` discovery.

## [2.0.1] - 2026-05-14

`2.0.1` is a focused stability release for dead-code precision and cache/report
contract parity after the 2.0 line.

### Dead code

- Add framework-aware runtime reachability for dead-code analysis: FastAPI/Starlette
  routes and `Annotated[..., Depends/Security(...)]` dependencies, Django URL patterns,
  Dependency Injector providers, Typer/Click commands, Celery tasks, top-level `__all__`
  exports, package entry points, and Pydantic validator/serializer hooks. Supported
  registrations suppress false dead-code findings without framework execution or
  name-only heuristics.
- Treat `typing.Protocol` and `typing_extensions.Protocol` declarations, including
  generic `Protocol[T]`, as type-only contracts so structural interfaces do not produce
  false-positive dead-code findings.
- Show a one-time interactive CLI migration note for projects upgrading from
  the 2.0.0 line when the refined reachability model may reduce dead-code
  findings.
- Bump cache schema to `2.7` and report schema to `2.11` to carry reachability facts
  for cold/warm parity and report explainability.

## [2.0.0] - 2026-04-30

`2.0.0` promotes the completed 2.0 release line to the stable public contract.

### Release

- Mark the Python package as stable (`2.0.0`) while keeping the established baseline, cache, report, and metrics
  baseline schemas unchanged.
- Make stable install guidance the default across README, docs, MCP guides, and local integration surfaces; prerelease
  installs remain available only as explicit version pins.
- Align VS Code, Claude Desktop, and Codex integration metadata with the final CodeClone 2.0 MCP package.
- Preserve the 2.0 behavior set: canonical package layout, adaptive dependency depth profiling, Coverage Join,
  report-only Security Surfaces, read-only MCP, and native IDE/agent projections.

## [2.0.0b7] - 2026-04-28

`2.0.0b7` is a beta hotfix for packaging-only issues found after the `2.0.0b6` publish.

### Packaging

- Constrain the optional MCP extra to `httpx>=0.27.1,<1` so prerelease install flows such as
  `uv tool install --pre "codeclone[mcp]"` do not resolve incompatible `httpx 1.0.dev*` builds through the upstream MCP
  dependency graph.
- Pin the preview VS Code extension packaging tool to `@vscode/vsce@2.25.0`, removing the vulnerable transitive
  `uuid<14` chain from `package-lock.json` while preserving `.vsix` packaging.
- Keep local pre-commit runs stable after package builds by letting mypy use the configured source roots and ignoring
  generated `build/` and `site/` artifacts.

## [2.0.0b6] - 2026-04-28

The global package refactor lands here: the entire runtime moves onto the
canonical module layout and legacy shims are removed for good. On top of that,
dependency-depth scoring is replaced with an adaptive project-relative model,
and the report/cache contracts advance to surface the new depth profile and the
report-only `security_surfaces` layer.

### Package layout and contracts

- Move the runtime fully onto the canonical package layout: `main` + `surfaces/cli`, `surfaces/mcp`, `core`, `analysis`,
  `baseline`, `cache`, `contracts`, `report/document`, `report/renderers`, and `report/html`.
- Remove remaining legacy root shims and stale compatibility modules in favor of direct canonical imports.
- Remove stale deleted-file cache entries and trim post-refactor import tails that were inflating dependency depth and
  clone pressure.
- Bump report schema to `2.10` and cache schema to `2.6` for additive dependency depth profile fields and
  `security_surfaces` facts; keep clone baseline schema `2.1` and metrics-baseline schema `1.2` unchanged.
- Preserve deterministic contracts and read-only MCP semantics across the new layout.

### Dependency depth scoring

- Replace the old fixed dependency-depth penalty (`max_depth > 8`) with an adaptive internal-graph profile based on
  `avg_depth`, `p95_depth`, and `max_depth`.
- Keep dependency cycles as the hard signal; treat acyclic depth as adaptive pressure relative to the project's own
  dependency profile.
- Limit dependency-depth scoring to the internal module graph instead of external imports such as `typing` or
  `argparse`.
- Surface the dependency depth profile in the canonical report, HTML Dependencies tab, and CLI/CI summaries.

### Security surfaces

- Add `metrics.families.security_surfaces`: a report-only exact inventory of security-relevant capability surfaces and
  trust-boundary code.
- Surface compact `security_surfaces` facts in canonical report JSON, CLI Metrics, HTML Quality, text/markdown
  projections, and MCP summaries / `metrics_detail`.
- Keep the layer honest: no vulnerability claims, no score impact, no gates, no SARIF security findings, and no baseline
  truth.

### Tooling, docs, and UX

- Refresh AGENTS, docs/book, and changelog content for the b6 package layout and report schema `2.10`.
- Tighten preview client metadata and install guidance for VS Code, Claude Desktop, and Codex.
- Replace the Codex plugin shell snippet with a repo-local shell-free launcher, and parallelize VS Code post-run MCP
  artifact hydration.
- Add a quiet one-time VS Code extension hint in interactive VS Code terminals, tracked per CodeClone version next to
  the resolved project cache path.

## [2.0.0b5] - 2026-04-16

Expands the canonical contract with adoption, API-surface, and coverage-join layers; clarifies run interpretation
across MCP/HTML/clients; tightens MCP launcher/runtime behavior.

### Contracts, metrics, and review surfaces

- Report schema `2.8`: add `coverage_adoption`, `api_surface`, `coverage_join`, and optional
  `clones.suppressed.*` (for `golden_fixture_paths`); separate coverage hotspots vs scope gaps.
- Baselines: clone `2.1`, metrics `1.2`; compact `api_surface` payload (`local_name` on disk, qualnames at runtime);
  read-compatible with `2.0` / `1.1`.
- Add public/private visibility classification for public-symbol metrics (no clone/fingerprint changes).
- Add annotation/docstring adoption coverage: parameter, return, public docstrings, explicit `Any`.
- Add opt-in API surface inventory + baseline diff (snapshots, additions, breaking changes).
- Add coverage join (`--coverage`): per-function facts + findings for below-threshold or missing-in-scope functions;
  current-run only (not baseline truth, no fingerprint impact).
- Add `golden_fixture_paths`: exclude matching clone groups from health/gates while keeping suppressed facts.
- Add gates: `--min-typing-coverage`, `--min-docstring-coverage`, `--fail-on-typing-regression`,
  `--fail-on-docstring-regression`, `--fail-on-api-break`, `--fail-on-untested-hotspots`, `--coverage-min`.
- Surface adoption/API/coverage-join in MCP, CLI Metrics, report payloads, and HTML (Overview + Quality subtab).
- Preserve embedded metrics and optional `api_surface` in unified baselines.
- Cache `2.5`: make analysis-profile compatibility API-surface-aware; invalidate stale non-API warm caches; preserve
  parameter order; align warm/cold API diffs.

### MCP, HTML, and client interpretation

- Surface effective analysis profile in report meta, MCP summary/triage, and HTML subtitle.
- Add `health_scope`, `focus`, `new_by_source_kind` to MCP summary/triage.
- Make baseline mismatch explicit (python tags + no-valid-baseline signal).
- Surface `Coverage Join` facts and the optional `coverage` MCP help topic in
  the VS Code extension when the connected server supports them.
- Prefer workspace-local launchers over `PATH` (Poetry fallback).
- Add `workspace_root` to force project `.venv` selection.

### Safety and maintenance

- Validate `git_diff_ref` as safe single-revision expressions.
- Replace segment digest `repr()` with canonical JSON bytes (determinism).
- Align CI coverage gate (`fail_under = 99`) and refresh `actions/checkout` pin.
- Refresh branch metadata/docs for `2.0.0b5`; update README badge to `89 (B)`.

## [2.0.0b4] - 2026-04-05

### MCP server

- Add `help(topic=...)` tool for workflow guidance, baseline semantics, analysis profile, and review-state routing
  (tool count: 20 → 21).
- Add `analysis_profile` help topic for explicit conservative-first / deeper-review threshold guidance.
- Enrich `_SERVER_INSTRUCTIONS` with triage-first workflow, budget-aware drill-down, and conservative-first threshold
  guidance so MCP-capable clients receive structured behavioral context on connect.
- Optimize MCP payloads: short finding IDs (sha256-based for block clones), compact `derived` section projection,
  bounded `metrics_detail` with pagination.
- Fix MCP initialize metadata so `serverInfo.version` reports the CodeClone package version rather than the underlying
  `mcp` runtime version.

### Report contract

- Bump canonical report schema to `2.3`.
- Add `metrics.overloaded_modules` — report-only module-hotspot ranking by size, complexity, and coupling pressure.
- Surface Overloaded Modules across JSON, text/markdown, HTML, and MCP without affecting findings, health, or gates.
- Normalize the canonical family name and MCP/report output to `overloaded_modules`; `god_modules` remains accepted as a
  read-only MCP input alias during transition.

### CLI and HTML

- Align CLI and HTML scope summaries with canonical inventory totals.
- Redesign Overview tab: Executive Summary becomes 2-column (Issue Breakdown + Source Breakdown) with scan scope in
  the section subtitle; Overloaded Modules section replaces the earlier stretched module-hotspot layout.

### Documentation

- Add Health Score chapter: scoring inputs, report-only layers, phased expansion policy.
- Document that future releases may lower scores due to broader scoring model, not only worse code.

### IDE and client integration (preview)

- Add VS Code extension (`codeclone-mcp` client) with baseline-aware triage, source drill-down, Explorer decorations,
  and HTML-report bridging.
- Add conservative, deeper-review, and custom analysis profiles to the VS Code extension and pass them through to MCP.
- Add limited Restricted Mode: onboarding works in untrusted workspaces, analysis stays gated until trust is granted.
- Add Node unit tests, extension-host smoke tests, and `.vsix` packaging.
- Tighten the VS Code extension to current VS Code UX guidance: one primary editor action, titled Quick Picks,
  per-view icons, non-button tree details, and a hard minimum local CodeClone version gate (`>= 2.0.0b4`).
- Add Claude Desktop `.mcpb` bundle wrapper for the local `codeclone-mcp` launcher with pre-loaded review instructions,
  explicit launcher settings, platform auto-discovery (macOS, Linux, Windows), local-stdio enforcement, signal
  forwarding, and deterministic package build smoke.
- Add a native Codex plugin with repo-local discovery metadata, bundled `codeclone-mcp` config, pre-loaded instructions,
  and two skills: conservative-first full review and quick hotspot discovery.

### Internal

- Extract shared `_json_io` module for deterministic JSON serialization across baseline, cache, and report paths.
- Remove low-signal structural clone noise surfaced by stricter analysis passes without touching golden fixture debt.

## [2.0.0b3] - 2026-04-01

2.0.0b3 is the release where CodeClone stops looking like "a strong analyzer with extras" and starts looking like a
coherent platform: canonical-report-first, agent-facing, CI-native, and product-grade.

### Licensing & packaging

- Re-license source code to MPL-2.0 while keeping documentation under MIT.
- Ship dual `LICENSE` / `LICENSE-docs` files and sync SPDX headers.

### MCP server (new)

- Add optional `codeclone[mcp]` extra with `codeclone-mcp` launcher (`stdio` and `streamable-http`).
- Introduce a read-only MCP surface with 20 tools, fixed resources, and run-scoped URIs for analysis, changed-files
  review, run comparison, findings / hotspots / remediation, granular checks, and gate preview.
- Add bounded run retention (`--history-limit`), `--allow-remote` guard, and reject `cache_policy=refresh` to preserve
  read-only semantics.
- Optimize MCP payloads for agents with short ids, compact summaries/cards, bounded `metrics_detail`, and slim
  changed-files / compare-runs responses — without changing the canonical report contract.
- Make MCP explicitly triage-first and budget-aware: clients are guided toward summary/triage → hotspots / `check_*` →
  single-finding drill-down instead of broad early listing.
- Add `cache.freshness` marker and `get_production_triage` / `codeclone://latest/triage` for compact production-first
  overview.
- Improve run-comparison honesty: `compare_runs` now reports `mixed` / `incomparable`, and `clones_only` runs surface
  `health: unavailable` instead of placeholder values.
- Harden repository safety: MCP analysis now requires an absolute repository root and rejects relative roots like `.`
  to avoid analyzing the wrong directory.
- Fix hotlist key resolution for `production_hotspots` and `test_fixture_hotspots`.
- Bump cache schema to `2.3` (stale metric entries rebuilt, not reused).

### Report contract

- Bump canonical report schema to `2.2`.
- Add canonical `meta.analysis_thresholds.design_findings` provenance and move threshold-aware design findings fully
  into the canonical report, so MCP and HTML read the same design-finding universe.
- Add `derived.overview.directory_hotspots` and render it in the HTML Overview tab as `Hotspots by Directory`.

### CLI

- Add `--changed-only`, `--diff-against`, and `--paths-from-git-diff` for changed-scope review and gating with
  first-class summary output.

### SARIF

- Stabilize `primaryLocationLineHash` (line numbers excluded), add run-unique `automationDetails.id` /
  `startTimeUtc`, set explicit `kind: "fail"`, and move ancillary fields to `properties`.

### HTML report

- Add `Hotspots by Directory` to the Overview tab, surfacing directory-level concentration for `all`, `clones`, and
  low-cohesion findings with scope-aware badges and compact counts.
- Add IDE picker (PyCharm, IDEA, VS Code, Cursor, Fleet, Zed) with persistent selection.
- Add clickable file-path deep links across all tabs and stable `finding-{id}` anchors.

### GitHub Action

- Ship Composite Action v2 with configurable quality gates, SARIF upload to Code Scanning, and PR summary comments.

## [2.0.0b2] - 2026-03-28

### Dependencies

- Upgrade requests (dev dep) to 2.33.0 for extract_zipped_paths security fix (CVE-2026-25645)

### HTML

- Fix page-level horizontal scrolling in wide table tabs by constraining overflow to local table wrappers (#14).
- Fix mobile header brand block layout on narrow viewports (#15).
- Make mobile navigation tabs sticky and horizontally scrollable with scroll-shadow affordance.
- Keep Overview KPI micro-badges inside cards at extreme browser/mobile widths.
- Restyle Report Provenance summary badges to match the card-style badge language used across the report.

## [2.0.0b1] - 2026-03-25

Major upgrade: CodeClone evolves from a structural clone detector into a
**baseline-aware code-health and CI governance tool** for Python.

### Architecture

- Stage-based pipeline (`pipeline.py`): discovery → processing → analysis → reporting → gating.
- Domain layers: `models.py`, `metrics/`, `report/`, `grouping.py`.
- Baseline schema `2.0`, report schema `2.1`, cache schema `2.2`; `fingerprint_version` remains `1`.

### Code-Health Analysis

- Seven health dimensions: clones, complexity, coupling, cohesion, dead code, dependencies, coverage.
- Piecewise clone scoring curve: mild penalty below 5% density, steep 5–20%, aggressive above 20%.
- Dimension weights: clones 25%, complexity 20%, cohesion 15%, coupling 10%, dead code 10%, dependencies 10%, coverage
  10%.
- Grade bands: A ≥90, B ≥75, C ≥60, D ≥40, F <40.

### Detection Thresholds

- Lowered function-level `--min-loc` from 15 to 10 (configurable via CLI/pyproject.toml).
- Lowered block fragment gate from loc≥40/stmt≥10 to loc≥20/stmt≥8.
- Lowered segment fragment gate from loc≥30/stmt≥12 to loc≥20/stmt≥10.
- All six thresholds configurable via `[tool.codeclone]` in `pyproject.toml`.

### Detection Quality

- Conservative dead-code detector: skips tests, dunders, visitors, protocol stubs.
- Module-level PEP 562 hooks (`__getattr__`, `__dir__`) are treated as non-actionable dead-code candidates.
- Exact qualname-based liveness with import-alias resolution.
- Canonical inline suppression syntax: `# codeclone: ignore[dead-code]` on declarations.
- Structural finding families: `duplicated_branches`, `clone_guard_exit_divergence`, `clone_cohort_drift`.

### Configuration and CLI

- Config from `pyproject.toml` under `[tool.codeclone]`; precedence: CLI > pyproject.toml > defaults.
- Optional-value report flags: `--html`, `--json`, `--md`, `--sarif`, `--text` with deterministic default paths.
- `--open-html-report`, `--timestamped-report-paths`, `--ci` preset.
- Explicit `--no-progress`/`--progress`, `--no-color`/`--color` flag pairs.

### HTML Report

- Overview: KPI grid with health gauge (baseline delta arc), Executive Summary (issue breakdown + source breakdown),
  Health Profile radar chart.
- KPI cards show baseline-aware tone: `✓ baselined` pill when all items are accepted debt, `+N` red badge for
  regressions.
- Get Badge modal: grade-only and score+grade variants, shields.io preview, Markdown/HTML embeds, copy feedback.
- Report Provenance modal with section cards, SVG icons, boolean badges.
- Responsive layout with dark/light theme toggle and system theme detection.

### Baseline and Contracts

- Unified baseline flow: clone keys + optional metrics in one file.
- Metrics snapshot integrity via `meta.metrics_payload_sha256`.
- Report contract: canonical `meta`/`inventory`/`findings`/`metrics` + derived `suggestions`/`overview` + `integrity`.
- SARIF: `%SRCROOT%` anchoring, `baselineState`, rich rule metadata.
- Cache compatibility now keys off the full six-threshold analysis profile
  (function + block + segment thresholds), not only the top-level function gate.

### Performance

- Unified AST collection pass (merged 3 separate walks).
- Suppression fast-path: skip tokenization when `codeclone:` absent.
- Cache dirty flag: skip `save()` on warm path when nothing changed.
- Adaptive multiprocessing, batch statement hashing, deferred HTML import.

### Docs and Publishing

- MkDocs site with Material theme and GitHub Pages workflow.
- Live sample reports (HTML, JSON, SARIF).
- PyPI-facing README now uses published docs URLs instead of repo-relative doc links.

### Packaging

- Package metadata stays explicitly beta (`2.0.0b1`, `Development Status :: 4 - Beta`).
- `pyproject.toml` moved to SPDX-style `license = "MIT"` and `project.license-files`
  for modern setuptools builds without release-time deprecation warnings.

### Stability

- Exit codes unchanged: `0`/`2`/`3`/`5`.
- Fingerprint contract unchanged: `BASELINE_FINGERPRINT_VERSION = "1"`.
- Coverage gate: `>=99%`.

## [1.4.4] - 2026-03-14

### Performance

- Backported report hot-path optimizations from `2.0.0b1` to the `1.4.x` line:
    - file snippets now reuse cached full-file lines and slice ranges without
      repeated full-file scans
    - Pygments modules are loaded once per importer identity instead of
      re-importing for each snippet
- Optimized block explainability range stats:
    - replaced repeated full `ast.walk()` scans per range with a per-file
      statement index + `bisect` window lookup

### Tests

- Preserved existing golden/contract behavior for `1.4.x` and kept report output
  semantics unchanged while improving runtime overhead.

### Contract Notes

- No baseline/cache/report schema changes.
- No clone detection or fingerprint semantic changes.

## [1.4.3] - 2026-03-03

### Cache Contract

- Cache schema bumped from `v1.2` to `v1.3`.
- Added signed analysis profile to cache payload:
    - `payload.ap.min_loc`
    - `payload.ap.min_stmt`
- Cache compatibility now requires `payload.ap` to match current CLI analysis thresholds. On mismatch, cache is ignored
  with `cache_status=analysis_profile_mismatch` and analysis continues without cache.

### CLI

- CLI now constructs cache context with effective `--min-loc` and `--min-stmt` values, so cache reuse is consistent
  with active analysis thresholds.

### Tests

- Added regression coverage for analysis-profile cache mismatch/match behavior in:
    - `tests/test_cache.py`
    - `tests/test_cli_inprocess.py`

### Contract Notes

- Baseline contract is unchanged (`schema v1.0`, `fingerprint version 1`).
- Report schema is unchanged (`v1.1`); cache metadata adds a new `cache_status` enum value.

## [1.4.2] - 2026-02-17

### Overview

This patch release is a maintenance update. Determinism remains guaranteed: reports are stable and ordering is
unchanged.

### Performance & Implementation Cleanup

- `process_file()` now uses a single `os.stat()` call to obtain both size (size guard) and `st_mtime_ns`/`st_size` (file
  stat signature), removing a redundant `os.path.getsize()` call.
- Discovery logic was deduplicated by extracting `_discover_files()`; quiet/non-quiet behavior differs only by UI status
  wrapper, not by semantics or filtering.
- Cache path wiring now precomputes `wire_map` so `_wire_filepath_from_runtime()` is evaluated once per key.

### Hash Reuse for Block/Segment Analysis

- `extract_blocks()` and `extract_segments()` accept optional `precomputed_hashes`. When provided, they reuse hashes
  instead of recomputing.
- The extractor computes function body hashes once and passes them to both block and segment extraction when both
  analyses run for the same function.

### Scanner Efficiency (No Semantic Change)

- `iter_py_files()` now filters candidates before sorting, so only valid candidates are sorted. The final order remains
  deterministic and equivalent to previous behavior.

### Contract Tightening

- `precomputed_hashes` type strengthened: `list[str] | None` → `Sequence[str] | None` (read-only intent in the type
  contract).
- Added `assert len(precomputed_hashes) == len(body)` in both `extract_blocks()` and `extract_segments()` to catch
  mismatched inputs early (development-time invariant).

### Testing & Determinism

- Byte-identical JSON reports verified across repeated runs; differences, when present, are limited to
  volatile/provenance meta fields (e.g., cache status/path, timestamps), while semantic payload remains stable.
- Unit tests updated to mock `os.stat` instead of `os.path.getsize` where applicable (`test_process_file_stat_error`,
  `test_process_file_size_limit`).

### Notes

- No changes to:
    - detection semantics / fingerprints
    - baseline hash inputs (`payload_sha256` semantic payload)
    - exit code contract and precedence
    - schema versions (baseline v1.0, cache v1.2, report v1.1)

---

## [1.4.1] - 2026-02-15

### CLI

- Semantic summary colors: clone counts → `bold yellow`, file metrics → neutral `bold`
- Phase separator, bold report paths, "Done in X.Xs" timing line

### HTML Report

- HiDPI chart canvas, hit-line markers with Pygments, cross-browser `<select>`
- Platform-aware shortcut labels (`⌘` / `Ctrl+`), color-coded section borders
- Compact code lines, proper tab-bar for novelty filter, polished transitions
- Rounded-rect badges (`6px`), tighter card radii (`10px`), cleaner empty states

---

## [1.4.0] - 2026-02-12

### Overview

This release stabilizes the baseline contract for long-term CI reuse without changing clone-detection semantics. Key
improvements include baseline schema standardization, enhanced cache efficiency, and hardened IO/contract behavior for
CI environments.

---

### Baseline Schema & Compatibility

**Stable v1 Schema**

- Baseline now uses stable v1 schema with strict top-level `meta` + `clones` objects
- Compatibility gated by `schema_version`, `fingerprint_version`, and `python_tag` (independent of package patch/minor
  version)
- Trust validation requires `meta.generator.name` to be `codeclone`
- Legacy 1.3 baseline layouts treated as untrusted with explicit regeneration guidance

**Integrity & Hash Calculation**

- Baseline integrity uses canonical `payload_sha256` over semantic payload (`functions`, `blocks`,
  `fingerprint_version`, `python_tag`)
- Intentionally excluded from `payload_sha256`:
    - `schema_version` (compatibility gate only)
    - `meta.generator.name` (trust gate only)
    - `meta.generator.version` and `meta.created_at` (informational only)
- Hash inputs remain stable across future 1.x patch/minor releases
- Baseline regeneration required only when `fingerprint_version` or `python_tag` changes

**Migration Notes**

- Early 1.4.0 development snapshots (before integrity canonicalization fix) may require one-time
  `codeclone . --update-baseline`
- After this one-time update, baselines are stable for long-term CI use

---

### File System & Storage

**Atomic Operations**

- Baseline writes use atomic `*.tmp` + `os.replace` pattern (same filesystem requirement)
- Configurable size guards:
    - `--max-baseline-size-mb`
    - `--max-cache-size-mb`

**Baseline Trust Model**

- **Normal mode**: Untrusted baseline triggers warning and comparison against empty baseline
- **CI preset** (`--ci`): Untrusted baseline causes fast-fail with exit code `2`
- Deterministic behavior ensures predictable CI outcomes

---

### CLI & Exit Codes

**Exit Code Contract** (explicit and stable)

- `0` - Success
- `2` - Contract error (unreadable files, untrusted baseline, integrity failures)
- `3` - Gating failure (new clones, threshold violations)
- `5` - Internal error

**Exit Code Priority**

- Contract errors (exit `2`) override gating failures (exit `3`) when both conditions present

**CI/Gating Modes**

- In CI/gating modes (`--ci`, `--fail-on-new`, `--fail-threshold`):
    - Unreadable or decode-failed source files treated as contract errors (exit `2`)
    - Prevents incomplete analysis from passing CI checks

**Error Handling**

- Standardized internal error UX: `INTERNAL ERROR` with reason and actionable next steps
- New `--debug` flag (also `CODECLONE_DEBUG=1`) includes traceback + runtime environment details
- CLI help now includes canonical exit-code descriptions plus `Repository` / `Issues` / `Docs` links

---

### Reporting Enhancements

**JSON Report (v1.1 Schema)**

- Compact deterministic layout with top-level `meta` + `files` + `groups`
- Explicit `group_item_layout` for array-based group records
- New `groups_split` structure with `new`/`known` keys per section
- Deterministic `meta.groups_counts` aggregates
- Legacy alias sections removed (`function_clones`, `block_clones`, `segment_clones`)

**TXT Report (aligned to report meta v1.1)**

- Normalized metadata/order as stable contract
- Explicit section metrics: `loc` for functions, `size` for blocks/segments
- Sections split into `(NEW)` and `(KNOWN)` for functions/blocks/segments
- With untrusted baseline: `(KNOWN)` sections empty, all groups in `(NEW)`

**HTML Report (aligned to report meta v1.1)**

- New baseline split controls: `New duplicates` / `Known duplicates`
- Consistent filtering behavior across report types
- Block explainability now core-owned (`block_group_facts`)
- Expanded `Report Provenance` section displays full meta information block

**Cross-Format Metadata**

- All formats (HTML/TXT/JSON) now include:
    - `baseline_payload_sha256` and `baseline_payload_sha256_verified` for audit traceability
    - Cache contract fields: `cache_schema_version`, `cache_status`, `cache_used`
    - Baseline audit fields and trust status

### Documentation

- Added the contract documentation book `docs/book/`.

---

### Testing

**Baseline Contract Testing**

- Expanded matrix coverage:
    - Legacy format handling
    - Type/shape validation
    - Compatibility mismatch scenarios
    - Integrity failure cases
    - Canonical hash determinism

**Golden Snapshot Testing**

- New detector golden snapshot fixture with canonical runtime policy
- Golden assertions run on `cp313` (consistency)
- Full invariant suite maintains matrix-wide coverage
- Golden tests use same core `python_tag` source as CLI/baseline checks (prevents cross-layer drift)

---

### Roadmap Note

Version 1.4.0 establishes a stable baseline/CI contract but revealed internal structure needs cleanup. Version 1.5 will
focus on architecture refactoring for maintainability and orchestration, with strict constraints:

**No changes to:**

- Detection semantics
- Fingerprint algorithms
- Baseline hash inputs
- Determinism guarantees

The 1.4.0 contract remains stable and reliable for long-term CI integration.

## [1.3.0] - 2026-02-08

### Overview

This release improves detection precision, determinism, and auditability, adds
segment-level reporting, refreshes the HTML report UI, and hardens baseline/cache
contracts for CI usage.

**Breaking (CI):** baseline contract checks are stricter. Legacy or mismatched baselines
must be regenerated.

### Detection Engine

- Safe normalization upgrades: local logical equivalence, proven-domain commutative
  canonicalization, and preserved symbolic call targets.
- Internal CFG metadata markers were moved to the `__CC_META__::...` namespace and emitted
  as synthetic AST names to prevent collisions with user string literals.
- CFG precision upgrades: short-circuit micro-CFG, selective `try/except` raise-linking,
  loop `break`/`continue` jump semantics, `for/while ... else`, and ordered `match`/`except`.
- Deterministic traversal and ordering improvements for stable clone grouping/report output.
- Segment-level internal detection added with strict candidate->hash confirmation; remains
  report-only (not part of baseline/CI fail criteria).
- Segment report noise reduction: overlapping windows are merged and boilerplate-only groups
  are suppressed using deterministic AST criteria.

### Baseline & CI

- Baseline format is versioned (`baseline_version`, `schema_version`) and legacy baselines
  fail fast with regeneration guidance.
- Added tamper-evident baseline integrity for v1.3+ (`generator`, `payload_sha256`).
- Added configurable size guards: `--max-baseline-size-mb`, `--max-cache-size-mb`.
- Behavioral hardening: in normal mode, untrusted baseline states are ignored with warning
  and compared as empty; in `--fail-on-new` / `--ci`, they fail fast with deterministic exit codes.

Update baseline after upgrade:

```bash
codeclone . --update-baseline
```

### CLI & Reports

- Added `--version`, `--cache-path` (legacy alias: `--cache-dir`), and `--ci` preset.
- Added strict output extension validation for `--html/.html`, `--json/.json`, `--text/.txt`.
- Summary output was redesigned for deterministic, cache-aware metrics across standard and CI modes.
- User-facing CLI messages were centralized in `codeclone/ui_messages.py`.
- HTML/TXT/JSON reports now include consistent provenance metadata (baseline/cache status fields).
- Clone group/report ordering is deterministic and aligned across HTML/TXT/JSON outputs.

### HTML UI

- Refreshed layout with improved navigation and dashboard widgets.
- Added command palette and keyboard shortcuts.
- Replaced emoji icons with inline SVG icons.
- Hardened escaping (text + attribute context) and snippet fallback behavior.

### Cache & Security

- Cache default moved to `<root>/.codeclone/cache.json` with legacy path warning.
- Cache schema moved to compact signed payload format (`CACHE_VERSION=1.2`) with
  relative file keys and fixed-array entries for faster IO and smaller files.
- Cache integrity uses constant-time signature checks and deep schema validation.
- Legacy `.cache_secret` is now treated as obsolete and triggers an explicit cleanup warning.
- Invalid/oversized cache is ignored deterministically and rebuilt from source.
- Added security regressions for traversal safety, report escaping, baseline/cache integrity,
  and deterministic report ordering across formats.
- Fixed POSIX parser CPU guard to avoid lowering `RLIMIT_CPU` hard limit.

### Documentation & Packaging

- Updated README and docs (`architecture`, `cfg`, `SECURITY`, `CONTRIBUTING`) to reflect
  current contracts and behaviors.
- Removed an invalid PyPI classifier from package metadata.

---

## [1.2.1] - 2026-02-02

### Overview

This release focuses on security hardening, robustness, and long-term maintainability.
No breaking API changes were introduced.

The goal of this release is to provide users with a safe, deterministic, and CI-friendly
tool suitable for security-sensitive and large-scale environments.

### Security & Robustness

- **Path Traversal Protection**
  Implemented strict path validation to prevent scanning outside the project root or
  accessing sensitive system directories, including macOS `/private` paths.

- **Cache Integrity Protection**
  Added HMAC-SHA256 signing for cache files to prevent cache poisoning and detect tampering.

- **Parser Safety Limits**
  Introduced AST parsing time limits to mitigate risks from pathological or adversarial inputs.

- **Resource Exhaustion Protection**
  Enforced a maximum file size limit (10MB) and a maximum file count per scan to prevent
  excessive memory or CPU usage.

- **Structured Error Handling**
  Introduced a dedicated exception hierarchy (`ParseError`, `CacheError`, etc.) and replaced
  broad exception handling with graceful, user-friendly failure reporting.

### Performance Improvements

- **Optimized AST Normalization**
  Replaced expensive `deepcopy` operations with in-place AST normalization, significantly
  reducing CPU and memory overhead.

- **Improved Memory Efficiency**
  Added an LRU cache for file reading and optimized string concatenation during fingerprint
  generation.

- **HTML Report Memory Bounds**
  HTML reports now read only the required line ranges instead of entire files, reducing peak
  memory usage on large codebases.

### Architecture & Maintainability

- **Strict Type Safety**
  Migrated all optional typing to Python 3.10+ `| None` syntax and achieved 100% `mypy` strict
  compliance.

- **Modular CFG Design**
  Split CFG data structures and builder logic into separate modules (`cfg_model.py` and
  `cfg.py`) for improved clarity and extensibility.

- **Template Extraction**
  Extracted HTML templates into a dedicated `templates.py` module.

- Added a `py.typed` marker for downstream type checkers.
- Added `__slots__` to performance-critical classes to reduce per-object memory overhead.

### CLI & User Experience

- Added a sequential execution fallback when process pools are unavailable (for example, in
  restricted or sandboxed environments).
- Emit clear, user-visible warnings when cache validation fails instead of silently ignoring
  corrupted state.
- Hardened HTML report template to safely embed JavaScript template literals and aligned it
  with linting requirements.

### Testing & Quality

- Expanded unit and integration test coverage across the CLI, CFG construction, cache
  handling, scanner, and HTML reporting paths.
- Added security regression tests for dot-dot traversal and symlinked sensitive directories.
- Tightened cache mismatch assertions to verify full state reset.
- Achieved and enforced 98%+ line coverage, with coverage configuration added to
  `pyproject.toml`.
- Added GitHub Actions workflow with Python 3.10–3.14 test matrix, including `ruff` and
  `mypy` checks.
- CI baseline enforcement now runs on a single pinned Python version to avoid AST dump
  differences across interpreter versions.

### Python Version Consistency for Baseline Checks

Due to inherent differences in Python’s AST between interpreter versions, baseline
generation and verification must be performed using the same Python version.

The baseline file now stores the Python version (`major.minor`) used during generation.
When running with `--fail-on-new`, codeclone verifies that the current interpreter version
matches the baseline and exits with code 2 if they differ.

This design ensures deterministic and reproducible clone detection results while preserving
support for Python 3.10–3.14 across the test matrix.

### Fixed

- **CFG Exception Handling**
  Fixed incorrect control-flow linking for `try`/`except` blocks.

- **Pattern Matching Support**
  Added missing structural handling for `match`/`case` statements in the CFG.

- **Block Detection Scaling**
  Made `MIN_LINE_DISTANCE` dynamic based on block size to improve clone detection accuracy
  across differently sized functions.

---

## [1.2.0] - 2026-02-02

### BREAKING CHANGES

- **CLI Arguments**
  Renamed output flags for brevity and consistency:
    - `--json-out` → `--json`
    - `--text-out` → `--text`
    - `--html-out` → `--html`
    - `--cache` → `--cache-dir`

- **Baseline Behavior**
    - The default baseline file location changed from
      `~/.config/codeclone/baseline.json` to `./codeclone.baseline.json`.
    - The CLI now warns if a baseline file is expected but missing (unless
      `--update-baseline` is used).

### Added

- **Detection Engine**
    - Deep CFG analysis for `try`/`except`/`finally`, `with`/`async with`, and
      `match`/`case` (Python 3.10+) statements.
    - Normalization for augmented assignments (`x += 1` vs `x = x + 1`).

- **Rich Output**
    - Color-coded status messages.
    - Progress indicators for long-running tasks.
    - Formatted summary tables.

- **CI/CD Improvements**
    - Clearer argument grouping in `--help` output.

### Improved

- **Baseline**
    - Safer JSON loading.
    - Improved typing and cleaner construction API.

- **Cache**
    - Graceful recovery from corrupted cache files.
    - Updated typing to modern Python standards.

- **Typing**
    - General typing improvements across reporting and normalization modules.

---

## [1.1.0] - 2026-01-19

### Added

- Control Flow Graph (CFG v1) for structural clone detection.
- Deterministic CFG-based function fingerprints.
- Interactive HTML report with syntax highlighting.
- Block-level clone visualization.

### Changed

- Function clone detection now based on CFG instead of pure AST.
- Improved robustness against refactoring and control-flow changes.

### Documentation

- Added `docs/cfg.md` with CFG semantics and limitations.
- Added `docs/architecture.md` describing system design.

---

## [1.0.0] - 2026-01-17

### Initial release

- AST-based function clone detection.
- Block-level clone detection (Type-3-lite).
- Baseline workflow for CI.
- JSON and text reports.
