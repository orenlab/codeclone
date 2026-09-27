# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The ratified analysis/comparison/evaluation grammar as an executable
contract (ruling 2026-08-24 §4), backend P0 step 3.

Every canonical fact family declares WHAT it is — one production of the
ratified grammar (``semantic_kind``) — and its tier is DERIVED from that
production, never written down beside it.  There is no tier field to
forget and no tier field to mis-set: a family without a declaration
cannot pass the wire gate, and a family whose production belongs to
another tier cannot enter the analysis wire.  The registry executes
:func:`require_analysis_wire_families` at import, so the gate sits on the
real path every encode, decode, ingest and test session takes — a
declaration with no structural path to the decision it names is narration
(the measured ``RISK_OBSERVATIONS_KEY`` precedent), and this module
exists to not repeat it.

The ratified productions (§4, verbatim tiers)::

    ANALYSIS:   source/input snapshot witnesses · analysis contract ·
                normalized findings/facts · run population ·
                external observations
    COMPARISON: baseline state/scope/root witness · per-lane trust ·
                availability/refusal · novelty facts · metric-baseline
                identity/results · deltas · disabled capabilities
    EVALUATION: evaluation contract revisions · evaluation request ·
                health result · gate inputs/outcomes · verdict/refusal
                facts

The finding/novelty split is structural, not conventional: ``novelty``,
``delta`` and ``metric-baseline result`` productions are ANNOTATIONS — a
declaration of one of these kinds MUST name ``subject_family`` (the fact
it annotates, referenced by identity) and an entity declaration MUST NOT.
A clone finding and its novelty are therefore two records in two tiers by
construction; collapsing novelty back into the finding row trips the
field-morphology gate instead of quietly shipping.

Field morphology is the second, independent witness.  The marker
vocabularies below are MEASURED, not invented: on the live canonical
report of this repository (231 MB, schema 3.2, b954552f, 2026-08-31) the
legacy document carries 589 marker-key occurrences outside their tier
house (142 finding rows with embedded ``novelty``, 116+116
``novelty``/``novelty_reason`` on design groups, 26+26 on structural
groups, per-family ``new_*``/``*_delta``/``baseline_diff_available``
summaries), while the canonical substrate itself measures clean — 0 of 90
stored/wire fields carry a foreign marker.  Tokens the measurement proved
ambiguous are deliberately NOT markers: ``score`` lives on both sides
(``candidates.score`` and the overloaded-modules scores are analysis-side
classification, the health score is evaluation), ``weight`` is the
module-graph edge weight 112 times on the same corpus (analysis), never
the health weight, ``disabled`` names an analysis tier-state as often as
a comparison capability, and ``availability``/``refusal`` are §4
productions of TWO tiers.  A marker that cannot discriminate is a false
instrument and stays out; the dated numbers above are observations of one
corpus, never invariants.

Canonical epoch E2 (2026-09-26) lands the first comparison families, and
with them the guard this module used to name as absent: an annotation
family's payload must be DISJOINT from its subject's (the "annotation must
reference, never embed" rule beyond the reference itself) — executed by
:func:`require_comparison_families` against the real field vocabularies of
both families, because the first real comparison family is the first input
that can reach it.  The families live in the model and the store only: they
join no wire section until their own wire-revision bump (§10), and the
analysis wire gate below still refuses them.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Final

from codeclone.canonical.errors import CanonicalModelError

ANALYSIS_TIER: Final = "analysis"
COMPARISON_TIER: Final = "comparison"
EVALUATION_TIER: Final = "evaluation"

GRAMMAR_TIERS: Final[frozenset[str]] = frozenset(
    {ANALYSIS_TIER, COMPARISON_TIER, EVALUATION_TIER}
)


class GrammarViolation(CanonicalModelError):
    """A fact family placed, declared, or shaped against the §4 grammar."""


#: The closed production vocabulary of the ratified grammar: each semantic
#: kind IS one §4 production, and the tier is a property of the production.
#: Declaring a kind outside this vocabulary is refused, so a new fact
#: family cannot invent a tier or skip having one.
SEMANTIC_KIND_TIERS: Final[Mapping[str, str]] = {
    # ANALYSIS productions.
    "source_snapshot_witness": ANALYSIS_TIER,
    "analysis_contract": ANALYSIS_TIER,
    "normalized_finding": ANALYSIS_TIER,
    "normalized_fact": ANALYSIS_TIER,
    "run_population": ANALYSIS_TIER,
    "external_observation": ANALYSIS_TIER,
    # COMPARISON productions.
    "baseline_witness": COMPARISON_TIER,
    "lane_trust": COMPARISON_TIER,
    "comparison_availability": COMPARISON_TIER,
    "novelty_annotation": COMPARISON_TIER,
    "metric_baseline_result": COMPARISON_TIER,
    "delta_annotation": COMPARISON_TIER,
    "disabled_capability": COMPARISON_TIER,
    # EVALUATION productions.
    "evaluation_contract": EVALUATION_TIER,
    "evaluation_request": EVALUATION_TIER,
    "health_result": EVALUATION_TIER,
    "gate_outcome": EVALUATION_TIER,
    "verdict": EVALUATION_TIER,
}

#: Annotation productions: facts ABOUT another fact.  The §4 split — a
#: clone finding and its novelty are never one record — is carried by
#: form: an annotation declaration must reference its subject family, an
#: entity declaration must not.
ANNOTATION_KINDS: Final[frozenset[str]] = frozenset(
    {"novelty_annotation", "delta_annotation", "metric_baseline_result"}
)

#: Which tiers an annotation's subject may live in.  Novelty annotates
#: analysis facts only (§4: finding → analysis, novelty → comparison
#: annotation/reference).  Deltas and metric-baseline results may also
#: annotate evaluation results — the measured ``metrics.summary.health``
#: shape, where the delta of the health score is a comparison fact about
#: an evaluation quantity.  No annotation ever annotates comparison:
#: annotations do not annotate annotations.
ANNOTATION_SUBJECT_TIERS: Final[Mapping[str, frozenset[str]]] = {
    "novelty_annotation": frozenset({ANALYSIS_TIER}),
    "delta_annotation": frozenset({ANALYSIS_TIER, EVALUATION_TIER}),
    "metric_baseline_result": frozenset({ANALYSIS_TIER, EVALUATION_TIER}),
}

#: Field-name tokens that spell comparison semantics.  Each entry is
#: §3/§4-named AND measured present in the legacy document (module
#: docstring); ambiguous tokens are excluded by measurement, not taste.
COMPARISON_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {"baseline", "delta", "known", "new", "novelty", "trust", "trusted"}
)

#: Field-name tokens that spell evaluation semantics.  ``verdict`` is
#: ruling-named (§3) and measured at zero occurrences in the current
#: document — kept on ruling authority, the one vocabulary entry whose
#: basis is the ratified text alone.
EVALUATION_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {"gate", "gates", "grade", "health", "verdict"}
)


@dataclass(frozen=True, slots=True)
class FamilyGrammar:
    """One family's grammar declaration: its §4 production, and — for
    annotation productions only — the family it annotates."""

    semantic_kind: str
    subject_family: str | None = None


#: The grammar declaration of every wave-1..4 wire family and, since
#: canonical epochs E2 and E3, of every comparison and evaluation family of
#: the model and store.
#: The tier of each family is derived from its production via
#: :data:`SEMANTIC_KIND_TIERS`; there is deliberately no tier literal
#: anywhere in this table.
FAMILY_SEMANTIC_GRAMMAR: Final[Mapping[str, FamilyGrammar]] = {
    "adoption_counts": FamilyGrammar("normalized_fact"),
    "analysis_population": FamilyGrammar("run_population"),
    "api_symbols": FamilyGrammar("normalized_fact"),
    "candidates": FamilyGrammar("normalized_fact"),
    "clone_groups": FamilyGrammar("normalized_finding"),
    # Canonical epoch E1 (2026-09-25): the three design hotspot families
    # are the document's grouped design findings, classified once by the
    # producer under the run's own thresholds.
    "cohesion_hotspots": FamilyGrammar("normalized_finding"),
    "complexity_hotspots": FamilyGrammar("normalized_finding"),
    "contracts": FamilyGrammar("normalized_fact"),
    "coupling_cohesion_observations": FamilyGrammar("normalized_fact"),
    "coupling_hotspots": FamilyGrammar("normalized_finding"),
    # E1: the external Cobertura join — a §4 "external observation", the
    # one production whose facts come from outside the analyzed source.
    "coverage_join": FamilyGrammar("external_observation"),
    "coverage_units": FamilyGrammar("external_observation"),
    "dead_code_observations": FamilyGrammar("normalized_finding"),
    # E1: the dead-code lane's population counters — the §4 "run
    # population" production, the ``run_scalars`` shape.
    "dead_code_summary": FamilyGrammar("run_population"),
    "dead_symbol_groups": FamilyGrammar("normalized_finding"),
    "dependency_cycles": FamilyGrammar("normalized_fact"),
    "dependency_occurrences": FamilyGrammar("normalized_fact"),
    "dependency_relations": FamilyGrammar("normalized_fact"),
    "file_modules": FamilyGrammar("normalized_fact"),
    "graph_nodes": FamilyGrammar("normalized_fact"),
    "import_observations": FamilyGrammar("normalized_fact"),
    "overloaded_modules": FamilyGrammar("normalized_fact"),
    "relationship_observations": FamilyGrammar("normalized_fact"),
    "risk_observations": FamilyGrammar("normalized_fact"),
    "run_scalars": FamilyGrammar("run_population"),
    "security_surfaces": FamilyGrammar("normalized_fact"),
    "semantic_edges": FamilyGrammar("normalized_fact"),
    "sink_roles": FamilyGrammar("normalized_fact"),
    "structural_groups": FamilyGrammar("normalized_finding"),
    "suppressed_clone_groups": FamilyGrammar("normalized_finding"),
    "unit_spans": FamilyGrammar("normalized_fact"),
    "unreachable_statement_groups": FamilyGrammar("normalized_finding"),
    "violations": FamilyGrammar("normalized_finding"),
    # Canonical epoch E2 (2026-09-26): the comparison tier, bound to the
    # seven existing productions.  Internal model and store state until the
    # wire-revision bump; the analysis wire gate refuses every one of them.
    "adoption_delta": FamilyGrammar(
        "delta_annotation", subject_family="adoption_counts"
    ),
    "api_surface_delta": FamilyGrammar(
        "delta_annotation", subject_family="api_symbols"
    ),
    "baseline_witness": FamilyGrammar("baseline_witness"),
    "clone_novelty": FamilyGrammar("novelty_annotation", subject_family="clone_groups"),
    "comparison_availability": FamilyGrammar("comparison_availability"),
    "complexity_novelty": FamilyGrammar(
        "novelty_annotation", subject_family="complexity_hotspots"
    ),
    "coupling_novelty": FamilyGrammar(
        "novelty_annotation", subject_family="coupling_hotspots"
    ),
    "dead_symbol_novelty": FamilyGrammar(
        "novelty_annotation", subject_family="dead_symbol_groups"
    ),
    "dependency_cycle_novelty": FamilyGrammar(
        "novelty_annotation", subject_family="dependency_cycles"
    ),
    "disabled_capabilities": FamilyGrammar("disabled_capability"),
    "lane_trust": FamilyGrammar("lane_trust"),
    "metrics_baseline_witness": FamilyGrammar("baseline_witness"),
    # Canonical epoch E3 (2026-09-27): the evaluation tier, bound to the five
    # existing productions, and the health delta — a comparison fact about an
    # evaluation quantity, the first annotation whose subject is evaluation.
    # Internal model and store state until the wire-revision bump.
    "evaluation_contract": FamilyGrammar("evaluation_contract"),
    "evaluation_request": FamilyGrammar("evaluation_request"),
    "finding_evaluation": FamilyGrammar("verdict"),
    "gate_outcome": FamilyGrammar("gate_outcome"),
    "health_delta": FamilyGrammar("delta_annotation", subject_family="health_result"),
    "health_result": FamilyGrammar("health_result"),
    "hotlist_selection": FamilyGrammar("verdict"),
    "unit_risk_result": FamilyGrammar("health_result"),
}


def tier_of_kind(semantic_kind: str) -> str:
    """The tier of one §4 production; unknown productions are refused."""
    tier = SEMANTIC_KIND_TIERS.get(semantic_kind)
    if tier is None:
        raise GrammarViolation(
            f"semantic kind {semantic_kind!r} is not a production of the "
            f"ratified grammar"
        )
    return tier


def tier_of_family(
    family: str,
    declarations: Mapping[str, FamilyGrammar] = FAMILY_SEMANTIC_GRAMMAR,
) -> str:
    """The derived tier of one declared family; undeclared is refused."""
    declaration = declarations.get(family)
    if declaration is None:
        raise GrammarViolation(
            f"fact family {family!r} has no grammar declaration: a family "
            f"without a semantic kind has no tier"
        )
    return tier_of_kind(declaration.semantic_kind)


def field_morphology(field_name: str) -> str | None:
    """The tier a field NAME spells, or ``None`` for neutral names.

    Comparison markers dominate evaluation markers: ``health_delta`` is
    the delta OF a health result — a comparison fact about an evaluation
    quantity (the measured ``metrics.summary.health`` shape).
    """
    tokens = set(field_name.replace("-", "_").split("_"))
    if tokens & COMPARISON_FIELD_MARKERS:
        return COMPARISON_TIER
    if tokens & EVALUATION_FIELD_MARKERS:
        return EVALUATION_TIER
    return None


def require_declaration(
    family: str,
    declaration: FamilyGrammar,
    declarations: Mapping[str, FamilyGrammar],
) -> str:
    """Refuse a malformed declaration; return the family's derived tier.

    An annotation production must reference a declared subject family of
    an admitted tier — the structural half of the finding/novelty split.
    An entity production must not carry a subject at all.
    """
    tier = tier_of_kind(declaration.semantic_kind)
    if declaration.semantic_kind in ANNOTATION_KINDS:
        if declaration.subject_family is None:
            raise GrammarViolation(
                f"annotation family {family!r} "
                f"({declaration.semantic_kind}) must reference the family "
                f"it annotates: a novelty without its finding is the "
                f"collapsed record the grammar forbids"
            )
        subject = declarations.get(declaration.subject_family)
        if subject is None:
            raise GrammarViolation(
                f"annotation family {family!r} references undeclared "
                f"subject family {declaration.subject_family!r}"
            )
        subject_tier = tier_of_kind(subject.semantic_kind)
        admitted = ANNOTATION_SUBJECT_TIERS[declaration.semantic_kind]
        if subject_tier not in admitted:
            raise GrammarViolation(
                f"annotation family {family!r} "
                f"({declaration.semantic_kind}) may not annotate "
                f"{subject_tier}-tier family "
                f"{declaration.subject_family!r}; admitted subject tiers: "
                f"{', '.join(sorted(admitted))}"
            )
    elif declaration.subject_family is not None:
        raise GrammarViolation(
            f"entity family {family!r} ({declaration.semantic_kind}) "
            f"must not reference a subject family: only annotation "
            f"productions annotate"
        )
    return tier


def require_tier_pure_fields(
    family: str, tier: str, field_names: Iterable[str]
) -> None:
    """Refuse fields whose name morphology belongs to a foreign tier.

    Analysis families must be marker-free in both directions; comparison
    and evaluation families may carry their own tier's markers plus
    neutral names.  This is the gate the measured legacy mixing walks
    into: ``novelty`` on a finding row, ``gate_relevant`` on a finding
    row, ``new_*`` on a metrics row all red here.
    """
    for field_name in sorted(field_names):
        morphology = field_morphology(field_name)
        if morphology is not None and morphology != tier:
            raise GrammarViolation(
                f"field {field_name!r} of {tier}-tier family {family!r} "
                f"spells {morphology}-tier semantics: the fact belongs in "
                f"its own tier, referenced — never embedded"
            )


def require_analysis_wire_families(
    families: Mapping[str, Iterable[str]],
    declarations: Mapping[str, FamilyGrammar] = FAMILY_SEMANTIC_GRAMMAR,
) -> None:
    """The wire gate: the analysis facts section admits analysis only.

    ``families`` maps each wire fact family to its stored/wire field
    names.  Refused, in deterministic order: a family without a grammar
    declaration; a family whose derived tier is not analysis; a field
    whose morphology spells another tier; and an analysis-tier
    declaration for a family the wire does not carry (a dangling
    declaration is narration, and narration rots).  Comparison and
    evaluation declarations are NOT required to appear here — they join
    their own wire section with their own revision bump (§10).
    """
    for family in sorted(families):
        declaration = declarations.get(family)
        if declaration is None:
            raise GrammarViolation(
                f"wire fact family {family!r} has no grammar declaration: "
                f"a family enters the wire only with its semantic kind"
            )
        tier = require_declaration(family, declaration, declarations)
        if tier != ANALYSIS_TIER:
            raise GrammarViolation(
                f"wire fact family {family!r} is {tier}-tier "
                f"({declaration.semantic_kind}) and cannot live in the "
                f"analysis facts section: comparison and evaluation "
                f"families join their own wire section with their own "
                f"revision bump"
            )
        require_tier_pure_fields(family, tier, families[family])
    for family in sorted(declarations):
        if (
            tier_of_family(family, declarations) == ANALYSIS_TIER
            and family not in families
        ):
            raise GrammarViolation(
                f"analysis-tier family {family!r} is declared but absent "
                f"from the wire registry: a dangling declaration is "
                f"narration"
            )


def _require_registry_families(
    tier: str,
    families: Mapping[str, Iterable[str]],
    declarations: Mapping[str, FamilyGrammar],
) -> Iterator[tuple[str, FamilyGrammar, tuple[str, ...]]]:
    """The checks every non-wire tier registry shares, family by family in
    name order: a declaration exists, its derived tier is the registry's, and
    no field spells another tier.  Yields each admitted family for the
    registry's own further checks."""
    for family in sorted(families):
        declaration = declarations.get(family)
        if declaration is None:
            raise GrammarViolation(
                f"{tier} family {family!r} has no grammar declaration"
            )
        family_tier = require_declaration(family, declaration, declarations)
        if family_tier != tier:
            raise GrammarViolation(
                f"family {family!r} is {family_tier}-tier "
                f"({declaration.semantic_kind}) and cannot live in the "
                f"{tier} registry"
            )
        fields = tuple(families[family])
        require_tier_pure_fields(family, family_tier, fields)
        yield family, declaration, fields


def _require_no_dangling(
    tier: str,
    families: Mapping[str, Iterable[str]],
    declarations: Mapping[str, FamilyGrammar],
) -> None:
    for family in sorted(declarations):
        if tier_of_family(family, declarations) == tier and family not in families:
            raise GrammarViolation(
                f"{tier}-tier family {family!r} is declared but absent "
                f"from the {tier} registry: a dangling declaration is "
                f"narration"
            )


def require_comparison_families(
    families: Mapping[str, Iterable[str]],
    subject_fields: Mapping[str, Iterable[str]],
    declarations: Mapping[str, FamilyGrammar] = FAMILY_SEMANTIC_GRAMMAR,
) -> None:
    """The comparison-tier registry gate (canonical epoch E2).

    ``families`` maps each comparison family to its stored field names;
    ``subject_fields`` maps each family an annotation may annotate — the
    analysis families and, since canonical epoch E3, the evaluation families —
    to ITS stored field names.  Refused, in deterministic order: a family
    without a grammar declaration; a family whose derived tier is not
    comparison; a field whose morphology spells another tier; an annotation
    whose payload shares a field with its subject's (the annotation
    references its subject and never embeds it); and a comparison-tier
    declaration no registry family answers (a dangling declaration is
    narration).
    """
    for family, declaration, fields in _require_registry_families(
        COMPARISON_TIER, families, declarations
    ):
        if declaration.subject_family is None:
            continue
        embedded = sorted(
            set(fields) & set(subject_fields.get(declaration.subject_family, ()))
        )
        if embedded:
            raise GrammarViolation(
                f"annotation family {family!r} embeds fields "
                f"{embedded!r} of its subject "
                f"{declaration.subject_family!r}: an annotation references "
                f"its subject, it never carries it"
            )
    _require_no_dangling(COMPARISON_TIER, families, declarations)


def require_evaluation_families(
    families: Mapping[str, Iterable[str]],
    declarations: Mapping[str, FamilyGrammar] = FAMILY_SEMANTIC_GRAMMAR,
) -> None:
    """The evaluation-tier registry gate (canonical epoch E3).

    ``families`` maps each evaluation family to its stored field names.
    Refused, in deterministic order: a family without a grammar declaration;
    a family whose derived tier is not evaluation; a field whose morphology
    spells another tier (a ``baseline_*`` or ``*_delta`` column on a verdict
    row is the comparison fact embedded in it); and an evaluation-tier
    declaration no registry family answers.  No evaluation production is an
    annotation (``ANNOTATION_KINDS`` are comparison productions), so there is
    no subject to check.
    """
    for _admitted in _require_registry_families(
        EVALUATION_TIER, families, declarations
    ):
        continue
    _require_no_dangling(EVALUATION_TIER, families, declarations)


def require_house_families(
    tier: str,
    field_names: Iterable[str],
    declarations: Mapping[str, FamilyGrammar] = FAMILY_SEMANTIC_GRAMMAR,
) -> None:
    """Refuse a fact-house field naming a family of another tier.

    The three houses of ``CanonicalFacts`` are tier residences; a field
    of one house must name a declared family whose derived tier is that
    house's tier — a verdict family in the comparison house reds here,
    exactly as a novelty family in the analysis house does.
    """
    if tier not in GRAMMAR_TIERS:
        raise GrammarViolation(f"unknown grammar tier {tier!r}")
    for field_name in sorted(field_names):
        family_tier = tier_of_family(field_name, declarations)
        if family_tier != tier:
            raise GrammarViolation(
                f"house field {field_name!r} names a {family_tier}-tier "
                f"family and cannot live in the {tier} house"
            )


def require_closed_vocabularies(
    comparison_markers: frozenset[str] = COMPARISON_FIELD_MARKERS,
    evaluation_markers: frozenset[str] = EVALUATION_FIELD_MARKERS,
    annotation_kinds: frozenset[str] = ANNOTATION_KINDS,
    kind_tiers: Mapping[str, str] = SEMANTIC_KIND_TIERS,
    subject_tiers: Mapping[str, frozenset[str]] = ANNOTATION_SUBJECT_TIERS,
) -> None:
    """Self-integrity of the closed vocabularies, executed at import.

    Parameterized so every refusal branch is reachable by a poisoned
    fixture — an integrity guard no input can trip is theater.
    """
    overlap = comparison_markers & evaluation_markers
    if overlap:
        raise GrammarViolation(
            f"field markers {sorted(overlap)!r} claim two tiers: a marker "
            f"that cannot discriminate is a false instrument"
        )
    undeclared_annotations = annotation_kinds - set(kind_tiers)
    if undeclared_annotations:
        raise GrammarViolation(
            f"annotation kinds {sorted(undeclared_annotations)!r} are not "
            f"grammar productions"
        )
    if set(subject_tiers) != annotation_kinds:
        raise GrammarViolation(
            "every annotation kind needs exactly one subject-tier rule"
        )
    for kind, admitted in sorted(subject_tiers.items()):
        foreign = admitted - GRAMMAR_TIERS
        if foreign or COMPARISON_TIER in admitted:
            raise GrammarViolation(
                f"annotation kind {kind!r} admits illegal subject tiers: "
                f"annotations never annotate annotations"
            )


require_closed_vocabularies()
for _family, _declaration in sorted(FAMILY_SEMANTIC_GRAMMAR.items()):
    require_declaration(_family, _declaration, FAMILY_SEMANTIC_GRAMMAR)
del _family, _declaration
