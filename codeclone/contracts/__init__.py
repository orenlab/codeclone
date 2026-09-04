# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from enum import IntEnum
from typing import Final, Literal

# The product default storage paths have one normative owner. They are
# re-exported here so every consumer keeps the import name it already uses.
from .storage_paths import (
    DEFAULT_CACHE_PATH,
    DEFAULT_HTML_REPORT_PATH,
    DEFAULT_JSON_REPORT_PATH,
    DEFAULT_MARKDOWN_REPORT_PATH,
    DEFAULT_SARIF_REPORT_PATH,
    DEFAULT_TEXT_REPORT_PATH,
)

BASELINE_SCHEMA_VERSION: Final = "3.0"
# Version "3" carries two changes that land together and are not separable:
# the norm CFG (post-terminator statements become real unreachable blocks, and
# exception dispatch, `finally` routing and context-manager suppression become
# ordinary edges) and binding-aware symbol emission in the wire. The hash
# domain moves with it (`ccfp3:fn`), so a function whose normalization did not
# change still cannot collide across generations.
BASELINE_FINGERPRINT_VERSION: Final = "3"
# Version "2" emits every Name and Attribute by the role its symbol is bound
# to, in every expression position, replacing the four position-based
# preservation sites. Alpha-renaming a local no longer moves the wire, and a
# resolved import keeps its canonical identity where the old wire erased it.
# The wire is the preimage of every stored fingerprint and statement token, and
# its generation is not inside those hash domains, so this constant is an input
# of the module-neutral cache reuse profile (codeclone/cache/reuse.py) instead
# of depending on BASELINE_FINGERPRINT_VERSION being bumped in the same commit.
WIRE_VERSION: Final = "2"
MODULE_IDENTITY_VERSION: Final = "2"
PORTABLE_PATH_PROFILE_VERSION: Final = "1"
# Generation of the semantic event vocabulary. Events and the function contract
# summaries built from them are stored in the module-neutral cache payload, so
# this constant is an input of that lane's reuse profile
# (codeclone/cache/reuse.py): a bump re-extracts the files instead of serving
# the previous vocabulary's events off a warm hit.
SEMANTIC_EVENT_VERSION: Final = "1"
CONTRACT_IR_VERSION: Final = "1"
# Canonical normalized model (F-3) — the one semantic model shared by the
# run-store backend and canonical JSON vNext. Revision "1" is the frozen
# semantic substrate ratified 2026-08-13 (three-class value epistemics;
# ModuleKey split by places; SYMBOL = (FILE, qualname), proven lossless
# against the legacy ModuleKey addressing on the frozen corpus). Independent
# of REPORT_SCHEMA_VERSION and of any storage schema revision by design: a
# projection revision never reaches back into semantic identity.
CANONICAL_MODEL_REVISION: Final = "1"
# Generation of the CANONICAL OBJECT IDENTITY: the semantic preimage by which a
# stored object, a scope receipt, a membership digest and a run are addressed.
# This constant and no other owns the run-store's domain separators. It moves
# when the preimage moves -- the logical key, the family namespace, the set of
# semantic witnesses, or the canonical payload encoding -- and every content
# address in the store moves with it, by construction.
#
# It is deliberately NOT STORAGE_SCHEMA_REVISION. Until RULING-2026-09-01 the
# storage revision was spelled into the separators, so a bridge table, an index
# or a SQLite layout change reset every object id and every run identity
# without a single analyzed fact changing; measured on the "0" -> "1" bump.
# The two questions are now answered by two constants: "can this process open
# this container" is storage physics, "by which preimage is this object
# addressed" is semantics, and physics may not move semantics.
#
# The separator SPELLING moved with the split (``cc-run-store:`` ->
# ``cc-object-identity:``) because the old spelling's generation space is
# already burned by two storage revisions: under it, identity generation N and
# storage generation N are the same bytes, and no evidence carrying them could
# say which contract produced it. "1" is therefore the first generation of this
# contract, not a continuation of the storage counter.
#
# The version is also a store witness layer with its own role, so it never
# enters the analysis-layer list joined into run identity twice: it reaches
# run_id through the domain separator only, and a store file written under a
# different identity generation is refused at open rather than reinterpreted.
CANONICAL_OBJECT_IDENTITY_VERSION: Final = "1"
# Wire revision of canonical JSON vNext. "0" is the pre-freeze draft grammar
# built by backend wave 1 (root members: format, revisions, values, domains,
# sets, scope, facts, integrity). The bump to "1" is the wire-freeze event
# and belongs to the maintainer once the sanctioned closed list (mechanical
# facts order, discriminator-first proof, columnar benchmark, lexical
# float/escape law, exact integrity preimage, violation_id fixture) closes.
CANONICAL_WIRE_REVISION: Final = "0"
# Storage schema revision of the canonical run-store (backend wave 2).
# Deliberately separate from CANONICAL_WIRE_REVISION and REPORT_SCHEMA_VERSION
# (F-3 §10, brief §14): the SQLite physics may change without claiming the
# semantics moved, and a projection revision never reaches back into stored
# run identity. The SQLite file is an internal store, never a user-facing
# artifact contract. "0" was the pre-freeze draft schema; "1" adds the
# ``run_report_links`` table -- the persisted identity bridge, a REBUILDABLE
# DERIVED INDEX over two artifacts that already exist, never a third
# authority. It is this constant and no other that moves for it: the relation
# is provably recomputable from the report document and the store row, so a
# new key in the public report would duplicate a computable witness rather
# than add semantic information, and REPORT_SCHEMA_VERSION stays where it is.
# The revision is a witness layer, so an existing store file opened by this
# process is refused (law 7) rather than migrated in place; the store holds no
# user artifact. It reaches NO content address: the domain separators belong to
# CANONICAL_OBJECT_IDENTITY_VERSION above, and republishing an unchanged
# analysis under a new schema revision yields the SAME object ids, scope
# receipt, membership digest and run id. That was not true through revision
# "1", which was spelled into the separators and reset all four; files of that
# generation do not declare the identity witness layer and are refused at open.
STORAGE_SCHEMA_REVISION: Final = "1"
AUTHORITY_ANALYSIS_REVISION: Final = "1"
AUTHORITY_REGISTRY_VERSION: Final = "1"
OBSERVATION_DIGEST_VERSION: Final = "1"
# Algorithm revision of the ``coupling_cohesion_observations`` design-metric
# lane. Separate from OBSERVATION_DIGEST_VERSION so a change in how these
# metrics are *computed* invalidates only the lanes whose values moved.
# Revision "2" covers the 39Y changes: every defined function now carries a
# complexity fact (clone-lane floors no longer gate the population), CBO
# counts the imported-domain and resolved-instantiation edge lanes, and the
# coupling risk bands were re-derived from the measured distribution. Values
# from revision "1" are not comparable with revision "2" values, so a baseline
# carrying the old revision is untrusted rather than diffed. Until Wave D this
# revision also governed ``risk_observations``; that lane now moves with
# COMPLEXITY_ALGORITHM_REVISION below, so a complexity recount never
# invalidates coupling observations and vice versa.
DESIGN_METRICS_ALGORITHM_REVISION: Final = "2"
# Algorithm revision of the ``risk_observations`` lane — the lane carrying the
# per-unit complexity dimension. Revisions "1" and "2" (shared history with
# DESIGN_METRICS_ALGORITHM_REVISION above) computed ``cyclomatic_complexity``
# from the CFG; under revision "2" that meant full McCabe E-N+2P over the
# complete Y9 graph. Revision "3" is the Wave D split: the public
# ``cyclomatic_complexity`` is a deterministic source-level decision count
# over AST constructs (single owner:
# ``codeclone.metrics.source_decisions.SourceDecisionCounter``), and the CFG
# value survives only as the diagnostic ``cfg_cyclomatic_complexity``, which
# reaches no baseline lane and no gate. Bump discipline: move this revision
# whenever any cell of the ratified decision table changes — a construct's
# contribution, the match wildcard rule, the BoolOp arity rule, the nested
# scope boundary — or when the lane's population rule moves. Values across
# revisions are not comparable; a baseline carrying an older revision is
# untrusted for this lane rather than diffed. Cached values move with it by
# construction: the constant is an input of the module-NEUTRAL cache reuse
# profile (codeclone/cache/reuse.py), because the per-unit complexity and its
# risk band are stored in that payload and a warm hit serves them verbatim.
# Before that binding a bump moved the report stamp only, and a warm run
# answered with pre-bump complexity under the new revision's name.
COMPLEXITY_ALGORITHM_REVISION: Final = "3"
BASELINE_LANE_DESCRIPTOR_VERSION: Final = "1"
BASELINE_LANE_DIGEST_DOMAIN: Final = "codeclone.baseline.lane.v1\0"
BASELINE_ROOT_DIGEST_DOMAIN: Final = "codeclone.baseline.root.v1\0"
API_SURFACE_SIGNATURE_VERSION: Final = "1"
REPORT_ANALYSIS_FACTS_DIGEST_DOMAIN: Final = "codeclone.report.analysis_facts.v1\0"
REPORT_COMPARISON_DIGEST_DOMAIN: Final = "codeclone.report.comparison.v1\0"
REPORT_EVALUATION_DIGEST_DOMAIN: Final = "codeclone.report.evaluation.v1\0"
REPORT_ENVELOPE_DIGEST_DOMAIN: Final = "codeclone.report.envelope.v1\0"
# --- Report semantic identity v2 (RULING-2026-08-31, ratified) ---
# The generation of the run-identity preimage, deliberately separate from
# REPORT_SCHEMA_VERSION: the schema names the wire shape, this names what the
# identity claims to cover. Generation "1" hashed source facts, the baseline
# projection and the gate request; findings tiers, policy parameters and
# evaluation outputs were outside the preimage, and five measured
# (tree x config x engine) states shared one run_id. Generation "2" adds the
# analysis population, the realized producer contracts and the canonical
# family digests of every EXECUTED semantic family, per the ratified law:
# two runs share a run_id iff they utter the same canonical set of semantic
# statements under the same realized contract of their derivation.
# Documents without this marker verify under generation-1 rules; the marker
# is never inferred.
REPORT_SEMANTIC_IDENTITY_VERSION: Final = "2"
REPORT_ANALYSIS_IDENTITY_DOMAIN_V2: Final = "codeclone.report.analysis.v2\0"
REPORT_COMPARISON_IDENTITY_DOMAIN_V2: Final = "codeclone.report.comparison.v2\0"
REPORT_EVALUATION_IDENTITY_DOMAIN_V2: Final = "codeclone.report.evaluation.v2\0"
REPORT_FAMILY_DIGEST_DOMAIN_V2: Final = "codeclone.report.family.v2\0"
# Which of the five report digest tiers names a run, for every surface that has
# to answer "which run is this". Exactly one tier can: ``evaluation`` seals the
# facts, the baseline, the gate thresholds and the outcome, so two runs over one
# tree that answer differently because their thresholds differ get different
# names. The tier below it -- ``comparison`` -- stops at facts and baseline, and
# gave those two runs one name. The tier above it -- the envelope -- also seals
# ``meta.runtime.report_generated_at_utc``, the document's only time-like field,
# so an identity taken from there would be new on every run by construction and
# no consumer could tell a repeated measurement from a changed one.
#
# It lives in r0 because its readers do not share a ring: the CLI and MCP
# surfaces are r4, the controller plane (``controller_insights``) is r2p, and
# r2p may not import r4. Owned one ring below both, it is reachable from either
# without a boundary violation, which is the whole reason it is here and not
# beside its first consumer. Not a version: the value is a wire key of the
# report document, so it moves only with the document's digest tier set, which
# ``report/document/integrity.py`` emits and verifies.
REPORT_RUN_IDENTITY_TIER: Final = "evaluation"
GATE_LANE_MATRIX_VERSION: Final = "2"
# Version "2" (cycle-policy split): the dependency-cycle input stopped being one
# kind-agnostic count and became two — import cycles and deferred cycles, each
# with its own penalty constant. The manifest names the inputs health consumes,
# so a health score computed under "1" and one computed under "2" are not
# derived from the same input set even when they carry the same number.
HEALTH_INPUT_MANIFEST_VERSION: Final = "2"
# The health formula generation: which aggregate the dimension scores are
# folded through. Until identity v2 this value existed only as an inline "1"
# in the evaluation contract builder -- a witness no constant owned, so a
# formula change had no lever to move. The calibrated inputs of the formula
# (HEALTH_WEIGHTS, the reference permilles, the saturation multiples and the
# dependency penalties) are NOT part of this revision: they are live
# evaluation parameters, uttered and digested per document
# (realized_contracts.evaluation.health.params), so a recalibration moves the
# run identity without touching this constant. This constant moves only when
# the folding itself changes meaning.
HEALTH_ALGORITHM_REVISION: Final = "1"
# The gate evaluation generation, on the same terms: the thresholds are the
# live parameters (gate_thresholds_digest), the lane requirement matrix is
# GATE_LANE_MATRIX_VERSION, and this constant names how request, matrix and
# lane availability fold into an exit verdict.
GATE_ALGORITHM_REVISION: Final = "1"
OBSERVER_VOCABULARY_VERSION: Final = "3"
# Version "2" names three changes to what counts as LIVE and to what the
# evidence lane may claim as the cause.
#
# (A) Two life proofs. (1) A PEP 484 explicit re-export -
# ``from x import y as y``, the ``as``-SAME-name spelling - livens its
# resolved target on its own; static ``__all__`` membership remains the
# second, independent, stronger explicit contract.
# The proof fires only at module scope in a runtime-reachable branch of a
# production file: a renaming import is not a re-export, a
# ``TYPE_CHECKING``-guarded import livens nothing, and a dynamically built
# ``__all__`` stays UNRESOLVED rather than degrading into a heuristic.
# (2) A resolved pluggy hook marker decorator roots its function: a proven
# ``@hookspec`` livens a declaration and a proven ``@hookimpl`` livens an
# implementation - two INDEPENDENT roots, never a pair. "Resolved" means the
# decorator expression resolves to the canonical ``pluggy.HookspecMarker`` /
# ``pluggy.HookimplMarker`` identity through module-scope assignments and
# import aliases; the decorator NAME alone is never evidence.
#
# (B) An evidence row names its own cause. An export root is emitted only for
# a candidate the liveness owner does not already hold live, measured from
# ``classify_liveness`` before any export root exists. Comparing qualnames
# alone could not match an attribute-called method in ANY configuration - an
# ``obj.m()`` call reaches the decision as a bare name - so the lane recorded
# "live because exported" over symbols a call site held live. An ``@overload``
# stub no longer roots the symbol it declares either: every stub shares the
# implementation's qualname, so admitting one let a symbol stand as its own
# external-decorator evidence, and a symbol whose ONLY root was its own stub
# is dead.
#
# (C) The wildcard re-export arm reads the language rule instead of a naming
# convention. ``from <target> import *`` binds what the TARGET's own
# ``__all__`` lists, carried per symbol as ``DeadCandidate.star_import_bound``.
# A leading-underscore test previously stood in for that rule, so a class the
# target's ``__all__`` excludes was rooted through a binding that does not
# exist at runtime; a member reachable only through its defining module is
# dead.
#
# Unchanged by all three: the verdict vocabulary, and the rule-3 abstention
# for an unresolved external base.
#
# (D) "4" retires the ``__all__``-plus-package named export chain (Y2) as a
# LIFE proof (RULING 2026-09-01, corrected 2026-09-03: an ``__all__``
# declaration is not internal use). The walk folded every static ``__all__``
# member into ``referenced_qualnames``, where it was indistinguishable from a
# call site; measured on this repository, that one arm held 104 symbols live
# under the closed world that nothing inside the product binds, 30 of them in
# private modules whose ``__all__`` exports to nobody. The declaration now
# does exactly its two jobs: the star-binding fact (C), and - new on the
# dependent cache lane - ``declared_exports``, the names a module's static
# ``__all__`` lists, which the external-reachability owner reads so that a
# public plain module's declared import is exposure (``declared_reexport``)
# and a name a module-level ``__getattr__`` serves is unresolved, never dead.
# The distinguishing witness for the bump: a cold run under this policy and a
# warm run over a generation-3 dependent lane disagree on every symbol the
# arm held, so a "3" row expresses the old policy and must miss.
#
# Bump this constant whenever what counts as LIVE changes; verdicts across
# versions are not comparable.
#
# "3" retires "2" and carries the same three changes. It exists because the
# release boundary is the wrong test for whether a generation may be refined
# in place. The earlier reasoning here - a generation never released carries
# no artifact, so refine it under the same number - was measured false: an
# UNRELEASED build writes a cache too. "2" and "3" share CACHE_VERSION, so a
# lane written before ``star_import_bound`` existed is accepted by a build
# that reads it, the missing key decodes as "not bound", and the wildcard arm
# concludes that live public API is dead - measured on httpx, five methods at
# high confidence, ``AsyncClient.post`` among them, reachable only on upgrade
# and invisible to any cold run. The honest test is not "has it shipped" but
# "can a reachable artifact still carry the old meaning".
#
# Cached liveness inputs move with a bump by construction: the constant is
# an input of the module-dependent cache reuse profile
# (codeclone/cache/reuse.py), so a bump misses exactly the lane that
# carries ``referenced_qualnames``, dead candidates and live-root reasons,
# and never touches the neutral fingerprint lane. That miss is what this
# bump buys, and it is pinned by
# ``test_liveness_policy_version_misses_only_dependent_lane``.
LIVENESS_POLICY_VERSION: Final = "4"
SOURCE_KIND_POLICY_VERSION: Final = "1"
# Generation of the adoption-coverage policy: WHAT COUNTS as an annotated
# parameter (the receiver of a non-static method is not one; ``*args`` and
# ``**kwargs`` are), as an ``Any`` annotation (bare, dotted, inside a subscript,
# a tuple or a ``|`` union) and as a documented public symbol (module-level
# export, or a public method of an exported class). Sole producer:
# ``codeclone.metrics.adoption.collect_module_adoption`` together with the
# visibility rules it reads from ``codeclone.metrics._visibility``.
#
# Its OUTPUT is stored: the per-module ``typing_coverage`` and
# ``docstring_coverage`` counters ride the module-DEPENDENT cache payload and a
# warm run serves them verbatim, without re-reading a single annotation. They
# are the whole input of the ``adoption_counts`` observation lane and of the
# typing/docstring coverage gates. So this constant is an input of that lane's
# reuse profile (codeclone/cache/reuse.py): a policy change misses exactly the
# dependent lane and leaves the neutral fingerprint lane alone. Without the
# binding the same source measured 57.1% annotated parameters warm and 66.7%
# cold under one policy change — one of two answers chosen by cache state.
# Bump whenever the counting rule moves; counters across versions are not
# comparable.
ADOPTION_COVERAGE_POLICY_VERSION: Final = "1"
# Algorithm revision of the function-relationship extraction: WHICH expressions
# inside a function body become relationship records (every call, plus every
# bare ``Name``/``Attribute`` load that is not the callee of a call) and HOW
# each one resolves to a target qualname — the import index, the caller's local
# bindings, top-level function and class names, local method qualnames, the
# enclosing class and its receiver, and the resolution rule reported beside the
# record. Sole producer:
# ``codeclone.analysis._module_walk._collect_function_relationship_facts``.
#
# Its OUTPUT is stored: ``function_relationship_facts`` rides the
# module-DEPENDENT cache payload per source function and is rehydrated verbatim
# into the dead-code test-reference lane and the call graph, so a resolution
# change that reaches no re-parsed file is simply not applied. Hence this
# constant is an input of that lane's reuse profile (codeclone/cache/reuse.py),
# on the same footing as LIVENESS_POLICY_VERSION above and for the same reason.
# Bump whenever what becomes a record, or what a record resolves to, changes.
#
# "2": two import dialects the resolver used to lose now resolve, so records
# that resolved to nothing under "1" carry a target under "2" —
# ``from <pkg> import <submodule> as <alias>`` binds a MODULE, and a
# function-local ``from <module> import <name>`` binds a symbol the walk
# already saw but the relationship index, which stopped at every function,
# did not. Both are properties of the binding, so one resolver answers them
# once for every consumer. This constant, and not LIVENESS_POLICY_VERSION,
# is the one that moves: what a record resolves to changed; how already
# obtained evidence is read in open/closed world did not.
#
# The distinguishing witness, measured on this repository 2026-09-04: a cache
# written by the pre-fix walk and read by the fixed one served 6 dead symbols
# as ``reason=unreferenced`` with an EMPTY witness list — the defect verbatim,
# ``cached 1184 / analyzed 0`` — while the same source cold reported all 30 as
# ``test_only_reference``. Under "2" that row misses the dependent lane, the
# file is re-walked and warm equals cold. Reverting this literal to "1" alone
# brings all 6 back, which is what makes the bump load-bearing rather than
# adjacent to the fix.
FUNCTION_RELATIONSHIP_ALGORITHM_REVISION: Final = "2"
# Closed detector catalogs that ride the module-dependent cache-reuse lane.
# Each is a mutable enumeration whose EXPANSION changes an emitted dependent
# fact for unchanged source, so a warm cache hit would otherwise serve the
# pre-expansion result as an honest-absence false negative (a narrowing
# self-rejects). Each is an input of the module-dependent reuse profile
# (codeclone/cache/reuse.py), so a catalog change misses exactly that lane and
# never the neutral fingerprint lane. Bump the matching constant whenever its
# catalog gains or drops a member; verdicts across versions are not comparable.
# The security-surface category / location-scope / classification-mode /
# evidence-kind catalogs (codeclone/analysis/security_surfaces.py).
SECURITY_SURFACE_CATALOG_VERSION: Final = "1"
# The runtime-reachability framework / edge-kind / route-method / marker-symbol
# catalogs (codeclone/analysis/reachability.py).
RUNTIME_REACHABILITY_CATALOG_VERSION: Final = "1"
# The structural finding-kind catalog (codeclone/domain/findings.py).
STRUCTURAL_FINDINGS_CATALOG_VERSION: Final = "1"
# Statement-level unreachability (39Y Y9). Version "1" is ONE predicate over
# ONE graph: a statement cannot run exactly when its block is not reachable
# from ``CFG.entry`` by directed traversal of ``Block.successors``. There is no
# separate clause for code after a terminator and none for a literal guard —
# the norm CFG builder already expresses both structurally, by emitting the
# post-terminator tail as a block with no incoming edge and by suppressing the
# edge into a branch whose guard is a literal ``ast.Constant`` that forbids
# entry. Exception dispatch, ``finally`` routing and context-manager
# suppression are likewise ordinary edges, so traversal answers them too.
# ``BlockOrigin`` names a cause for the reader and is evidence only: the block
# is already decided unreachable before any origin is consulted, and no verdict
# depends on it. No value inference and no propagation: the moment a name
# lookup counts as evidence the rule stops being this declared predicate.
# The verdict set is stored per unit in the module-neutral cache payload, so
# this constant is an input of that lane's reuse profile
# (codeclone/cache/reuse.py) and a policy bump re-decides instead of serving the
# previous predicate's answers.
STATEMENT_REACHABILITY_POLICY_VERSION: Final = "1"
# Maximum number of inserted, deleted or replaced normalized statements between
# two units that still group as the ``near_miss`` clone tier (39Y Y8). Integer
# by contract: the tier carries no similarity score and no tunable floor. A
# distance of zero is the exact tier's business and never enters near_miss.
NEAR_MISS_MAX_EDIT_STATEMENTS: Final = 1
# The near-miss lane's own algorithm identity. Revision "1" was the 39Y Y8
# single-divergence head-scan construction and was never published as a
# constant; "2" is the sequence Levenshtein verdict (insert, delete and
# replace each cost exactly one edit; equal costs zero) together with the
# canonical DP-backtrace witness law — one documented total order over
# equal-cost forks, so which statement is reported as the edit is as
# deterministic as the distance itself. "3" adds the declared renamed token
# domain (the CxB composition): the same Levenshtein verdict and witness law
# run a second time over statement tokens canonicalized by the
# renamed_structure ordinal rules, each domain on its own deletion index,
# with a pair confirmable in both domains reported once in the y8 domain.
# Bumping this never touches the exact lane: BASELINE_FINGERPRINT_VERSION
# and the statement-token wire are unchanged, and the tier still reaches no
# baseline lane and no gate.
NEAR_MISS_ALGORITHM_REVISION: Final = "3"
# The renamed-structure lane's own algorithm identity (Wave C). Revision "1"
# is ordinal canonicalization: LOCAL and ATTRIBUTE ordinals in separate
# numbering spaces, binding identity scope-qualified before assignment,
# first-occurrence ordering with parameters seeded by declaration position,
# imported identities and unprovable names rigid, terminal callees literal
# across the whole unit, and the equality pattern preserved. The tier is an
# exact match in its own digest domain — O(n), no pairwise matcher, no
# similarity score. Bumping this never touches the exact lane:
# BASELINE_FINGERPRINT_VERSION is unchanged, and the tier reaches no baseline
# lane and no gate. It does touch the cache: the per-unit renamed digest and the
# renamed token sequence are stored in the module-neutral payload and their hash
# domains embed this revision, so the constant is an input of that lane's reuse
# profile (codeclone/cache/reuse.py). Without it a partially warm run would
# group digests of two generations against each other.
RENAMED_STRUCTURE_ALGORITHM_REVISION: Final = "1"
# The execution-state dictionary of the advisory tier containers
# (``findings.groups.near_miss`` / ``findings.groups.renamed_structure``).
# ``state`` is the primary witness of producer execution, and the dictionary
# is contractually significant (the ``novelty_reason`` precedent): adding a
# value is a contract change, not a serialization detail.
#
# - ``disabled``: the producer was never invoked. The container is exactly
#   ``{tier, state, algorithm_revision}`` — ``count`` is omitted entirely
#   (omission, not 0 and not null), because a tier that never ran has no
#   measurement to utter. ``algorithm_revision`` at ``disabled`` is the
#   *configured producer revision* — which algorithm the opt-in would run —
#   never evidence that it ran.
# - ``complete``: the producer ran to completion over the clone-eligible
#   population. The law: ``count=0`` MUST mean a completed measurement with
#   an empty result, never absence of measurement.
#
# Before this dictionary existed the containers stamped ``count: 0``
# unconditionally, making "never ran" indistinguishable from "ran and found
# nothing" (the empty-root-is-not-unmeasured class; benchmark pair T3-01 was
# misattributed through exactly that hole).
TIER_STATE_DISABLED: Final = "disabled"
TIER_STATE_COMPLETE: Final = "complete"

# 3.2 adds the two rule-3 fact families: per-class base resolution and
# per-method decorator evidence. Both gate the tri-state liveness verdict,
# so a cache that lacked them would make the verdict depend on cache state.
# It also carries the per-unit normalized statement sequence behind the
# ``near_miss`` tier (39Y Y8): grouping runs over units that a warm run serves
# straight off the wire, so a sequence that did not ride the cache would make a
# warm run report zero near-miss pairs. Everything this phase sanctions rides
# this one bump instead of adding a second.
#
# 3.3 carries the per-unit renamed-structure digest (Wave C) on the same
# reasoning: the digest is computed from the AST, a warm run never re-parses,
# and a unit served off a wire without it would make a warm run silently
# report zero renamed-structure groups.
#
# 3.4 carries the per-unit renamed-canonical statement sequence (the CxB
# composition), closing the same trap one lane over: the near-miss renamed
# token domain reads this sequence off the unit fact, so a warm run served
# off a 3.3 wire would silently report only y8-domain pairs. Its own key,
# absence rejects the entry, rejection just re-analyses the file.
#
# 3.7 combines three independently-authored cache-format changes that each
# reached "3.5"/"3.6" on their own branch; the merge carries all of them, so the
# digit advances once more to name the single combined generation. Three
# reasons, one truth:
#
# (a) Wave D widens the positional unit row by one column: index 7 stays the
# public ``cyclomatic_complexity`` (now the source-decision count) and a new
# trailing column carries the diagnostic ``cfg_cyclomatic_complexity``. Cached
# units also hold complexity computed by the pre-split CFG algorithm, so the
# bump forces every unit through the new counter instead of serving stale
# semantics off the wire; the widened row decodes strictly at ``{18}`` -- no
# legacy length is tolerated, a shorter generation is unloadable at this gate.
#
# (b) The cache trust envelope: the integrity checksum now covers the versioned
# pre-image ``{v, payload}`` instead of ``payload`` alone, so the generation
# gate ``v`` is inside the checksummed scope -- a migration/backup/edit-in-place
# that rewrites ``v`` without re-checksumming is refused (``INTEGRITY_FAILED``)
# rather than trusted as a payload it never covered under that mark. The on-disk
# envelope key was renamed ``sig`` -> ``checksum`` and the keyless "signature"
# vocabulary retired to checksum/integrity names, telling the truth that this is
# a corruption/desync integrity check and not authentication. The
# module-dependent reuse profile now versions the design-metrics algorithm
# revision and the security-surface / runtime-reachability / structural-findings
# detector catalogs directly, so a policy change in any of those lanes that does
# not coincide with a neutral-lane change can no longer serve a stale
# dependent-lane fact off a warm hit.
#
# (c) The cycle-honesty wave carries binding time and the PEP 810 laziness
# marker on every module dependency row (dependencies ``payload_schema`` "6").
# A warm run served off a pre-cycle wire would decode every edge as eager
# import_time and silently report a deferred cycle as critical -- the exact lie
# the wave removes -- so those rows are rejected and the file re-analysed.
#
# Every 3.4/3.5/3.6 cache is rejected at the version gate and re-analysed; there
# is no byte-stable path for the widened row, the checksummed scope, the
# key-name change, or the dependency-row schema, so the bump IS the
# compatibility guarantee.
#
# 3.8 carries the clone-artifact materialization witness (tier ruling T2,
# 2026-08-24): the neutral wire gains the mandatory ``mt`` key naming which
# opt-in artifact channels (``near_miss``, ``renamed_structure``) the writing
# extraction actually computed, and the ``us``/``uc``/``urs`` payload keys are
# emitted exactly when their channel is claimed. Under 3.7 the artifacts were
# computed unconditionally, so absence of a payload could only mean a stale
# entry and "absence rejects" was a complete law. Once disabled tiers stop
# paying for artifacts, the row needs a legal way to say "not materialized"
# that no reader can confuse with "materialized empty" — measured on 3.7:
# present-but-empty sequence rows load as OK, warm-hit, and report zero
# near-miss pairs where a cold run reports five. The witness is that legal
# form; decode rejects a row whose witness disagrees with its payload keys in
# either direction, and the neutral reuse gate demands witness == the running
# configuration's channels. 3.7 caches are rejected at the version gate and
# re-analysed — there is no byte-stable path for the mandatory key.
#
# 3.8 -> 4.0 is the only bump in this constant's history that changes the
# CONTAINER rather than the row: the analysis cache stops being a JSON monolith
# at ``.codeclone/cache.json`` and becomes a row-addressed SQLite store at
# ``.codeclone/db/cache.sqlite3``. The major digit moves because no 3.x reader
# and no 3.x file survive the move in any direction — there is nothing to
# migrate and nothing to reinterpret, only a different artifact at a different
# path. A 3.x cache is therefore never rejected at the version gate, because it
# is never opened: ``Cache._legacy_monolith_warning`` merely REPORTS the
# stranded JSON document and leaves it on disk, following the ``.cache_secret``
# precedent -- a file this tool no longer owns is not this tool's to delete.
# The bump records the generation break for anything that reads this constant
# to reason about compatibility.
#
# 4.0 -> 4.1 gives the api-surface lane the materialization witness the clone
# lane got at 3.8, and for the identical reason on the other lane: a row's
# ``api_surface`` payload is absent both when a module exports nothing and when
# no extraction looked at it, while the profile key was computed from
# ``bool(args.api_surface)`` and the workers materialized on
# ``not skip_metrics and args.api_surface``. Measured: one metrics-skipping run
# through either surface left rows keyed as api-collecting and empty, and the
# next full run reused them and reported ``public_symbols: 0`` against 5409 and
# ``breaking: 4949`` against 50. The mandatory ``amt`` key is the legal way for
# a row to say "did not collect"; decode rejects a row without it, so a 4.0 row
# is re-analysed rather than read as "collected, and empty". The row's meaning
# changed, so the generation moves with it.
#
# The same generation's api payload is what the collector admits under the
# language's visibility rule (``__all__`` first; a bare private module only
# when the run includes private modules): where a symbol is defined is not
# where it becomes observable, so privacy narrows nothing at collection and
# the external-reachability owner decides exposure per symbol afterwards. An
# unreleased build of this generation collected privacy-first, and this
# reader served its rows as "collected, empty" (measured: ``public_symbols``
# 9 cold, 2 warm). The dependent profile carries ``api_collection_policy`` so
# such a row misses; the number does not move for a build that never shipped.
#
# The same generation also carries the liveness-policy-v4 declaration fact on
# the dependent lane: ``dx``, the names a module's static ``__all__`` lists,
# beside the binding fact ``sb``. It joins 4.1 rather than opening 4.2 because
# one generation boundary was already open for every known incompatible row
# change of this wave; absence is the legal reading of a module that declares
# nothing, and a 4.1 row written before the key existed misses the dependent
# lane on LIVENESS_POLICY_VERSION ("3" -> "4") rather than decoding as
# "declares nothing".
#
# It is disposable acceleration state and never truth, so this constant reaches
# no report, no baseline and no content address: nothing downstream of a run
# changes value because the cache changed shape.
CACHE_VERSION: Final = "4.1"
# 3.0 -> 3.1: the ``metrics.families.health.summary.population`` value set
# changed. "complete" became "complete_nonempty" and "complete_empty" joined
# it, because one word was carrying two facts — a population that exists and
# was not read, and a scope holding no source file at all. The enum is
# wire-visible in every report artifact and in the HTML data attribute, so a
# reader that switches on it sees a value it has never been told about.
#
# The bump IS the compatibility guarantee here, exactly as for the cache
# above: ``check_report_v3_compatibility`` applies an *exact* policy, so a
# stored 3.0 report is refused rather than silently misread against the new
# value set. ``tests/test_report_honest_population.py`` pins the coupling —
# the enum cannot move again without this constant moving with it.
#
# 3.2 -> 3.3 (RULING 2026-09-01, external reachability): the ``dead_code``
# family gains a semantic state the old wire could not express. A symbol with
# no internal evidence that a consumer outside the repository could reach is
# neither a dead finding nor a live omission; it is uttered as its own record
# type in ``dead_code.unresolved`` (reason code, reachability state, witness,
# world contract, location), counted in ``summary.unresolved``, and every
# verdict in the family now names the world it was derived under in
# ``summary.world_contract``. Not a new value of an existing finding and not a
# confidence level: a reader that switched on the old wire would read the
# absence of a finding as "proven live", which is the ambiguity the state
# exists to end. Baseline schema, cache generation, module identity and the
# semantic identity generation stay where they are; the new payload enters the
# run identity through the observation lane's ``abstained`` rows and the
# realized ``world_contract`` parameter, not through a generation bump.
REPORT_SCHEMA_VERSION: Final = "3.3"
# The clone vocabulary of the report wire: what the document calls the family
# and what a clone group calls its kind. These are facts about the payload, not
# a layer's opinion about it, and they live here because of who has to read
# them: the producer of the document is in the analysis ring and the renderers
# are in the presentation ring, and the only rings both may import are this one
# and utils. Declared beside a producer or a door, the vocabulary is reachable
# from one side only, and the other side restates it — which is how one
# document came to state both "seventeen suppressed" and "zero".
#
# These names are NOT the baseline's lane identities. ``clones.functions`` and
# ``clones.blocks`` in ``baseline/lanes.py`` are spelled alike, feed the
# container digest, and are versioned on their own; deriving one from the other
# would put two contracts under one value.
CLONE_KIND_FUNCTION: Final = "function"
CLONE_KIND_BLOCK: Final = "block"
CLONE_KIND_SEGMENT: Final = "segment"
FAMILY_CLONES: Final = "clones"
# The address of the finding-group container, and the shape of what is inside
# it. Both sides of the wire need these: the producer writes the container in
# the analysis ring, and eleven readers -- renderers, MCP surfaces, the CLI
# changed-scope gate, the derived overview -- walked it from four rings that
# share only this module and ``utils``. Every one of them spelled the five
# container keys itself, and one had already lost a family from a published
# total that way, so the vocabulary lives here and the walk lives in
# ``codeclone.utils.finding_groups``.
FINDING_GROUPS_PATH: Final[tuple[str, ...]] = ("findings", "groups")
# The container keys of the baseline-tracked families, in the order every
# consumer presents them. This is the document's spelling, which is NOT the
# finding-family vocabulary: a group says ``family: "clone"`` and its container
# is keyed ``clones``. ``domain.findings.BASELINE_TRACKED_FAMILIES`` owns the
# family values; the two are pinned to each other in
# ``tests/test_finding_groups_owner.py`` so neither can drift alone.
#
# The advisory tiers are deliberately absent. They key sibling containers under
# the same root, reach no baseline lane, and must never widen a published
# total.
GROUP_KEY_STRUCTURAL: Final = "structural"
GROUP_KEY_DEAD_CODE: Final = "dead_code"
GROUP_KEY_DESIGN: Final = "design"
GROUP_KEY_AUTHORITY: Final = "authority"
BASELINE_TRACKED_GROUP_KEYS: Final[tuple[str, ...]] = (
    FAMILY_CLONES,
    GROUP_KEY_STRUCTURAL,
    GROUP_KEY_DEAD_CODE,
    GROUP_KEY_DESIGN,
    GROUP_KEY_AUTHORITY,
)
# The clone family holds three sibling lists; every other family nests its
# groups under one key. That asymmetry is the whole reason a hand-written walk
# gets the container wrong.
CLONE_GROUP_BUCKET_KEYS: Final[tuple[str, ...]] = ("functions", "blocks", "segments")
NESTED_GROUPS_KEY: Final = "groups"
# The key under which the clone family nests its suppressed buckets, and the
# full document path of that container. This is the single site in the codebase
# that spells either: a consumer navigating there takes the address from here
# instead of restating it, so a rename moves every reader at once.
SUPPRESSED_CONTAINER_KEY: Final = "suppressed"
SUPPRESSED_CONTAINER_PATH: Final[tuple[str, ...]] = (
    *FINDING_GROUPS_PATH,
    FAMILY_CLONES,
    SUPPRESSED_CONTAINER_KEY,
)
# Human-readable provenance stamp for a metrics artifact, reported to the
# operator and nothing more. It is NOT the compatibility authority and must not
# be described as one: no code branches on it. Whether a stored artifact may be
# compared with current values is decided in exactly one place,
# ``MetricsBaseline.verify_compatibility`` — per-lane ``algorithm_revision`` and
# ``payload_schema`` first (a stale design-metric lane raises
# INCOMPATIBLE_METRICS_CONTRACT), then ``BASELINE_SCHEMA_VERSION`` and the
# Python tag. That check is finer than this string: it names the lane that
# moved instead of failing the whole artifact.
#
# 1.3 records that the design-metric lanes moved to
# DESIGN_METRICS_ALGORITHM_REVISION "2"; the refusal to diff 1.2 values against
# current ones is delivered by the lane revision, not by this constant.
METRICS_BASELINE_SCHEMA_VERSION: Final = "1.3"
ENGINEERING_MEMORY_SCHEMA_VERSION: Final = "1.7"
# Semantic retrieval index. Derived, rebuildable sidecar — NOT
# covered by ENGINEERING_MEMORY_SCHEMA_VERSION. Bump to invalidate the index
# on an incompatible projection/row-format change (forces a rebuild, not a
# SQLite migration). v3 (Stage 2) adds the ``source_revision`` row column; the
# one-time full rebuild is actually forced by the backend schema check, not by
# this constant — it stays in sync so the reported ``index_version`` is honest.
SEMANTIC_INDEX_FORMAT_VERSION: Final = "3"
# Global escape hatch for the cheap per-row ``source_revision`` key (Stage 2
# incremental sourcing). Bump to invalidate EVERY semantic lane at once on a
# cross-cutting projection/row-format change. Per-source projection versions are
# folded into each source's content token instead, so a single-lane projector
# change re-embeds only that lane (see ``memory.semantic.projection``).
SEMANTIC_PROJECTION_REVISION_VERSION: Final = "1"
# Per-source projection versions folded into each source's ``source_revision``
# content token. Trajectory reuses TRAJECTORY_PROJECTION_VERSION below.
MEMORY_PROJECTION_VERSION: Final = "memory-v1"
AUDIT_PROJECTION_VERSION: Final = "audit-v1"
PATCH_TRAIL_SCHEMA_VERSION: Final = "1"
# Platform observability sqlite store (.codeclone/db/platform_observability.sqlite3):
# a runtime-profiling plane separate from audit/memory. Bump on an incompatible
# observability schema change.
PLATFORM_OBSERVABILITY_SCHEMA_VERSION: Final = "1.1"

# Memory-derived projection/derivation versions. NOT persistence schema
# versions: bump to supersede previously derived rows on an incompatible
# projection/scoring/distillation change (re-projection, not a SQLite
# migration). Defined here so all version constants live in one place; the
# owning modules re-export these names.
TRAJECTORY_PROJECTION_VERSION: Final = "trajectory-v3"
TRAJECTORY_PROJECTION_VERSION_V1: Final = "trajectory-v1"
TRAJECTORY_QUALITY_SCORE_VERSION: Final = "2"
EXPERIENCE_DISTILLATION_VERSION: Final = "experience-v1"
# IDE governance HMAC attestation protocol version (IDE Memory channels).
IDE_GOVERNANCE_PROTOCOL_VERSION: Final = 2

# Corpus analytics store (.codeclone/analytics/corpus_clustering.sqlite3) and
# derived export/representation contracts. Bump independently from memory schema.
CORPUS_ANALYTICS_STORE_SCHEMA_VERSION: Final = "1.2"
CORPUS_EXPORT_SCHEMA_VERSION: Final = "1.3"
CORPUS_PROFILE_MANIFEST_SCHEMA_VERSION: Final = "1"
CORPUS_CONTROL_PLANE_CONTRACT_VERSION: Final = "1.0"
CORPUS_REPRESENTATION_CONTRACT_VERSION: Final = "3"
CORPUS_NORMALIZER_VERSION: Final = "1"
CORPUS_EMBEDDING_CONTRACT_VERSION: Final = "2"
CORPUS_AGENT_LABEL_CONTRACT_VERSION: Final = "1"
CORPUS_PARTITION_MAP_VERSION: Final = "1"

DEFAULT_COMPLEXITY_THRESHOLD: Final = 20
DEFAULT_COUPLING_THRESHOLD: Final = 10
DEFAULT_COHESION_THRESHOLD: Final = 4
DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD: Final = 20
DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD: Final = 10
DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD: Final = 4
DEFAULT_HEALTH_THRESHOLD: Final = 60
DEFAULT_ROOT: Final = "."
DEFAULT_MIN_LOC: Final = 10
DEFAULT_MIN_STMT: Final = 6
DEFAULT_BLOCK_MIN_LOC: Final = 20
DEFAULT_BLOCK_MIN_STMT: Final = 8
DEFAULT_SEGMENT_MIN_LOC: Final = 20
DEFAULT_SEGMENT_MIN_STMT: Final = 10
DEFAULT_PROCESSES: Final = 4
DEFAULT_MAX_CACHE_SIZE_MB: Final = 256
DEFAULT_MAX_BASELINE_SIZE_MB: Final = 5
DEFAULT_COVERAGE_MIN: Final = 50
DEFAULT_BASELINE_PATH: Final = "codeclone.baseline.json"

# Complexity risk bands. Reviewed and kept unchanged through the Wave D
# source-decision recalibration (see the health block below).
#
# A band is not a gate threshold. A gate threshold is read at report time over
# stored facts; a band CLASSIFIES at extraction, and the resulting word is
# stored per unit as ``units[].risk`` in the module-neutral cache payload, which
# a warm run serves verbatim. Both edges are therefore inputs of that lane's
# reuse profile (codeclone/cache/reuse.py). Without that binding a
# recalibration - admissible only through the independent blind benchmark the
# score-change law requires - would leave every warm-cache user's risk
# classification exactly as it was, under the new calibration's name.
COMPLEXITY_RISK_LOW_MAX: Final = 10
COMPLEXITY_RISK_MEDIUM_MAX: Final = 20
# Coupling risk bands, derived from the measured CBO distribution of a
# reference corpus (915 classes; avg 1.44, p50 0, p90 4, p95 7, p99 14,
# max 27) under the resolution-gated edge contract in ``metrics/coupling.py``.
# Both edges are percentiles of that distribution, so a class leaves a band
# only by being more coupled than a declared share of real classes:
#   low    -- the bulk, at or below the upper decile (p90);
#   medium -- the decile-to-ventile band (p90 .. p95);
#   high   -- the upper ventile, the 5% tail.
# p90 and p95 measured identically (4 and 7) on the production-only subset of
# the same corpus, so the edges describe the shape of the distribution rather
# than the filter applied to it. Owning test:
# tests/test_metrics_health_recalibration.py, which recomputes both percentiles
# from the recorded histogram.
#
# Like the complexity bands above, these classify at extraction: the words are
# stored as ``class_metrics[].risk_coupling`` and ``.risk_cohesion`` in the
# module-DEPENDENT cache payload and are rehydrated verbatim, so all three edges
# are inputs of that lane's reuse profile (codeclone/cache/reuse.py) and of no
# other. A band move re-derives the class rows and spares the neutral lane.
COUPLING_RISK_LOW_MAX: Final = 4
COUPLING_RISK_MEDIUM_MAX: Final = 7
COHESION_RISK_MEDIUM_MAX: Final = 3

# Coupling health dimension: four bounded terms whose weights spend exactly the
# 100 points of the dimension, and the complexity dimension above uses the same
# four-term shape for the same reason. The complexity formula it replaced
# (100 - avg*2.5 - max*1.2 - high*8) was a function of the single worst
# function: on the measured post-norm distribution of this repository one
# 34-complexity function alone spent 40.8 points and five high-risk functions
# spent 40, pinning the dimension at 12 while the typical function sits at
# complexity 3. Its reference shares are MEASURED, not chosen.
#
# Wave D re-measured them for the source-decision metric
# (COMPLEXITY_ALGORITHM_REVISION): the same population (production functions
# outside tests/ and benchmarks/) now measures n=5438, avg 3.90,
# p90/p95/p99 = 8/11/21, max 98, with 321 above COMPLEXITY_RISK_LOW_MAX
# (59.03 per mille) and 56 above COMPLEXITY_RISK_MEDIUM_MAX (10.30 per mille).
# The two permilles below are a GENERATED calibration artifact, not hand
# numbers: they are the output of the calibration procedure
# (``tests/_complexity_calibration.py``) over its pinned reference
# distribution, and ``tests/test_complexity_calibration.py`` reds if either
# constant stops equalling that output. The retired Y9-CFG values were 28 and
# 1 (from n=5194, 146 above 10, 5 above 20). The complexity BANDS are
# unchanged: 10 and 20 were reviewed and kept, and the recalibration touched
# only these two permilles — never fail_health, never the bands, never the
# outlier term.
#
# Bounding is the point. The previous coupling formula
# (100 - avg*7 - max*2 - high*8) let one 27-collaborator class cost 54 points
# and 16 high-risk classes cost 128, which pinned the dimension at 0 on the
# reference distribution: it measured a single outlier, not the project, and
# could not move when the code improved.
#
# Two terms are shares rather than counts, so the dimension does not punish a
# project for being large; the reference share of each is implied by the band
# percentile above (a p90 edge leaves 100 per mille above it, a p95 edge 50),
# so bands and score share one derivation instead of two measurements.
HEALTH_COMPLEXITY_TYPICAL_WEIGHT: Final = 30
HEALTH_COMPLEXITY_ELEVATED_WEIGHT: Final = 30
HEALTH_COMPLEXITY_EXTREME_WEIGHT: Final = 30
HEALTH_COMPLEXITY_OUTLIER_WEIGHT: Final = 10
# Generated by the calibration procedure (tests/_complexity_calibration.py:
# reference_permilles()); pinned by tests/test_complexity_calibration.py. Do
# not hand-edit — recalibrate through the procedure with a fresh measurement
# and maintainer ratification.
HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE: Final = 59
HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE: Final = 10
HEALTH_COMPLEXITY_TAIL_SATURATION_MULTIPLE: Final = 4
HEALTH_COMPLEXITY_OUTLIER_SATURATION_MULTIPLE: Final = 3
HEALTH_COUPLING_TYPICAL_WEIGHT: Final = 30
HEALTH_COUPLING_ELEVATED_WEIGHT: Final = 30
HEALTH_COUPLING_EXTREME_WEIGHT: Final = 30
HEALTH_COUPLING_OUTLIER_WEIGHT: Final = 10
HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE: Final = 100
HEALTH_COUPLING_EXTREME_REFERENCE_PERMILLE: Final = 50
# A tail this many times its reference share spends that term completely: at
# 4x, 40% of classes are above the low band and 20% above the medium band, so
# elevated coupling is the dominant mode rather than a tail. It also places the
# reference distribution at a quarter of each tail term, leaving both room to
# worsen and room to improve.
HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE: Final = 4
# The single-worst-class term saturates once the maximum reaches this multiple
# of the high-risk band edge above it. Past that point the dimension stops
# responding to one class's magnitude, which is exactly the defect this
# replaces.
HEALTH_COUPLING_OUTLIER_SATURATION_MULTIPLE: Final = 3
# Per-cycle penalty for an ``import_cycle`` — a cycle whose import-time edge
# subgraph still cycles, so it can crash the interpreter at import. Unchanged
# since the dimension was written; the cycle-policy split narrowed WHICH cycles
# it counts (import ones) without moving its value.
HEALTH_DEPENDENCY_CYCLE_PENALTY: Final = 25
# Per-cycle penalty for a ``deferred_cycle`` — real, but unable to crash at
# import because only deferred, lazy, or typing edges close it.
#
# CANDIDATE VALUE, DELIBERATELY EQUAL TO THE IMPORT PENALTY. The cycle-policy
# split exists to create this seam, not to move the score: at 25 the dependency
# dimension is identical to the pre-split behaviour for every repository.
# Lowering it is a user-facing score change and is therefore governed by the
# project's score-change law — it may only be revised by a separate calibration
# task carrying an independent BLIND benchmark over at least five frozen
# external repositories pinned to commit SHAs. Do not tune it here, and never
# from CodeClone's own self-score.
HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY: Final = 25
HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY: Final = 4
HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER: Final = 2.0
HEALTH_DEPENDENCY_DEPTH_P95_MARGIN: Final = 1

HEALTH_WEIGHTS: Final[dict[str, float]] = {
    "clones": 0.25,
    "complexity": 0.20,
    "coupling": 0.10,
    "cohesion": 0.15,
    "dead_code": 0.10,
    "dependencies": 0.10,
    "coverage": 0.10,
}


class ExitCode(IntEnum):
    SUCCESS = 0
    CONTRACT_ERROR = 2
    GATING_FAILURE = 3
    INTERNAL_ERROR = 5


REPOSITORY_URL: Final = "https://github.com/orenlab/codeclone"
ISSUES_URL: Final = "https://github.com/orenlab/codeclone/issues"
DOCS_URL: Final = "https://orenlab.github.io/codeclone/"


def cli_help_epilog() -> str:
    return "\n".join(
        [
            "Exit codes:",
            "  0  Success.",
            "  2  Contract error: untrusted or invalid baseline, invalid output",
            "     configuration, incompatible versions, or unreadable sources in",
            "     CI/gating mode.",
            "  3  Gating failure: new clones, threshold violations, or metrics",
            "     quality gate failures.",
            "  5  Internal error: unexpected exception.",
            "",
            f"Repository: {REPOSITORY_URL}",
            f"Issues:     {ISSUES_URL}",
            f"Docs:       {DOCS_URL}",
        ]
    )


#: What a run actually observed of the population it found. Six of the seven
#: health dimensions are counters of *observed* debt, so an unobserved
#: population scores exactly like a clean one — "we did not measure" and "we
#: measured, it is clean" used to be bit-identical. This names them apart, in
#: the same shape the project already uses for baseline-relative novelty: a
#: fact that is absent is reported as absent, never as a favourable answer.
#:
#: Four states, not three. ``unmeasured`` used to carry two unrelated facts: a
#: population that exists and was not read (a broken run), and a scope that
#: holds no source file at all (a complete measurement of an empty area). They
#: need different words because they need different remediations — look for
#: the dead worker, versus look at the analysis root — and because only the
#: first one is a fault.
#:
#: * ``complete_nonempty`` — every file found was read, and there were files.
#: * ``complete_empty``    — the scope holds no source file; nothing was lost.
#: * ``partial``           — files were found, some read, some not.
#: * ``unmeasured``        — files exist (or the lane never ran) and none were
#:                           observed. The only state that means "no evidence".
#:
#: Lives here, in the dependency-free contract ring, rather than beside the
#: models: health, the gates, the baseline publisher and the CLI surfaces all
#: decide on it, and the surfaces may not import the model store at all. A
#: fact every ring must consult belongs in the ring every ring may reach.
HealthPopulation = Literal[
    "complete_nonempty",
    "complete_empty",
    "partial",
    "unmeasured",
]

#: The states over which a health number exists at all. Derived once, here,
#: because four states collapse to this binary question at every presenting
#: surface, and a surface that re-derives it from ``score is None`` reads the
#: consequence instead of the fact — which is why the two refusals could not
#: be worded apart before.
_POPULATIONS_WITH_A_SCORE: Final[frozenset[str]] = frozenset(
    {"complete_nonempty", "partial"}
)


def observed_population(
    *,
    files_found: int,
    files_analyzed_or_cached: int,
) -> HealthPopulation:
    """Name what the run observed, from the two counters and nothing else.

    The sole computer of this fact. Health, the gates, the baseline publisher
    and the CLI all consult it; a second implementation in any one of them
    would be two semantics for one word.

    Derived from two counters, never configured: no threshold is involved, so
    there is nothing here that can drift the way a calibrated constant can.
    The four states are exhaustive and mutually exclusive by construction —
    the first branch splits on whether anything was read, and each side then
    splits on whether there was anything to read.
    """

    if files_analyzed_or_cached <= 0:
        # Nothing was read. Which of the two absences it is depends entirely
        # on whether there was anything to read; conflating them is the defect
        # this function exists to remove.
        return "complete_empty" if files_found <= 0 else "unmeasured"
    if files_analyzed_or_cached < files_found:
        return "partial"
    return "complete_nonempty"


def population_carries_score(population: HealthPopulation) -> bool:
    """True when a health number exists for this population.

    One owner for the question every presenting surface asks. ``partial`` is
    included: a truncated run measured something, and naming the truncation is
    a different job from withholding the number. The two excluded states both
    withhold it — for different reasons, which is why they stay
    distinguishable in ``population`` itself rather than collapsing into a
    missing key.
    """

    return population in _POPULATIONS_WITH_A_SCORE


#: The states in which the run observed its whole input universe. The second
#: binary collapse of the four population states, and a different one:
#: ``population_carries_score`` asks whether a number exists over what was
#: read, this asks whether what was read is everything there was. The two
#: disagree on ``partial`` and on ``complete_empty``, which is why each
#: collapse carries its own named owner instead of a surface inferring one
#: from the other.
_POPULATIONS_WITH_AN_OBSERVED_UNIVERSE: Final[frozenset[str]] = frozenset(
    {"complete_nonempty", "complete_empty"}
)


def population_universe_observed(population: HealthPopulation) -> bool:
    """True when the run observed every member of the population it found.

    One owner for the question a set-theoretic comparison must ask before it
    runs. A membership diff manufactures facts from absence: a member that
    went unobserved is indistinguishable from a member that was removed, so a
    ``partial`` run reads each unread module as a torn-down API and an
    ``unmeasured`` run reads the whole baseline that way (`B8`, `G4`).

    ``complete_empty`` is included, and that is the other boundary, not an
    accident: a scope that genuinely holds no source file anymore has really
    removed what the baseline remembers, and withholding that comparison
    would silence a true signal. Absence of observation and observation of
    absence are different facts; only ``population`` tells them apart.
    """

    return population in _POPULATIONS_WITH_AN_OBSERVED_UNIVERSE


__all__ = [
    "ADOPTION_COVERAGE_POLICY_VERSION",
    "API_SURFACE_SIGNATURE_VERSION",
    "AUDIT_PROJECTION_VERSION",
    "AUTHORITY_ANALYSIS_REVISION",
    "AUTHORITY_REGISTRY_VERSION",
    "BASELINE_FINGERPRINT_VERSION",
    "BASELINE_LANE_DESCRIPTOR_VERSION",
    "BASELINE_LANE_DIGEST_DOMAIN",
    "BASELINE_ROOT_DIGEST_DOMAIN",
    "BASELINE_SCHEMA_VERSION",
    "BASELINE_TRACKED_GROUP_KEYS",
    "CACHE_VERSION",
    "CANONICAL_MODEL_REVISION",
    "CANONICAL_OBJECT_IDENTITY_VERSION",
    "CANONICAL_WIRE_REVISION",
    "CLONE_GROUP_BUCKET_KEYS",
    "CLONE_KIND_BLOCK",
    "CLONE_KIND_FUNCTION",
    "CLONE_KIND_SEGMENT",
    "COHESION_RISK_MEDIUM_MAX",
    "COMPLEXITY_ALGORITHM_REVISION",
    "COMPLEXITY_RISK_LOW_MAX",
    "COMPLEXITY_RISK_MEDIUM_MAX",
    "CONTRACT_IR_VERSION",
    "CORPUS_AGENT_LABEL_CONTRACT_VERSION",
    "CORPUS_ANALYTICS_STORE_SCHEMA_VERSION",
    "CORPUS_CONTROL_PLANE_CONTRACT_VERSION",
    "CORPUS_EMBEDDING_CONTRACT_VERSION",
    "CORPUS_EXPORT_SCHEMA_VERSION",
    "CORPUS_NORMALIZER_VERSION",
    "CORPUS_PARTITION_MAP_VERSION",
    "CORPUS_PROFILE_MANIFEST_SCHEMA_VERSION",
    "CORPUS_REPRESENTATION_CONTRACT_VERSION",
    "COUPLING_RISK_LOW_MAX",
    "COUPLING_RISK_MEDIUM_MAX",
    "DEFAULT_BASELINE_PATH",
    "DEFAULT_BLOCK_MIN_LOC",
    "DEFAULT_BLOCK_MIN_STMT",
    "DEFAULT_CACHE_PATH",
    "DEFAULT_COHESION_THRESHOLD",
    "DEFAULT_COMPLEXITY_THRESHOLD",
    "DEFAULT_COUPLING_THRESHOLD",
    "DEFAULT_COVERAGE_MIN",
    "DEFAULT_HEALTH_THRESHOLD",
    "DEFAULT_HTML_REPORT_PATH",
    "DEFAULT_JSON_REPORT_PATH",
    "DEFAULT_MARKDOWN_REPORT_PATH",
    "DEFAULT_MAX_BASELINE_SIZE_MB",
    "DEFAULT_MAX_CACHE_SIZE_MB",
    "DEFAULT_MIN_LOC",
    "DEFAULT_MIN_STMT",
    "DEFAULT_PROCESSES",
    "DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD",
    "DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD",
    "DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD",
    "DEFAULT_ROOT",
    "DEFAULT_SARIF_REPORT_PATH",
    "DEFAULT_SEGMENT_MIN_LOC",
    "DEFAULT_SEGMENT_MIN_STMT",
    "DEFAULT_TEXT_REPORT_PATH",
    "DESIGN_METRICS_ALGORITHM_REVISION",
    "DOCS_URL",
    "ENGINEERING_MEMORY_SCHEMA_VERSION",
    "EXPERIENCE_DISTILLATION_VERSION",
    "FAMILY_CLONES",
    "FINDING_GROUPS_PATH",
    "FUNCTION_RELATIONSHIP_ALGORITHM_REVISION",
    "GATE_ALGORITHM_REVISION",
    "GATE_LANE_MATRIX_VERSION",
    "GROUP_KEY_AUTHORITY",
    "GROUP_KEY_DEAD_CODE",
    "GROUP_KEY_DESIGN",
    "GROUP_KEY_STRUCTURAL",
    "HEALTH_ALGORITHM_REVISION",
    "HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE",
    "HEALTH_COMPLEXITY_ELEVATED_WEIGHT",
    "HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE",
    "HEALTH_COMPLEXITY_EXTREME_WEIGHT",
    "HEALTH_COMPLEXITY_OUTLIER_SATURATION_MULTIPLE",
    "HEALTH_COMPLEXITY_OUTLIER_WEIGHT",
    "HEALTH_COMPLEXITY_TAIL_SATURATION_MULTIPLE",
    "HEALTH_COMPLEXITY_TYPICAL_WEIGHT",
    "HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE",
    "HEALTH_COUPLING_ELEVATED_WEIGHT",
    "HEALTH_COUPLING_EXTREME_REFERENCE_PERMILLE",
    "HEALTH_COUPLING_EXTREME_WEIGHT",
    "HEALTH_COUPLING_OUTLIER_SATURATION_MULTIPLE",
    "HEALTH_COUPLING_OUTLIER_WEIGHT",
    "HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE",
    "HEALTH_COUPLING_TYPICAL_WEIGHT",
    "HEALTH_DEPENDENCY_CYCLE_PENALTY",
    "HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY",
    "HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER",
    "HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY",
    "HEALTH_DEPENDENCY_DEPTH_P95_MARGIN",
    "HEALTH_INPUT_MANIFEST_VERSION",
    "HEALTH_WEIGHTS",
    "IDE_GOVERNANCE_PROTOCOL_VERSION",
    "ISSUES_URL",
    "LIVENESS_POLICY_VERSION",
    "MEMORY_PROJECTION_VERSION",
    "METRICS_BASELINE_SCHEMA_VERSION",
    "MODULE_IDENTITY_VERSION",
    "NEAR_MISS_ALGORITHM_REVISION",
    "NEAR_MISS_MAX_EDIT_STATEMENTS",
    "NESTED_GROUPS_KEY",
    "OBSERVATION_DIGEST_VERSION",
    "OBSERVER_VOCABULARY_VERSION",
    "PATCH_TRAIL_SCHEMA_VERSION",
    "PLATFORM_OBSERVABILITY_SCHEMA_VERSION",
    "PORTABLE_PATH_PROFILE_VERSION",
    "RENAMED_STRUCTURE_ALGORITHM_REVISION",
    "REPORT_ANALYSIS_FACTS_DIGEST_DOMAIN",
    "REPORT_ANALYSIS_IDENTITY_DOMAIN_V2",
    "REPORT_COMPARISON_DIGEST_DOMAIN",
    "REPORT_COMPARISON_IDENTITY_DOMAIN_V2",
    "REPORT_ENVELOPE_DIGEST_DOMAIN",
    "REPORT_EVALUATION_DIGEST_DOMAIN",
    "REPORT_EVALUATION_IDENTITY_DOMAIN_V2",
    "REPORT_FAMILY_DIGEST_DOMAIN_V2",
    "REPORT_RUN_IDENTITY_TIER",
    "REPORT_SCHEMA_VERSION",
    "REPORT_SEMANTIC_IDENTITY_VERSION",
    "REPOSITORY_URL",
    "RUNTIME_REACHABILITY_CATALOG_VERSION",
    "SECURITY_SURFACE_CATALOG_VERSION",
    "SEMANTIC_EVENT_VERSION",
    "SEMANTIC_INDEX_FORMAT_VERSION",
    "SEMANTIC_PROJECTION_REVISION_VERSION",
    "SOURCE_KIND_POLICY_VERSION",
    "STATEMENT_REACHABILITY_POLICY_VERSION",
    "STORAGE_SCHEMA_REVISION",
    "STRUCTURAL_FINDINGS_CATALOG_VERSION",
    "SUPPRESSED_CONTAINER_KEY",
    "SUPPRESSED_CONTAINER_PATH",
    "TIER_STATE_COMPLETE",
    "TIER_STATE_DISABLED",
    "TRAJECTORY_PROJECTION_VERSION",
    "TRAJECTORY_PROJECTION_VERSION_V1",
    "TRAJECTORY_QUALITY_SCORE_VERSION",
    "WIRE_VERSION",
    "ExitCode",
    "HealthPopulation",
    "cli_help_epilog",
    "population_universe_observed",
]
