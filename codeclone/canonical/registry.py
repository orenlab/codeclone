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

from codeclone.canonical.grammar import require_analysis_wire_families

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
            "files_analyzed",
            ANALYSIS_FACT,
            "run_inventory_producer",
            "observed run-population scalar (zero is measured)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "files_cached",
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
    {"analysis_population", "run_scalars"}
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
