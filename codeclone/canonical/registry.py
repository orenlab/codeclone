# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical field declaration registry — the structural pin chosen by the
maintainer (2026-08-13): every canonical field is declared with its
epistemic class, owner, and wire obligation, and the projector emits only
declared fields.  An undeclared derived field is not something a test
catches — it is something that cannot be written.

Field classes follow the ratified three-class epistemics:

* ``analysis_fact`` — a producer established it; stored in the run snapshot.
* ``contract_derived_semantic`` — purely derivable from canonical facts plus
  a versioned contract, but participates in identity, ordering, selection,
  compatibility, or public addressing; its formula has exactly one versioned
  authority even when the value is not stored.
* ``representation_projection`` — derivable and semantically inert; never
  stored, only a representation convenience.

The wire order of fact families is born mechanically from this registry —
sorted family names, no manual tail (facts-order sanction, 2026-08-13):
declared field order exists only where earlier bytes are required to
interpret later bytes, and fact families have no such dependency.

Corpus ratios in this module (``2 379/2 379 @ 95e4210b, 2026-08-30``) are
DATED OBSERVATIONS of one corpus at one revision, never invariants.  They
record what a key was measured to do on a population; they do not claim
what it does now.  Every one of them moved between ratification and
2026-08-30 (F1 17 561 → 20 001 rows, F2 2 091 → 2 379, F4 12 971 → 14 827,
F10 387 → 406), because the population moves with the tree — so an
undated ratio silently becomes a false statement about the current run,
which is exactly what these stamps exist to prevent.  The invariant the
ratios were introduced to support — *the key is total on its family* — is
not documentation at all: ``model._unique_by_key`` proves it on every
ingest of every corpus, and ``test_canonical_wire_freeze_corpus`` executes
it against real producer output.  Re-derive a ratio by running the
analyzer at the stamped revision; do not update the number in place
without re-stamping it.

Not every declared attribute is enforcement, and the opening claim holds
only for the wire obligation.  ``field``, ``wire``, ``stored`` and
``wire_shape`` are read by the accessors below, so an undeclared wire
column genuinely cannot be written.  ``category``, ``owner``,
``derivation`` and ``public_handle`` have NO production reader (measured
2026-08-30 by AST over the tree: ``category`` and ``derivation`` have no
reader at all; ``owner`` and ``public_handle`` only in
``tests/test_canonical_identity``).  A wrong epistemic class or a wrong
formula owner is therefore narration that nothing can catch.  Giving
them a consumer is a production decision, not a comment fix — do not
read the opening paragraph as if they were already enforced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from codeclone.canonical.grammar import (
    require_analysis_wire_families,
    require_comparison_families,
    require_evaluation_families,
)

ANALYSIS_FACT: Final = "analysis_fact"
CONTRACT_DERIVED: Final = "contract_derived_semantic"
REPRESENTATION: Final = "representation_projection"


@dataclass(frozen=True, slots=True)
class FieldDeclaration:
    """One canonical field: who owns it, what it is, and where it may appear.

    ``wire_shape`` names the column's wire form: ``"column"`` is a plain
    equal-length column; ``"sparse_bool_positions"`` is a boolean written as
    a strictly increasing list of true row positions, omitted when no row is
    true (F-3 §7.6 rule 3 — omitted list means no trues, so absence and
    emptiness mean the same thing and rule 1 omits the default).
    """

    field: str
    category: str
    owner: str
    derivation: str
    stored: bool
    wire: bool
    public_handle: bool = False
    wire_shape: str = "column"


# Fact families of the wave-1 canonical subset.  Keys are the wire table
# names; the wire emits them in sorted(key) order — mechanically, from this
# mapping, never from a hand-written list.
FACT_FAMILY_FIELDS: Final[dict[str, tuple[FieldDeclaration, ...]]] = {
    # F3 (wave 4): key (scope, feature) — 2 614/2 614 unique at
    # ratification, 2 671/2 671 @ 95e4210b 2026-08-30; the scope is the
    # ratified tagged ScopeRef over
    # MODULE | FILE (ruling 2026-08-24 §2), never a polymorphic string.
    "adoption_counts": (
        FieldDeclaration(
            "denominator",
            ANALYSIS_FACT,
            "adoption_coverage_producer",
            "observed population count; payload, never key (zero-"
            "denominator scopes are dropped by the producer — absence "
            "already means unmeasured, so the family floor is 1)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "feature",
            ANALYSIS_FACT,
            "adoption_coverage_producer",
            "closed vocabulary (ADOPTION_FEATURES); key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "numerator",
            ANALYSIS_FACT,
            "adoption_coverage_producer",
            "observed adopted count; zero is MEASURED here (16 of 46 "
            "corpus rows — unlike the F2 floor); payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "scope",
            ANALYSIS_FACT,
            "adoption_coverage_producer",
            "key component: tagged ScopeRef MODULE | FILE (ruling §2) — "
            "914 module / 9 file scopes at ratification, 933 / 9 @ "
            "95e4210b 2026-08-30, zero unresolvable throughout; the "
            "variant IS identity",
            stored=True,
            wire=True,
        ),
    ),
    # AnalysisPopulation (RULING-2026-08-31 §3): the run-level execution
    # population singleton — ONE record per analysis snapshot (record wire
    # member, the F9 shape), never a row family.  The five-state law and
    # the zero-only-as-measurement law ride the model's closed vocabulary
    # (PRODUCER_EXECUTION_STATES); the ratified receipts columns join with
    # the producer wiring that can witness them (their zero today would be
    # fabricated — exactly what the hard law forbids).
    "analysis_population": (
        FieldDeclaration(
            "analysis_mode",
            ANALYSIS_FACT,
            "analysis_execution_producer",
            "realized analysis profile mode as the run pronounced it "
            "(meta.analysis_mode); non-empty string payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "analysis_profile",
            ANALYSIS_FACT,
            "analysis_execution_producer",
            "realized profile parameters: sorted unique (name, "
            "non-negative int) pairs — observed request, not policy "
            "authority (policy contracts are I2-C territory)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "producer_states",
            ANALYSIS_FACT,
            "analysis_execution_producer",
            "sorted unique (family, state) pairs; state is the closed "
            "five-state vocabulary (PRODUCER_EXECUTION_STATES), family "
            "names are the run's own pronouncement — meaning owned by "
            "the future producer registry (identity ruling I1)",
            stored=True,
            wire=True,
        ),
    ),
    # F5 (wave 4, ratified form): key (SYMBOL, canonical_signature_variant);
    # one owner of the canonical signature identity — parameters and return
    # enter the variant by contract, never a bare (FILE, symbol,
    # returns_digest) key.
    "api_symbols": (
        FieldDeclaration(
            "parameters",
            ANALYSIS_FACT,
            "api_surface_producer",
            "ordered signature parameters; variant preimage component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "returns_digest",
            ANALYSIS_FACT,
            "api_surface_producer",
            "return digest under ccapi1:sig; variant preimage component "
            "(empty wire string spells the producer's absence)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "signature_variant",
            CONTRACT_DERIVED,
            "api_signature_identity_contract.v1",
            "sha256 over (signature version, arity, parameters, returns)",
            stored=False,
            wire=True,
            public_handle=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "api_surface_producer",
            "SYMBOL key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol_kind",
            ANALYSIS_FACT,
            "api_surface_producer",
            "closed vocabulary (API_SYMBOL_KINDS); payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "visibility",
            ANALYSIS_FACT,
            "api_surface_producer",
            "closed vocabulary (API_VISIBILITIES); payload, never key",
            stored=True,
            wire=True,
        ),
    ),
    "candidates": (
        FieldDeclaration(
            "level",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "producer_set",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "shared_fact",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "candidate_id",
            CONTRACT_DERIVED,
            "candidate_identity_contract.v1",
            "sha256 over (revision, level, shared_fact, producers)",
            stored=False,
            wire=True,
            public_handle=True,
        ),
        FieldDeclaration(
            "score",
            CONTRACT_DERIVED,
            "candidate_identity_contract.v1",
            "closed level score table",
            stored=False,
            wire=False,
        ),
    ),
    # F8 (wave 4): the emitted clone population only — suppressed is a
    # different population (ruling 2026-08-24 §10) and has no columns here.
    "clone_groups": (
        FieldDeclaration(
            "clone_kind",
            ANALYSIS_FACT,
            "clone_detection_producer",
            "closed vocabulary (CLONE_KINDS); key component — one producer "
            "key string may exist under two kinds",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "group_key",
            ANALYSIS_FACT,
            "clone_detection_producer",
            "the producer's fp-v2 grouping key; key component — meaning "
            "owned by the clone fingerprint generation "
            "(BASELINE_FINGERPRINT_VERSION)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "items",
            ANALYSIS_FACT,
            "clone_detection_producer",
            "member identities (unit and span); group arity and item "
            "identity are different measurements — per-kind item metrics "
            "stay with the legacy document",
            stored=True,
            wire=True,
        ),
    ),
    # E1 (2026-09-25): the document's design/cohesion groups — one row per
    # class the run's cohesion threshold classified a hotspot; key (SYMBOL,
    # start_line).  The threshold lives in the analysis contract, not here:
    # the row IS the verdict (the F7 kind precedent).
    "cohesion_hotspots": (
        FieldDeclaration(
            "end_line",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "class declaration extent; payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "instance_var_count",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "lcom4",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "the cohesion measure the threshold classified; payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "method_count",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "risk",
            CONTRACT_DERIVED,
            "metrics.cohesion.cohesion_risk",
            "the risk ladder over lcom4 (COHESION_RISK_* contract "
            "thresholds); re-derived by the projection, never stored",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "start_line",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "declaration-site discriminator; key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "SYMBOL key component (a class, no FUNCTION role)",
            stored=True,
            wire=True,
        ),
    ),
    # E1: the document's design/complexity groups — one row per function
    # the run's complexity threshold classified a hotspot; key (SYMBOL,
    # start_line).  The measures are the finding's OWN published payload:
    # the risk lane carries the same numbers as observations of every unit,
    # this family carries the producer's SELECTION of them under the run's
    # threshold — a different population, held equal to the lane on every
    # corpus by the E1 projection pins.
    "complexity_hotspots": (
        FieldDeclaration(
            "cyclomatic_complexity",
            ANALYSIS_FACT,
            "complexity_metrics_producer",
            "the measure the threshold classified; payload, floor 1",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "end_line",
            ANALYSIS_FACT,
            "complexity_metrics_producer",
            "declaration extent; payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "nesting_depth",
            ANALYSIS_FACT,
            "complexity_metrics_producer",
            "observed depth (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "risk",
            CONTRACT_DERIVED,
            "metrics.complexity.risk_level",
            "the risk ladder over cyclomatic_complexity "
            "(COMPLEXITY_RISK_* contract thresholds); never stored",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "start_line",
            ANALYSIS_FACT,
            "complexity_metrics_producer",
            "declaration-site discriminator; key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "complexity_metrics_producer",
            "SYMBOL key component",
            stored=True,
            wire=True,
        ),
    ),
    "contracts": (
        FieldDeclaration(
            "effect_signature",
            ANALYSIS_FACT,
            "contract_ir_producer",
            "carried fact in the wave-1 subset (wire basis not carried)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "function",
            ANALYSIS_FACT,
            "contract_ir_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "root_set",
            ANALYSIS_FACT,
            "contract_ir_producer",
            "observed",
            stored=True,
            wire=True,
        ),
    ),
    "coupling_cohesion_observations": (
        FieldDeclaration(
            "dimension",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "closed vocabulary (COUPLING_COHESION_DIMENSIONS); key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "numerator",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "observed positive count; payload, never key (zero rows dropped "
            "by the producer — absence means zero)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "SYMBOL key component (with dimension: 2 091/2 091 at "
            "ratification, 2 379/2 379 @ 95e4210b 2026-08-30 — see the "
            "corpus-ratio note at the head of this module)",
            stored=True,
            wire=True,
        ),
    ),
    # E1: the document's design/coupling groups — one row per class the
    # run's coupling threshold classified a hotspot; key (SYMBOL,
    # start_line).  ``coupled_classes`` is the per-class attribution the
    # standalone ``coupled_sets`` value family does not carry.
    "coupling_hotspots": (
        FieldDeclaration(
            "cbo",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "the coupling measure the threshold classified; payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "coupled_classes",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "the producer's sorted unique coupled labels; payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "end_line",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "class declaration extent; payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "risk",
            CONTRACT_DERIVED,
            "metrics.coupling.coupling_risk",
            "the risk ladder over cbo (COUPLING_RISK_* contract "
            "thresholds); never stored",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "start_line",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "declaration-site discriminator; key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "SYMBOL key component (a class, no FUNCTION role)",
            stored=True,
            wire=True,
        ),
    ),
    # E1 (A5): the external Cobertura join — ONE record per run, present
    # exactly when the run was handed a report (record wire member, the F9
    # shape; the absent record is the empty member, never a zero fake).
    # Every count the document publishes beside these that is a sum over
    # ``coverage_units`` is declared derived and never stored.
    "coverage_join": (
        FieldDeclaration(
            "coverage_hotspots",
            REPRESENTATION,
            "metrics.coverage_join.coverage_hotspot",
            "count of unit rows the one hotspot rule selects; a sum over "
            "coverage_units, never a column",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "files",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "files the report mapped into the run — a fact of the XML, not "
            "of the units (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "hotspot_threshold_percent",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "the run's requested threshold; payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "invalid_reason",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "why the report could not be read; present exactly when the "
            "status is invalid (empty wire string spells absence)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "measured_units",
            REPRESENTATION,
            "coverage_join_producer",
            "count of measured unit rows; a sum over coverage_units",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "missing_from_report_units",
            REPRESENTATION,
            "coverage_join_producer",
            "count of unit rows the report never mapped; a sum",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "overall_covered_lines",
            REPRESENTATION,
            "coverage_join_producer",
            "sum of covered_lines over coverage_units",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "overall_executable_lines",
            REPRESENTATION,
            "coverage_join_producer",
            "sum of executable_lines over coverage_units",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "overall_permille",
            REPRESENTATION,
            "metrics.coverage_join.permille",
            "the one coverage ratio over the two overall sums",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "scope_gap_hotspots",
            REPRESENTATION,
            "metrics.coverage_join.scope_gap_hotspot",
            "count of unit rows the one scope-gap rule selects; a sum",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "source",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "the report's path as the document contracts it (in-root "
            "relative, or the file name of an external path); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "status",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "closed vocabulary (COVERAGE_JOIN_STATUSES); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "units",
            REPRESENTATION,
            "coverage_join_producer",
            "the unit row count; never a column",
            stored=False,
            wire=False,
        ),
    ),
    # E1 (A5): one row per unit the join measured against the external
    # report; key (SYMBOL, start_line).  What the join OBSERVED is stored;
    # the permille, the two hotspot flags, the complexity and the risk the
    # document publishes on the item are derived through their owners.
    "coverage_units": (
        FieldDeclaration(
            "coverage_hotspot",
            REPRESENTATION,
            "metrics.coverage_join.coverage_hotspot",
            "the one hotspot rule over risk, status and permille",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "coverage_permille",
            REPRESENTATION,
            "metrics.coverage_join.permille",
            "the one coverage ratio over covered and executable lines",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "coverage_status",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "closed vocabulary (COVERAGE_UNIT_STATUSES); payload bound to "
            "executable_lines by the model law",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "covered_lines",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "observed count inside the span (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "cyclomatic_complexity",
            REPRESENTATION,
            "risk_observations",
            "the unit's own measure, carried by the risk lane under the "
            "same declaration key; never a second column",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "end_line",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "declaration extent; payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "executable_lines",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "observed count inside the span (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "risk",
            CONTRACT_DERIVED,
            "metrics.complexity.risk_level",
            "the risk ladder over the unit's cyclomatic complexity",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "scope_gap_hotspot",
            REPRESENTATION,
            "metrics.coverage_join.scope_gap_hotspot",
            "the one scope-gap rule over risk and status",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "start_line",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "declaration-site discriminator; key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "coverage_join_producer",
            "SYMBOL key component",
            stored=True,
            wire=True,
        ),
    ),
    # F4 (wave 4, slice K3): key (entity, observation_kind); the entity is
    # the ratified tagged reference — the variant is identity (§2).
    "dead_code_observations": (
        FieldDeclaration(
            "abstained",
            ANALYSIS_FACT,
            "dead_code_producer",
            "rule-3 tri-state abstention; payload boolean, mutually "
            "exclusive with live_root_reason by contract",
            stored=True,
            wire=True,
            wire_shape="sparse_bool_positions",
        ),
        FieldDeclaration(
            "candidate_kind",
            ANALYSIS_FACT,
            "dead_code_producer",
            "closed vocabulary (DEAD_CODE_CANDIDATE_KINDS); payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "entity",
            ANALYSIS_FACT,
            "dead_code_producer",
            "key component: tagged entity reference FileSymbol(FILE, "
            "qualname) | ModuleSymbol(MODULE, qualname) | opaque variant — "
            "the variant is part of the identity (§2)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "live_root_reason",
            ANALYSIS_FACT,
            "dead_code_producer",
            "closed vocabulary (LIVE_ROOT_REASONS) or absent (empty wire "
            "string spells the producer's absence, the F5 returns precedent)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "observation_kind",
            ANALYSIS_FACT,
            "dead_code_producer",
            "closed vocabulary (DEAD_CODE_OBSERVATION_KINDS); key component "
            "— symbol rows and unreachable-statement rows are two meanings "
            "with two policy owners",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "reachable",
            ANALYSIS_FACT,
            "dead_code_producer",
            "runtime reachability verdict; payload boolean",
            stored=True,
            wire=True,
            wire_shape="sparse_bool_positions",
        ),
        FieldDeclaration(
            "reference_count",
            ANALYSIS_FACT,
            "dead_code_producer",
            "observed count (zero is measured); payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "runtime_marker_count",
            ANALYSIS_FACT,
            "dead_code_producer",
            "observed count (zero is measured); payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "source_markers",
            ANALYSIS_FACT,
            "dead_code_producer",
            "sorted unique (key, value) evidence pairs; payload, never key",
            stored=True,
            wire=True,
        ),
    ),
    # E1 (A7): the dead-code lane's population counters — ONE record per
    # run (record wire member, the F9 shape), present exactly when the lane
    # ran.  Measured NOT derivable from ``dead_code_observations`` (the
    # abstention lanes are absent from it); the three counters that ARE
    # derivable from the group families are declared derived.
    "dead_code_summary": (
        FieldDeclaration(
            "candidates",
            ANALYSIS_FACT,
            "dead_code_producer",
            "the judged module-level population (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "high_confidence",
            REPRESENTATION,
            "dead_symbol_groups",
            "count of dead_symbol_groups rows at high confidence; a sum",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "live_roots",
            ANALYSIS_FACT,
            "dead_code_producer",
            "observed live-root count (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "nested_candidates",
            ANALYSIS_FACT,
            "dead_code_producer",
            "the judged function-local population (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "suppressed",
            ANALYSIS_FACT,
            "dead_code_producer",
            "suppressed dead-symbol count — a population this model does "
            "not carry as rows (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "total",
            REPRESENTATION,
            "dead_symbol_groups",
            "count of dead_symbol_groups rows; never a column",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "unreachable_statements",
            REPRESENTATION,
            "unreachable_statement_groups",
            "count of unreachable_statement_groups rows; never a column",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "unresolved",
            ANALYSIS_FACT,
            "dead_code_producer",
            "reachability abstentions (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "unresolved_external_override",
            ANALYSIS_FACT,
            "dead_code_producer",
            "rule-3 abstentions (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "unresolved_internal",
            ANALYSIS_FACT,
            "dead_code_producer",
            "internal abstentions, liveness policy v5 (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "world_contract",
            ANALYSIS_FACT,
            "dead_code_producer",
            "closed vocabulary (WORLD_CONTRACTS): the world every verdict "
            "of the run was derived under",
            stored=True,
            wire=True,
        ),
    ),
    # E1 (A2): the document's dead_code/unused_symbol groups — the
    # liveness policy's VERDICT population, one row per published finding;
    # key (SYMBOL, start_line), the declaration-site key.  Not the
    # observation lane: measured 36 findings against 19 929 lane rows @
    # ebe362d5, and the selection is the policy, not a function of the lane.
    "dead_symbol_groups": (
        FieldDeclaration(
            "candidate_kind",
            ANALYSIS_FACT,
            "dead_code_producer",
            "closed vocabulary (DEAD_CODE_CANDIDATE_KINDS); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "confidence",
            ANALYSIS_FACT,
            "dead_code_producer",
            "closed vocabulary (DEAD_SYMBOL_CONFIDENCES); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "end_line",
            ANALYSIS_FACT,
            "dead_code_producer",
            "declaration extent; payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "reason",
            ANALYSIS_FACT,
            "dead_code_producer",
            "closed vocabulary (DEAD_SYMBOL_REASONS); payload bound to the "
            "evidence list by the producer's own contract",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "start_line",
            ANALYSIS_FACT,
            "dead_code_producer",
            "declaration-site discriminator; key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "dead_code_producer",
            "SYMBOL key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "test_reference_sources",
            ANALYSIS_FACT,
            "dead_code_producer",
            "sorted unique test references; non-empty exactly for the test-only reason",
            stored=True,
            wire=True,
        ),
    ),
    # The ratified dependency split (ruling 2026-08-24 §2): the relation is
    # the entity gate/SCC read; the occurrence is location evidence bound to
    # it.  ``line`` never enters the relation — location is evidence, not
    # identity.
    "dependency_occurrences": (
        FieldDeclaration(
            "binding",
            ANALYSIS_FACT,
            "dependency_producer",
            "classified binding time; occurrence payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "dependency_type",
            ANALYSIS_FACT,
            "dependency_producer",
            "relation-triple component binding this evidence to its entity",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "is_lazy",
            ANALYSIS_FACT,
            "dependency_producer",
            "raw PEP 810 marker; occurrence payload boolean",
            stored=True,
            wire=True,
            wire_shape="sparse_bool_positions",
        ),
        FieldDeclaration(
            "line",
            ANALYSIS_FACT,
            "dependency_producer",
            "evidence location; occurrence row-key component (926 corpus "
            "collisions without it), never relation identity",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "source",
            ANALYSIS_FACT,
            "dependency_producer",
            "relation-triple component; DependencyEndpoint MODULE | FILE",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "target",
            ANALYSIS_FACT,
            "dependency_producer",
            "relation-triple component; DependencyEndpoint MODULE | FILE",
            stored=True,
            wire=True,
        ),
    ),
    # F7 (wave 4): one row per module set, the kind classified once by the
    # one producer owner.  ``member_paths`` of the legacy row is declared
    # here as what it is — the registry's FILE-MODULE projection, a table
    # and never a column (§2.3) — so the projector CANNOT emit it.
    "dependency_cycles": (
        FieldDeclaration(
            "kind",
            ANALYSIS_FACT,
            "dependency_producer",
            "classified once by the one cycle owner (import_cycle iff the "
            "import-time edges still cycle among the members); closed "
            "vocabulary (DEPENDENCY_CYCLE_KINDS); payload of the set, "
            "never a second row",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "member_paths",
            REPRESENTATION,
            "module_registry",
            "registry FILE-MODULE projection per member; re-derivable from "
            "file_modules — a table, never a column (§2.3)",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "modules",
            ANALYSIS_FACT,
            "dependency_producer",
            "entity key: the module SET (one row per set); MODULE domain, "
            "never strings; at least two members (Tarjan floor)",
            stored=True,
            wire=True,
        ),
    ),
    "dependency_relations": (
        FieldDeclaration(
            "dependency_type",
            ANALYSIS_FACT,
            "dependency_producer",
            "entity-key component; closed vocabulary (IMPORT_TYPES)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "source",
            ANALYSIS_FACT,
            "dependency_producer",
            "entity-key component; DependencyEndpoint MODULE | FILE (measured 860/1)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "target",
            ANALYSIS_FACT,
            "dependency_producer",
            "entity-key component; DependencyEndpoint MODULE | FILE",
            stored=True,
            wire=True,
        ),
    ),
    "file_modules": (
        FieldDeclaration(
            "file",
            ANALYSIS_FACT,
            "module_registry",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "module",
            ANALYSIS_FACT,
            "module_registry",
            "observed",
            stored=True,
            wire=True,
        ),
    ),
    "graph_nodes": (
        FieldDeclaration(
            "effect_signature",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "not derivable here: no wire stored beside (S8.V.3)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "function",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "output_facts",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "ordered producer emission; NOT a set (1 157/12 244 unsorted)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "resolution_state",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "root_set",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "observed",
            stored=True,
            wire=True,
        ),
    ),
    # Canonical model revision 2: every import the module walk observed —
    # the served ``module_imports`` slice, external and unresolved targets
    # included.  A DIFFERENT population contract from the dependency
    # families (which keep the internal graph the gate consumes and are not
    # widened by sanction): 11 445 served rows against 6 491 dependency
    # occurrences @ f117a8ad (a dated observation).  Key: the whole
    # observation (11 445/11 445 distinct on every field @ f117a8ad).
    "import_observations": (
        FieldDeclaration(
            "binding",
            ANALYSIS_FACT,
            "module_walk_producer",
            "classified binding time; closed vocabulary (DEPENDENCY_BINDINGS)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "candidate_targets",
            ANALYSIS_FACT,
            "module_walk_producer",
            "the producer's sorted, unique candidate list; empty iff unresolved",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "dependency_type",
            ANALYSIS_FACT,
            "module_walk_producer",
            "the served import_type; closed vocabulary (IMPORT_TYPES)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "inventory_expansion",
            ANALYSIS_FACT,
            "module_walk_producer",
            "the row was expanded from a from-import of a package member",
            stored=True,
            wire=True,
            wire_shape="sparse_bool_positions",
        ),
        FieldDeclaration(
            "is_lazy",
            ANALYSIS_FACT,
            "module_walk_producer",
            "raw PEP 810 marker",
            stored=True,
            wire=True,
            wire_shape="sparse_bool_positions",
        ),
        FieldDeclaration(
            "level",
            ANALYSIS_FACT,
            "module_walk_producer",
            "relative-import depth; zero on absolute imports",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "line",
            ANALYSIS_FACT,
            "module_walk_producer",
            "the statement's own line; zero admitted as a coerced document zero",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "mechanism",
            ANALYSIS_FACT,
            "module_walk_producer",
            "static statement or dynamic load; closed (IMPORT_MECHANISMS)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "requested_module",
            ANALYSIS_FACT,
            "module_walk_producer",
            "the module text the statement named; absent on a bare relative "
            "import, spelled empty on the wire",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "requested_names",
            ANALYSIS_FACT,
            "module_walk_producer",
            "the names a from-import requested, in the producer's sorted order",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "resolution",
            ANALYSIS_FACT,
            "module_walk_producer",
            "the producer's classification; closed (IMPORT_RESOLUTIONS); the "
            "target variant is checked against it",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "source",
            ANALYSIS_FACT,
            "module_walk_producer",
            "the importing file as the producer keys it; DependencyEndpoint "
            "MODULE | FILE (54 of 11 445 served sources are module-less paths)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "target",
            ANALYSIS_FACT,
            "module_walk_producer",
            "tagged ImportTarget: MODULE | FILE of the run, opaque dotted "
            "head outside its registry, or unresolved_target",
            stored=True,
            wire=True,
        ),
    ),
    # E1 (A4): the overloaded-modules producer's rows, keyed by FILE
    # (1 247/1 247 unique on path @ ebe362d5, a dated observation).  The
    # ``module`` column the document publishes is the registry's
    # FILE-MODULE projection and is never stored (the F7 member_paths
    # precedent); ``source_kind`` is the stored classification verdict (the
    # F10 precedent).
    "overloaded_modules": (
        FieldDeclaration(
            "callable_count",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "candidate_reasons",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "the producer's ordered reasons; payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "candidate_status",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "closed vocabulary (OVERLOADED_CANDIDATE_STATUSES); the "
            "producer's verdict, stored as a fact",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "classes",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "complexity_max",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed maximum over the module's units; payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "complexity_total",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed sum over the module's units; payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "dependency_score",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "composite score at the document's four-decimal precision",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "fan_in",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "fan_out",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "file",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "FILE key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "functions",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "hub_balance",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "composite score at the document's four-decimal precision",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "import_edges",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "instability",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "composite score at the document's four-decimal precision",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "loc",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "methods",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "module",
            REPRESENTATION,
            "module_registry",
            "the file's module, or its path when it has none — the "
            "registry FILE-MODULE projection, a table and never a column",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "reimport_edges",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "reimport_ratio",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "composite score at the document's four-decimal precision",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "score",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "composite score at the document's four-decimal precision",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "shape_score",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "composite score at the document's four-decimal precision",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "size_score",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "composite score at the document's four-decimal precision",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "source_kind",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "classification VERDICT of the one owner "
            "(SOURCE_KIND_POLICY_VERSION), stored as a fact; closed "
            "vocabulary (SECURITY_SOURCE_KINDS)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "total_deps",
            ANALYSIS_FACT,
            "overloaded_modules_producer",
            "observed count (zero is measured); payload",
            stored=True,
            wire=True,
        ),
    ),
    # Canonical model revision 2: the per-function call/reference records
    # — the served ``relationship_facts`` slice in BOTH resolution states.
    # Key: the observation; ``occurrence_count`` is the one payload field
    # (1 342 of 112 967 records @ f117a8ad repeat on one line).
    "relationship_observations": (
        FieldDeclaration(
            "expression",
            ANALYSIS_FACT,
            "function_relationship_producer",
            "unparsed source text of the call/reference; absent, never "
            "empty (spelled empty on the wire)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "line",
            ANALYSIS_FACT,
            "function_relationship_producer",
            "the expression's line, clamped positive by the producer",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "occurrence_count",
            ANALYSIS_FACT,
            "function_relationship_producer",
            "how many records the producer emitted for this observation; "
            "payload, never key; the served tuple expands by it",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "origin_lane",
            ANALYSIS_FACT,
            "function_relationship_producer",
            "production or test source; closed (RELATIONSHIP_ORIGIN_LANES)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "path",
            REPRESENTATION,
            "function_relationship_producer",
            "the source SYMBOL's file joined to the serving root — the "
            "served absolute path is a rendering, never a column (§2.3)",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "relation_kind",
            ANALYSIS_FACT,
            "function_relationship_producer",
            "call or reference; closed (RELATIONSHIP_KINDS)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "resolution_rule",
            ANALYSIS_FACT,
            "function_relationship_producer",
            "the mechanism that resolved (or failed to resolve) the "
            "expression; closed (RELATIONSHIP_RESOLUTION_RULES); absent "
            "spelled empty on the wire",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "resolution_status",
            REPRESENTATION,
            "function_relationship_producer",
            "resolved iff the target is a symbol or an opaque head, "
            "unresolved iff it is the nullary variant — the producer's own "
            "rule, owned by relationship_resolution_status(); a column would "
            "be the same fact twice",
            stored=False,
            wire=False,
        ),
        FieldDeclaration(
            "source",
            ANALYSIS_FACT,
            "function_relationship_producer",
            "the recording function's SYMBOL; the served glued qualname is "
            "rebuilt through file_modules",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "target",
            ANALYSIS_FACT,
            "function_relationship_producer",
            "tagged RelationshipTarget: SYMBOL of the run, opaque head:local "
            "outside it, or unresolved_target",
            stored=True,
            wire=True,
        ),
    ),
    # E1 (A2): the document's structural finding groups — one row per
    # group the detectors published; key (finding_kind, finding_key), the
    # pair the document's ``structural:{kind}:{key}`` identity is spelled
    # from through ``findings.ids.structural_group_id``.
    "structural_groups": (
        FieldDeclaration(
            "finding_key",
            ANALYSIS_FACT,
            "structural_findings_producer",
            "the detector's own group key; key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "finding_kind",
            ANALYSIS_FACT,
            "structural_findings_producer",
            "closed vocabulary (STRUCTURAL_FINDING_KINDS); key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "occurrences",
            ANALYSIS_FACT,
            "structural_findings_producer",
            "member sites (unit and span); at least one",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "signature",
            ANALYSIS_FACT,
            "structural_findings_producer",
            "the detector's raw signature as sorted unique (key, value) "
            "pairs; the typed stable block and the facts are derived from "
            "it by findings.group_shapes",
            stored=True,
            wire=True,
        ),
    ),
    # E1 (A1): the clone groups the suppression policy took OUT of the
    # emitted population — a different population from ``clone_groups``
    # (ruling 2026-08-24 §10), its own family, never mixed in.  Key
    # (clone_kind, group_key), the emitted family's own.
    "suppressed_clone_groups": (
        FieldDeclaration(
            "clone_kind",
            ANALYSIS_FACT,
            "clone_detection_producer",
            "closed vocabulary (CLONE_KINDS); key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "group_key",
            ANALYSIS_FACT,
            "clone_detection_producer",
            "the producer's fp-v2 grouping key; key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "items",
            ANALYSIS_FACT,
            "clone_detection_producer",
            "member identities (unit and span); at least two",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "matched_patterns",
            ANALYSIS_FACT,
            "clone_suppression_producer",
            "the patterns the suppressor matched, in its own order; at least one",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "suppression_rule",
            ANALYSIS_FACT,
            "clone_suppression_producer",
            "the rule that suppressed the group; payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "suppression_source",
            ANALYSIS_FACT,
            "clone_suppression_producer",
            "where the rule came from; payload",
            stored=True,
            wire=True,
        ),
    ),
    # The DECLARATION entity: key (SYMBOL, start_line), measured total on
    # the self-repo corpus (15 934/15 934 distinct @ 4512acf0, 2026-09-03 —
    # a dated observation, not an invariant; the key's totality is what
    # ``_unique_by_key`` proves on every run).  The span rides its OWN
    # family rather than a column of ``risk_observations`` because
    # ``dimension`` is in that family's key: 6 675 of 15 934 declarations
    # carry two risk rows, so the span would be stored twice and two copies
    # could contradict each other without ever sharing a key.  The producer
    # is the unit extraction, not a metric: ``end_line`` is the parsed
    # declaration's ``ast`` extent and does not move when a metric is
    # recounted, which is why the store namespaces this family under
    # ``canonical_model`` and not under the complexity revision.
    "unit_spans": (
        FieldDeclaration(
            "end_line",
            ANALYSIS_FACT,
            "unit_extraction_producer",
            "observed declaration extent; payload, never key (a range end, "
            "refused below its own start)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "start_line",
            ANALYSIS_FACT,
            "unit_extraction_producer",
            "declaration-site discriminator; key component — different "
            "declarations sharing one qualname (@overload families, "
            "property/setter pairs) are different entities",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "unit_extraction_producer",
            "SYMBOL key component",
            stored=True,
            wire=True,
        ),
    ),
    # F1 (ruling 2026-08-26, fork (b)): key (SYMBOL, dimension, start_line)
    # — the declaration site IS a key component here, the named exception
    # to the dependency rule that location is evidence (§2), resolved by
    # the maintainer's morning ruling.  See RISK_OBSERVATIONS_KEY below.
    "risk_observations": (
        FieldDeclaration(
            "dimension",
            ANALYSIS_FACT,
            "complexity_metrics_producer",
            "closed vocabulary (RISK_DIMENSIONS); key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "numerator",
            ANALYSIS_FACT,
            "complexity_metrics_producer",
            "observed positive count; payload, never key (zero rows dropped "
            "by the producer — absence means zero)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "start_line",
            ANALYSIS_FACT,
            "complexity_metrics_producer",
            "declaration-site discriminator; key component (the "
            "complexity.items precedent, 12 285/12 285 unique) — different "
            "declarations sharing one qualname are different entities",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "complexity_metrics_producer",
            "SYMBOL key component",
            stored=True,
            wire=True,
        ),
    ),
    # F9 (wave 4, ratified form): ONE record per analysis snapshot — a
    # run-level analysis fact, not a tabular entity; no invented entity key.
    # The wire member is a record object (see RECORD_WIRE_FAMILIES).
    "run_scalars": (
        FieldDeclaration(
            "classes",
            ANALYSIS_FACT,
            "run_inventory_producer",
            "observed run-population scalar (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "files_found",
            ANALYSIS_FACT,
            "run_inventory_producer",
            "observed run-population scalar (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "files_observed",
            ANALYSIS_FACT,
            "run_inventory_producer",
            "observed run-population scalar (zero is measured); parsed plus "
            "cached, the split being provenance that never reaches the store",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "files_skipped",
            ANALYSIS_FACT,
            "run_inventory_producer",
            "observed run-population scalar (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "functions",
            ANALYSIS_FACT,
            "run_inventory_producer",
            "observed run-population scalar (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "methods",
            ANALYSIS_FACT,
            "run_inventory_producer",
            "observed run-population scalar (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "parsed_lines",
            ANALYSIS_FACT,
            "run_inventory_producer",
            "observed run-population scalar (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "source_io_skipped",
            ANALYSIS_FACT,
            "run_inventory_producer",
            "observed run-population scalar (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "unsupported_construct_skipped",
            ANALYSIS_FACT,
            "run_inventory_producer",
            "observed run-population scalar (zero is measured)",
            stored=True,
            wire=True,
        ),
    ),
    # F10 (wave 4, slice 5): key (FILE, start_line, evidence_symbol) —
    # the packet's exhaustive 1-3-field enumeration found exactly six
    # unique 3-keys, evidence_symbol in all (387/387 at ratification,
    # 406/406 @ 95e4210b 2026-08-30, 11/11 on the s5 corpus — dated
    # observations, see the module head).  The legacy row's ``module``
    # field is deliberately NOT declared: it is the registry's
    # FILE-MODULE projection, verified at
    # ingest and re-derivable from file_modules (the F7 member_paths
    # precedent) — the projector cannot emit it.
    "security_surfaces": (
        FieldDeclaration(
            "capability",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "the producer's catalog entry; open string payload whose "
            "meaning is owned by SECURITY_SURFACE_CATALOG_VERSION",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "category",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "closed vocabulary (SECURITY_SURFACE_CATEGORIES); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "classification_mode",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "closed vocabulary (SECURITY_CLASSIFICATION_MODES); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "end_line",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "evidence span end; payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "evidence_kind",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "closed vocabulary (SECURITY_EVIDENCE_KINDS); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "evidence_symbol",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "key component — two symbols may share one line (the s5 "
            "eval+compile datum)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "file",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "FILE key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "location_scope",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "closed vocabulary (SECURITY_LOCATION_SCOPES); payload bound "
            "to qualname by the model law (module scope has no local name)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "qualname",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "local name of the hosting unit, or absent on module scope "
            "(empty wire string spells absence, the F5 returns precedent)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "source_kind",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "classification VERDICT of the one producer owner "
            "(SOURCE_KIND_POLICY_VERSION), stored as a fact and never "
            "re-derived on read — the F7 kind precedent; closed "
            "vocabulary (SECURITY_SOURCE_KINDS)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "start_line",
            ANALYSIS_FACT,
            "security_surfaces_producer",
            "key component — one symbol may repeat across lines "
            "(the s5 pickle.loads datum)",
            stored=True,
            wire=True,
        ),
    ),
    "semantic_edges": (
        FieldDeclaration(
            "source",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "target",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "observed",
            stored=True,
            wire=True,
        ),
    ),
    "sink_roles": (
        FieldDeclaration(
            "authority_status",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "not derivable: unique role fact (§8.1)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
    ),
    # E1 (A2): the document's dead_code/unreachable_statement groups —
    # one row per unreachable region the CFG producer published; key
    # (SYMBOL, start_line).
    "unreachable_statement_groups": (
        FieldDeclaration(
            "end_line",
            ANALYSIS_FACT,
            "statement_reachability_producer",
            "region extent; payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "reason",
            ANALYSIS_FACT,
            "statement_reachability_producer",
            "closed vocabulary (UNREACHABLE_REASONS); payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "start_line",
            ANALYSIS_FACT,
            "statement_reachability_producer",
            "region start; key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "statement_count",
            ANALYSIS_FACT,
            "statement_reachability_producer",
            "observed region size, floor 1; payload",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "statement_reachability_producer",
            "SYMBOL key component: the live unit hosting the region",
            stored=True,
            wire=True,
        ),
    ),
    "violations": (
        FieldDeclaration(
            "authority_status",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "canonical_owner",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "governance registry declaration; no role requirement",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "contract_id",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "governance registry declaration; natural-key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "effect_signature",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "authority-effect domain digest; not derivable (S8.V.3)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "kind",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "closed vocabulary; natural-key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "locations",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "distilled source evidence; NOT derivable (S8.V.3) — the "
            "producer's basis is FunctionContractSummary.events, which is "
            "no family of this subset, so the value is stored rather than "
            "projected; payload tuple, never key (a violation is the same "
            "violation wherever it was witnessed)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "producer_set",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "natural-key component; FUNCTION role required",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "resolution_state",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "root_set",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "sink_identity",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "natural-key component; FUNCTION role required",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "suppressed",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "inline suppression flag; payload boolean",
            stored=True,
            wire=True,
            wire_shape="sparse_bool_positions",
        ),
        FieldDeclaration(
            "violation_id",
            CONTRACT_DERIVED,
            "violation_identity_contract.v1",
            "sha256 over (revision, contract_id, kind, sink_identity, producers)",
            stored=False,
            wire=True,
            public_handle=True,
        ),
    ),
}


# ---------------------------------------------------------------------------
# The ratified F1 key — the fork was RESOLVED by the maintainer (2026-08-26,
# variant (b)), and the family above is now a real wire family.
# ---------------------------------------------------------------------------

# F1 ``risk_observations`` — logical key of the analysis-fact family,
# resolved by the 2026-08-24 night preflight trace (ruling 2026-08-24 §1)
# and ratified by the 2026-08-26 morning ruling (fork (b)).
#
# The measured defect: the bare ``(FILE, qualname, dimension)`` key is blind
# to 4 real declaration groups — ``@overload`` families of 4, 4 and 3
# declarations plus one property/setter pair of 2, so 13 rows collapse onto
# 4 keys and 9 rows are lost (9 of 20 001 @ 95e4210b 2026-08-30; the note
# this replaced said "three triples and one pair", which totals 7, not the
# 9 it claimed).  Every group is *different declarations sharing one name*,
# so deduplication is indefensible: a producer-native discriminator is
# required.
#
# The ratified discriminator is the declaration-site ``start_line``, by the
# product's own precedent: ``complexity.items`` already keys
# ``(path, qualname, start_line)`` and is unique on it (12 285/12 285 at
# ratification, 14 040/14 040 @ 95e4210b 2026-08-30).  The producer now
# carries the fact end to end: the risk lane's
# ``RiskObservation`` row keeps ``start_line`` (payload schema "5"), the
# baseline reader keys with it, and the family declaration above admits it
# as a KEY component — the named exception to the dependency rule that
# location is evidence (ruling §2), admitted by fork (b).
#
# THIS TUPLE IS A DECLARATION, NOT THE EXECUTED KEY.  No production caller
# reads it: the key the model actually enforces is built inside
# ``model._prove_unique_keys``.  A declaration with no structural path to
# the decision it names is not enforcement, so the binding is carried by
# ``tests/test_canonical_registry`` — it drives the real
# ``CanonicalModel.normalize`` path and refuses to let this tuple and the
# executed key drift apart, in either direction.  Keep that binding alive:
# a pin that compares this literal to a literal proves only that the
# literal was typed twice (measured 2026-08-30 — the pin it replaced stayed
# green while the executed key both lost and gained a component).
RISK_OBSERVATIONS_FAMILY: Final = "risk_observations"
RISK_OBSERVATIONS_KEY: Final[tuple[str, ...]] = (
    "file",
    "qualname",
    "dimension",
    "start_line",
)


#: Families whose wire member is ONE record object, never a columnar table
#: (F9: one record per analysis snapshot — there are no rows to key, and a
#: fake entity key is never invented; ruling 2026-08-24 §1).  The absent
#: record is the empty member.
RECORD_WIRE_FAMILIES: Final[frozenset[str]] = frozenset(
    {"analysis_population", "coverage_join", "dead_code_summary", "run_scalars"}
)


def is_record_family(family: str) -> bool:
    """True for single-record wire families (no rows, no row keys)."""
    return family in RECORD_WIRE_FAMILIES


def wire_fact_family_order() -> tuple[str, ...]:
    """Wire order of fact families: mechanical, total, no manual tail."""
    return tuple(sorted(FACT_FAMILY_FIELDS))


def wire_columns(family: str) -> tuple[str, ...]:
    """Wire columns of one family, in canonical (sorted) column order.

    Every ``wire=True`` field is a wire column: stored facts are emitted
    from the model, and contract-derived handles (``stored=False``) are
    computed by the projector through the field's one formula owner —
    never by a consumer, never by a second spelling of the formula.
    """
    return tuple(
        sorted(
            declaration.field
            for declaration in FACT_FAMILY_FIELDS[family]
            if declaration.wire
        )
    )


def derived_wire_columns(family: str) -> tuple[str, ...]:
    """The family's contract-derived wire columns (emitted, never stored)."""
    return tuple(
        sorted(
            declaration.field
            for declaration in FACT_FAMILY_FIELDS[family]
            if declaration.wire and not declaration.stored
        )
    )


def sparse_bool_wire_columns(family: str) -> tuple[str, ...]:
    """The family's sparse-boolean wire columns (position lists, omitted
    when no row is true — F-3 §7.6 rules 1 and 3)."""
    return tuple(
        sorted(
            declaration.field
            for declaration in FACT_FAMILY_FIELDS[family]
            if declaration.wire and declaration.wire_shape == "sparse_bool_positions"
        )
    )


# The §4 grammar gate (ruling 2026-08-24, backend step 3): the analysis
# facts section admits analysis-tier families only, each declared by its
# semantic kind in ``codeclone.canonical.grammar``.  Executed at import,
# so every path that reads this registry — codec encode and decode,
# ingest, the store exporter, every test session — inherits the check: a
# family added here without a grammar declaration, or with a comparison
# or evaluation production, or with a field spelling foreign-tier
# semantics, refuses loudly instead of shipping into the analysis wire.
# Declaration-only columns (``stored=False, wire=False``) are not passed:
# a value with no residence has no residence to misplace.
require_analysis_wire_families(
    {
        family: tuple(
            declaration.field
            for declaration in declarations
            if declaration.stored or declaration.wire
        )
        for family, declarations in FACT_FAMILY_FIELDS.items()
    }
)


# ---------------------------------------------------------------------------
# Canonical epoch E2 (2026-09-26): the comparison tier.
#
# These families are internal model and store state until the wire-revision
# bump: every declaration is ``wire=False``, the wire order above never names
# them, and the analysis wire gate refuses them.  The declaration still
# carries the same epistemics — a stored comparison fact, or a value derived
# from one through its named owner, declared and never stored.
# ---------------------------------------------------------------------------

_COMPARISON_FACT: Final = "comparison_fact"


def _stored(field: str, owner: str, derivation: str) -> FieldDeclaration:
    return FieldDeclaration(
        field, _COMPARISON_FACT, owner, derivation, stored=True, wire=False
    )


def _declared(field: str, owner: str, derivation: str) -> FieldDeclaration:
    return FieldDeclaration(
        field, CONTRACT_DERIVED, owner, derivation, stored=False, wire=False
    )


def _baseline_identity(owner: str) -> tuple[FieldDeclaration, ...]:
    """The two identity columns every comparison row carries: this run was
    compared against THIS container (both ``None``: no container)."""
    return (
        _stored(
            "baseline_scope_id",
            owner,
            "the container's baseline_scope_id (document "
            "baseline.baseline_scope_id); key component of the comparison",
        ),
        _stored(
            "root_digest",
            owner,
            "the container's meta.root_digest (document "
            "baseline.root_digest_or_null); key component of the comparison",
        ),
    )


def _novelty(subject: str) -> tuple[FieldDeclaration, ...]:
    owner = "report.document._common novelty owner"
    return (
        *_baseline_identity(owner),
        _stored(
            "finding_id",
            owner,
            f"the published id of the {subject} finding (codeclone.findings."
            "ids); the reference to the subject, never its payload",
        ),
        _stored("novelty", owner, "closed vocabulary: new / known / unavailable"),
        _stored(
            "novelty_reason",
            owner,
            "null for a verdict; for unavailable the absence it is "
            "(lane_unavailable / comparison_unavailable / entity_not_compared)",
        ),
    )


def _metric_delta(subject: str, terms: str) -> tuple[FieldDeclaration, ...]:
    owner = "metrics_baseline.diff"
    return (
        *_baseline_identity(owner),
        _stored(
            "delta",
            owner,
            f"key: the delta term of the {subject} comparison; closed per "
            f"family: {terms}",
        ),
        _stored("value", owner, "the term's measured value"),
    )


COMPARISON_FAMILY_FIELDS: Final[dict[str, tuple[FieldDeclaration, ...]]] = {
    "adoption_delta": _metric_delta(
        "adoption_counts",
        "docstring_permille_delta / typing_param_permille_delta / "
        "typing_return_permille_delta (MetricsDiff); every term present iff "
        "adoption_counts is compared",
    ),
    "api_surface_delta": _metric_delta(
        "api_symbols",
        "api_breaking_changes / api_signature_changes (compatible, never "
        "inside the breaking count) / new_api_symbols (MetricsDiff lengths); "
        "every term present iff api_surface is compared",
    ),
    "baseline_witness": (
        *_baseline_identity("report.document.builder baseline projection"),
        _stored("fingerprint_version", "report.meta", "meta.baseline"),
        _stored("loaded", "clone baseline resolver", "meta.baseline.loaded"),
        _stored(
            "payload_sha256",
            "report.meta",
            "meta.baseline.payload_sha256 (the container root digest when read)",
        ),
        _stored(
            "python_tag",
            "report.meta",
            "the artifact's interpreter tag; provenance, bound by the root "
            "digest; the RUNTIME tag is execution provenance and never stored",
        ),
        _stored("schema_version", "report.meta", "meta.baseline"),
        _stored(
            "state",
            "report.document.builder baseline projection",
            "missing / trusted / untrusted (baseline.state)",
        ),
        _stored("status", "clone baseline resolver", "meta.baseline.status"),
        _declared(
            "compared_without_valid_baseline",
            "surfaces baseline summary",
            "not trusted",
        ),
        _declared(
            "payload_sha256_verified",
            "report.meta",
            "loaded and status == ok and payload_sha256 is not null",
        ),
        _declared(
            "trusted",
            "surfaces baseline resolvers",
            "trusted_for_diff, set exactly when loaded is set",
        ),
    ),
    "clone_novelty": (
        *_novelty("function or block clone"),
        _declared(
            "new_clones",
            "canonical.comparison_projection",
            "count of new function and block clone findings; null when "
            "neither clone lane is compared",
        ),
    ),
    "comparison_availability": (
        *_baseline_identity("canonical.comparison_rows availability owner"),
        _stored(
            "availability",
            "canonical.comparison_rows availability owner",
            "compared / not_compared / unavailable; the fourth state is a "
            "disabled capability, never a word here",
        ),
        _stored(
            "lane",
            "canonical.comparison_rows availability owner",
            "key: one of the lanes a comparison has a term for",
        ),
    ),
    "complexity_novelty": _novelty("design complexity"),
    "coupling_novelty": _novelty("design coupling"),
    "dead_symbol_novelty": _novelty("dead-code unused symbol"),
    "dependency_cycle_novelty": _novelty("design dependency cycle"),
    "health_delta": (
        *_metric_delta(
            "health_result",
            "health_delta (MetricsDiff.health_delta), the score delta; present "
            "iff the document states the health comparison "
            "(metrics.families.health.summary.baseline_diff_available)",
        ),
        _declared(
            "baseline_diff_available",
            "canonical.evaluation_projection",
            "a health_delta row exists",
        ),
    ),
    "disabled_capabilities": (
        *_baseline_identity("report.document.builder baseline projection"),
        _stored(
            "lane",
            "report.document.builder baseline projection",
            "key: an observation lane the run's contract did not enable",
        ),
    ),
    "lane_trust": (
        *_baseline_identity("report.document.builder baseline projection"),
        _stored("lane", "baseline.container_trust", "key: the observation lane"),
        _stored(
            "reason",
            "baseline.container_trust",
            "LaneTrustReason, or baseline_missing / root_unverified",
        ),
        _stored("status", "baseline.container_trust", "trusted / unavailable"),
    ),
    "metrics_baseline_witness": (
        *_baseline_identity("report.document.builder baseline projection"),
        _stored("loaded", "metrics baseline resolver", "meta.metrics_baseline"),
        _stored(
            "payload_sha256", "report.meta", "meta.metrics_baseline.payload_sha256"
        ),
        _stored("schema_version", "report.meta", "meta.metrics_baseline"),
        _stored("status", "metrics baseline resolver", "meta.metrics_baseline"),
        _declared(
            "payload_sha256_verified",
            "report.meta",
            "loaded and status == ok and payload_sha256 is not null",
        ),
        _declared(
            "trusted",
            "surfaces baseline resolvers",
            "trusted_for_diff, set exactly when loaded is set",
        ),
    ),
}

#: Comparison families that are ONE record per run (``None`` is the typed
#: absence), never a keyed row set.
COMPARISON_RECORD_FAMILIES: Final[frozenset[str]] = frozenset(
    {"baseline_witness", "metrics_baseline_witness"}
)


def comparison_stored_fields(family: str) -> tuple[str, ...]:
    """The stored fields of one comparison family, in sorted order."""
    return tuple(
        sorted(
            declaration.field
            for declaration in COMPARISON_FAMILY_FIELDS[family]
            if declaration.stored
        )
    )


# ---------------------------------------------------------------------------
# Canonical epoch E3 (2026-09-27): the evaluation tier.
#
# Internal model and store state until the wire-revision bump, exactly as the
# comparison tier: every declaration is ``wire=False`` and the analysis wire
# gate refuses the families.  A stored evaluation fact is what THIS run
# concluded under its own request; a value derived from one through its named
# owner is declared and never stored.
# ---------------------------------------------------------------------------

_EVALUATION_FACT: Final = "evaluation_fact"


def _evaluated(field: str, owner: str, derivation: str) -> FieldDeclaration:
    return FieldDeclaration(
        field, _EVALUATION_FACT, owner, derivation, stored=True, wire=False
    )


_REQUEST_KEY: Final = (
    "the request identity (contracts.evaluation.gate_thresholds_digest, "
    "report.document.integrity.build_evaluation_contract); key"
)

EVALUATION_FAMILY_FIELDS: Final[dict[str, tuple[FieldDeclaration, ...]]] = {
    "evaluation_contract": (
        _evaluated(
            "active_gate_lane_requirements",
            "report.gates.evaluator",
            "each requested gate and the lanes it reads, under the run's lanes",
        ),
        _evaluated("gate_algorithm_revision", "contracts", "GATE_ALGORITHM_REVISION"),
        _evaluated("gate_lane_matrix_version", "contracts", "GATE_LANE_MATRIX_VERSION"),
        _evaluated("gate_thresholds_digest", "report.document.integrity", _REQUEST_KEY),
        _evaluated(
            "health_algorithm_revision", "contracts", "HEALTH_ALGORITHM_REVISION"
        ),
        _evaluated(
            "health_input_lanes",
            "report.gates.evaluator",
            "HEALTH_INPUT_LANES the run enabled",
        ),
        _evaluated(
            "health_input_manifest_version",
            "contracts",
            "HEALTH_INPUT_MANIFEST_VERSION",
        ),
        _evaluated(
            "health_params",
            "contracts.report_identity.realized_health_params",
            "the realized health parameters, dotted names; empty iff no health "
            "verdict was computed",
        ),
        _declared(
            "health_params_digest",
            "report.document.integrity",
            "sha256 of the canonical health parameter mapping",
        ),
    ),
    "evaluation_request": (
        _evaluated("gate_thresholds_digest", "report.document.integrity", _REQUEST_KEY),
        _evaluated(
            "terms",
            "report.gates.evaluator.MetricGateConfig",
            "every gate term by name, as uttered (evaluation.request)",
        ),
    ),
    "finding_evaluation": (
        _evaluated(
            "clone_type",
            "report.suggestions.classify_clone_type",
            "clone findings only",
        ),
        _evaluated("confidence", "report.document findings", "high / medium / low"),
        _evaluated(
            "finding_id",
            "codeclone.findings.ids",
            "key: the published finding id; the reference to the finding",
        ),
        _evaluated(
            "priority",
            "report.document._common._priority",
            "severity rank / effort weight",
        ),
        _evaluated("severity", "report.document findings", "critical / warning / info"),
    ),
    "gate_outcome": (
        _evaluated("exit_code", "report.gates.evaluator", "0 / 2 / 3"),
        _evaluated("gate_thresholds_digest", "report.document.integrity", _REQUEST_KEY),
        _evaluated("reasons", "report.gates.evaluator", "in the evaluator's order"),
        _evaluated("required_lanes", "report.gates.evaluator", "sorted lanes"),
        _evaluated("unavailable_lanes", "report.gates.evaluator", "sorted lanes"),
        _declared("would_fail", "canonical.evaluation_projection", "exit_code != 0"),
    ),
    "health_result": (
        _evaluated("dimensions", "metrics.health", "null iff the score is withheld"),
        _evaluated("grade", "metrics.health", "null iff the score is withheld"),
        _evaluated(
            "health_algorithm_revision",
            "contracts",
            "the revision it was computed under",
        ),
        _evaluated(
            "health_input_manifest_version",
            "contracts",
            "the input manifest it was computed under",
        ),
        _evaluated(
            "population",
            "contracts.observed_population",
            "withholds the score for complete_empty / unmeasured",
        ),
        _evaluated("score", "metrics.health", "0..100, null iff withheld"),
    ),
    "hotlist_selection": (
        _evaluated("finding_id", "report.document.derived", "the selected finding"),
        _evaluated(
            "hotlist",
            "report.document.derived",
            "key: the four derived.hotlists and the suggestions order",
        ),
        _evaluated("rank", "report.document.derived", "key: 1-based position"),
    ),
    "unit_risk_result": (
        _evaluated(
            "band", "metrics complexity / coupling / cohesion", "low/medium/high"
        ),
        _evaluated(
            "dimension", "report.document.metrics", "key: complexity/coupling/cohesion"
        ),
        _evaluated("start_line", "report.document.metrics", "key: declaration site"),
        _evaluated("symbol", "report.document.metrics", "key: the measured unit"),
    ),
}

#: Evaluation families that are ONE record per evaluated run.
EVALUATION_RECORD_FAMILIES: Final[frozenset[str]] = frozenset(
    {"evaluation_contract", "evaluation_request", "gate_outcome", "health_result"}
)


def evaluation_stored_fields(family: str) -> tuple[str, ...]:
    """The stored fields of one evaluation family, in sorted order."""
    return tuple(
        sorted(
            declaration.field
            for declaration in EVALUATION_FAMILY_FIELDS[family]
            if declaration.stored
        )
    )


# The evaluation registry gate, executed at import: every family is declared
# under an evaluation production and carries no foreign-tier field.
require_evaluation_families(
    {family: evaluation_stored_fields(family) for family in EVALUATION_FAMILY_FIELDS}
)


# The comparison registry gate, executed at import beside the analysis wire
# gate: every family is declared under a comparison production, carries no
# foreign-tier field, and — for an annotation — shares no field with its
# subject.  Declaration-only columns are not passed, as above.
require_comparison_families(
    {
        family: tuple(
            declaration.field for declaration in declarations if declaration.stored
        )
        for family, declarations in COMPARISON_FAMILY_FIELDS.items()
    },
    {
        **{
            family: tuple(
                declaration.field
                for declaration in declarations
                if declaration.stored or declaration.wire
            )
            for family, declarations in FACT_FAMILY_FIELDS.items()
        },
        # Canonical epoch E3: the health delta annotates an evaluation family.
        **{
            family: evaluation_stored_fields(family)
            for family in EVALUATION_FAMILY_FIELDS
        },
    },
)
