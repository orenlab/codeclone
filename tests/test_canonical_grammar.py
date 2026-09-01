# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Pins for the executable §4 grammar (ruling 2026-08-24), step 3.

Independence law of these pins: every expected tier and kind below is an
INDEPENDENT literal fixture, never read back from
``FAMILY_SEMANTIC_GRAMMAR`` or ``SEMANTIC_KIND_TIERS`` — a pin that asks
the production table what the production table says proves only that the
table was read twice.  Flipping one production entry must red here.

The wiring pin reads the registry SOURCE (the
``test_canonical_facts_composition`` precedent): the gate is enforcement
only while the registry executes it at import, so removing that one call
must red even though every behavioral pin on the gate function itself
would stay green.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from codeclone.canonical.grammar import (
    ANALYSIS_TIER,
    COMPARISON_FIELD_MARKERS,
    COMPARISON_TIER,
    EVALUATION_FIELD_MARKERS,
    EVALUATION_TIER,
    FAMILY_SEMANTIC_GRAMMAR,
    FamilyGrammar,
    GrammarViolation,
    field_morphology,
    require_analysis_wire_families,
    require_closed_vocabularies,
    require_declaration,
    require_house_families,
    require_tier_pure_fields,
    tier_of_family,
    tier_of_kind,
)

_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "codeclone" / "canonical" / "registry.py"
)

# The independent tier fixture: what each wire family IS under §4, spelled
# here by hand.  clone_groups / dead_code_observations / violations are
# the finding populations; run_scalars is the §4 "run population"; the
# rest are normalized facts.  All of it is analysis — comparison and
# evaluation families do not exist in the wave-1..4 wire.
_EXPECTED_TIERS: dict[str, str] = {
    "adoption_counts": "analysis",
    "analysis_population": "analysis",
    "api_symbols": "analysis",
    "candidates": "analysis",
    "clone_groups": "analysis",
    "contracts": "analysis",
    "coupling_cohesion_observations": "analysis",
    "dead_code_observations": "analysis",
    "dependency_cycles": "analysis",
    "dependency_occurrences": "analysis",
    "dependency_relations": "analysis",
    "file_modules": "analysis",
    "graph_nodes": "analysis",
    "risk_observations": "analysis",
    "run_scalars": "analysis",
    "security_surfaces": "analysis",
    "semantic_edges": "analysis",
    "sink_roles": "analysis",
    "violations": "analysis",
}

_EXPECTED_KINDS: dict[str, str] = {
    "adoption_counts": "normalized_fact",
    "analysis_population": "run_population",
    "api_symbols": "normalized_fact",
    "candidates": "normalized_fact",
    "clone_groups": "normalized_finding",
    "contracts": "normalized_fact",
    "coupling_cohesion_observations": "normalized_fact",
    "dead_code_observations": "normalized_finding",
    "dependency_cycles": "normalized_fact",
    "dependency_occurrences": "normalized_fact",
    "dependency_relations": "normalized_fact",
    "file_modules": "normalized_fact",
    "graph_nodes": "normalized_fact",
    "risk_observations": "normalized_fact",
    "run_scalars": "run_population",
    "security_surfaces": "normalized_fact",
    "semantic_edges": "normalized_fact",
    "sink_roles": "normalized_fact",
    "violations": "normalized_finding",
}


def _wire_field_names() -> dict[str, tuple[str, ...]]:
    from codeclone.canonical.registry import FACT_FAMILY_FIELDS

    return {
        family: tuple(
            declaration.field
            for declaration in declarations
            if declaration.stored or declaration.wire
        )
        for family, declarations in FACT_FAMILY_FIELDS.items()
    }


# ---------------------------------------------------------------------------
# Tier derivation: total on the wire, pinned against independent literals.
# ---------------------------------------------------------------------------


def test_every_wire_family_matches_the_independent_tier_fixture() -> None:
    assert sorted(_wire_field_names()) == sorted(_EXPECTED_TIERS)
    for family, expected_tier in sorted(_EXPECTED_TIERS.items()):
        assert tier_of_family(family) == expected_tier, family


def test_every_wire_family_matches_the_independent_kind_fixture() -> None:
    assert sorted(FAMILY_SEMANTIC_GRAMMAR) == sorted(_EXPECTED_KINDS)
    for family, expected_kind in sorted(_EXPECTED_KINDS.items()):
        assert FAMILY_SEMANTIC_GRAMMAR[family].semantic_kind == expected_kind, family


def test_production_tiers_are_the_ratified_ones() -> None:
    assert tier_of_kind("normalized_finding") == "analysis"
    assert tier_of_kind("run_population") == "analysis"
    assert tier_of_kind("external_observation") == "analysis"
    assert tier_of_kind("novelty_annotation") == "comparison"
    assert tier_of_kind("baseline_witness") == "comparison"
    assert tier_of_kind("delta_annotation") == "comparison"
    assert tier_of_kind("health_result") == "evaluation"
    assert tier_of_kind("gate_outcome") == "evaluation"
    assert tier_of_kind("verdict") == "evaluation"


def test_unknown_production_is_refused() -> None:
    with pytest.raises(GrammarViolation, match="not a production"):
        tier_of_kind("vibes_fact")


def test_undeclared_family_has_no_tier() -> None:
    with pytest.raises(GrammarViolation, match="no grammar declaration"):
        tier_of_family("mystery_counts")


# ---------------------------------------------------------------------------
# Field morphology: the measured marker vocabulary, both directions.
# ---------------------------------------------------------------------------


def test_field_morphology_spells_the_measured_legacy_mixing() -> None:
    # Comparison shapes measured in the legacy document (589 misplaced
    # occurrences @ b954552f): novelty on finding rows, new_*/delta/
    # baseline_diff_available on metrics rows, lane trust on baseline.
    assert field_morphology("novelty") == "comparison"
    assert field_morphology("novelty_reason") == "comparison"
    assert field_morphology("baseline_diff_available") == "comparison"
    assert field_morphology("new_high_risk") == "comparison"
    assert field_morphology("docstring_delta") == "comparison"
    assert field_morphology("known") == "comparison"
    assert field_morphology("sorted_lane_trust") == "comparison"
    # Evaluation shapes: gate routing on finding rows, health verdicts.
    assert field_morphology("gate_relevant") == "evaluation"
    assert field_morphology("health") == "evaluation"
    assert field_morphology("grade") == "evaluation"
    assert field_morphology("verdict") == "evaluation"


def test_field_morphology_dominance_is_comparison_over_evaluation() -> None:
    # The measured metrics.summary.health shape: the delta OF the health
    # score is a comparison fact about an evaluation quantity.
    assert field_morphology("health_delta") == "comparison"


def test_field_morphology_is_silent_on_neutral_and_ambiguous_names() -> None:
    # Neutral substrate names stay neutral.
    assert field_morphology("numerator") is None
    assert field_morphology("start_line") is None
    assert field_morphology("observation_kind") is None
    # Measured-ambiguous tokens are NOT markers: score lives on both
    # sides (candidates.score is analysis classification, health score is
    # evaluation), weight is the module-graph edge weight 112 times on
    # the same corpus, disabled names an analysis tier-state as often as
    # a comparison capability.
    assert field_morphology("score") is None
    assert field_morphology("average_score") is None
    assert field_morphology("weight") is None
    assert field_morphology("disabled") is None


def test_marker_vocabularies_are_disjoint() -> None:
    assert not COMPARISON_FIELD_MARKERS & EVALUATION_FIELD_MARKERS


# ---------------------------------------------------------------------------
# Misplacement reds: one test per tier axis, both directions.
# ---------------------------------------------------------------------------


def test_novelty_field_on_an_analysis_family_is_refused() -> None:
    families = _wire_field_names()
    families["clone_groups"] = (*families["clone_groups"], "novelty")
    with pytest.raises(GrammarViolation, match=r"'novelty'.*comparison-tier"):
        require_analysis_wire_families(families)


def test_evaluation_field_on_an_analysis_family_is_refused() -> None:
    families = _wire_field_names()
    families["clone_groups"] = (*families["clone_groups"], "gate_relevant")
    with pytest.raises(GrammarViolation, match=r"'gate_relevant'.*evaluation-tier"):
        require_analysis_wire_families(families)


def test_comparison_kind_family_cannot_enter_the_analysis_wire() -> None:
    declarations = dict(FAMILY_SEMANTIC_GRAMMAR)
    declarations["clone_novelty"] = FamilyGrammar(
        "novelty_annotation", subject_family="clone_groups"
    )
    families = _wire_field_names()
    families["clone_novelty"] = ("novelty",)
    with pytest.raises(GrammarViolation, match="comparison-tier"):
        require_analysis_wire_families(families, declarations)


def test_evaluation_kind_family_cannot_enter_the_analysis_wire() -> None:
    declarations = dict(FAMILY_SEMANTIC_GRAMMAR)
    declarations["health_results"] = FamilyGrammar("health_result")
    families = _wire_field_names()
    families["health_results"] = ("dimension",)
    with pytest.raises(GrammarViolation, match="evaluation-tier"):
        require_analysis_wire_families(families, declarations)


def test_wire_family_without_a_declaration_is_refused() -> None:
    families = _wire_field_names()
    families["mystery_counts"] = ("numerator",)
    with pytest.raises(GrammarViolation, match="no grammar declaration"):
        require_analysis_wire_families(families)


def test_dangling_analysis_declaration_is_refused() -> None:
    declarations = dict(FAMILY_SEMANTIC_GRAMMAR)
    declarations["ghost_counts"] = FamilyGrammar("normalized_fact")
    with pytest.raises(GrammarViolation, match="dangling declaration"):
        require_analysis_wire_families(_wire_field_names(), declarations)


def test_comparison_and_evaluation_declarations_may_wait_off_wire() -> None:
    # §10: their families join their own wire section later; declaring
    # them must NOT poison the analysis gate.
    declarations = dict(FAMILY_SEMANTIC_GRAMMAR)
    declarations["clone_novelty"] = FamilyGrammar(
        "novelty_annotation", subject_family="clone_groups"
    )
    declarations["health_results"] = FamilyGrammar("health_result")
    require_analysis_wire_families(_wire_field_names(), declarations)


def test_tier_purity_admits_own_tier_markers() -> None:
    require_tier_pure_fields(
        "clone_novelty", COMPARISON_TIER, ("novelty", "novelty_reason")
    )
    require_tier_pure_fields("gate_outcomes", EVALUATION_TIER, ("gate", "verdict"))
    with pytest.raises(GrammarViolation, match=r"'verdict'.*comparison"):
        require_tier_pure_fields("clone_novelty", COMPARISON_TIER, ("verdict",))
    with pytest.raises(GrammarViolation, match=r"'novelty'.*evaluation"):
        require_tier_pure_fields("gate_outcomes", EVALUATION_TIER, ("novelty",))


# ---------------------------------------------------------------------------
# The finding/novelty split is structural.
# ---------------------------------------------------------------------------


def test_annotation_without_a_subject_is_the_forbidden_collapse() -> None:
    with pytest.raises(GrammarViolation, match="collapsed record"):
        require_declaration(
            "clone_novelty",
            FamilyGrammar("novelty_annotation"),
            dict(FAMILY_SEMANTIC_GRAMMAR),
        )


def test_entity_with_a_subject_is_refused() -> None:
    with pytest.raises(GrammarViolation, match="only annotation productions"):
        require_declaration(
            "clone_groups_2",
            FamilyGrammar("normalized_finding", subject_family="clone_groups"),
            dict(FAMILY_SEMANTIC_GRAMMAR),
        )


def test_annotation_of_an_undeclared_subject_is_refused() -> None:
    with pytest.raises(GrammarViolation, match="undeclared subject"):
        require_declaration(
            "clone_novelty",
            FamilyGrammar("novelty_annotation", subject_family="mystery"),
            dict(FAMILY_SEMANTIC_GRAMMAR),
        )


def test_novelty_annotates_analysis_only() -> None:
    declarations = dict(FAMILY_SEMANTIC_GRAMMAR)
    declarations["health_results"] = FamilyGrammar("health_result")
    with pytest.raises(GrammarViolation, match="may not annotate evaluation"):
        require_declaration(
            "health_novelty",
            FamilyGrammar("novelty_annotation", subject_family="health_results"),
            declarations,
        )
    # The accepted §4 shape: novelty referencing its finding family.
    tier = require_declaration(
        "clone_novelty",
        FamilyGrammar("novelty_annotation", subject_family="clone_groups"),
        declarations,
    )
    assert tier == COMPARISON_TIER


def test_delta_may_annotate_an_evaluation_result() -> None:
    # The measured health-delta shape: comparison fact about an
    # evaluation quantity.
    declarations = dict(FAMILY_SEMANTIC_GRAMMAR)
    declarations["health_results"] = FamilyGrammar("health_result")
    tier = require_declaration(
        "health_delta",
        FamilyGrammar("delta_annotation", subject_family="health_results"),
        declarations,
    )
    assert tier == COMPARISON_TIER


# ---------------------------------------------------------------------------
# Houses: model residence agrees with derived tiers.
# ---------------------------------------------------------------------------


def test_analysis_house_fields_are_analysis_tier_families() -> None:
    from codeclone.canonical.model import AnalysisFacts

    field_names = tuple(
        model_field.name for model_field in dataclasses.fields(AnalysisFacts)
    )
    assert field_names, "the analysis house cannot be empty"
    require_house_families(ANALYSIS_TIER, field_names)


def test_comparison_and_evaluation_houses_are_born_empty_today() -> None:
    from codeclone.canonical.model import ComparisonFacts, EvaluationFacts

    assert dataclasses.fields(ComparisonFacts) == ()
    assert dataclasses.fields(EvaluationFacts) == ()


def test_analysis_family_cannot_live_in_a_foreign_house() -> None:
    with pytest.raises(GrammarViolation, match="analysis-tier"):
        require_house_families(COMPARISON_TIER, ("clone_groups",))
    with pytest.raises(GrammarViolation, match="analysis-tier"):
        require_house_families(EVALUATION_TIER, ("clone_groups",))


def test_comparison_family_cannot_live_in_a_foreign_house() -> None:
    declarations = dict(FAMILY_SEMANTIC_GRAMMAR)
    declarations["clone_novelty"] = FamilyGrammar(
        "novelty_annotation", subject_family="clone_groups"
    )
    with pytest.raises(GrammarViolation, match="comparison-tier"):
        require_house_families(ANALYSIS_TIER, ("clone_novelty",), declarations)
    with pytest.raises(GrammarViolation, match="comparison-tier"):
        require_house_families(EVALUATION_TIER, ("clone_novelty",), declarations)
    require_house_families(COMPARISON_TIER, ("clone_novelty",), declarations)


def test_evaluation_family_cannot_live_in_a_foreign_house() -> None:
    declarations = dict(FAMILY_SEMANTIC_GRAMMAR)
    declarations["health_results"] = FamilyGrammar("health_result")
    with pytest.raises(GrammarViolation, match="evaluation-tier"):
        require_house_families(ANALYSIS_TIER, ("health_results",), declarations)
    with pytest.raises(GrammarViolation, match="evaluation-tier"):
        require_house_families(COMPARISON_TIER, ("health_results",), declarations)
    require_house_families(EVALUATION_TIER, ("health_results",), declarations)


def test_unknown_house_tier_is_refused() -> None:
    with pytest.raises(GrammarViolation, match="unknown grammar tier"):
        require_house_families("presentation", ("clone_groups",))


# ---------------------------------------------------------------------------
# The wiring: the registry executes the gate, and the real population
# passes it.
# ---------------------------------------------------------------------------


def test_registry_source_executes_the_wire_gate_at_import() -> None:
    """The gate is enforcement only on the executed path.

    A module-level ``require_analysis_wire_families(...)`` call must
    exist in registry.py — behavioral pins on the gate function stay
    green when the one call is deleted, so the call itself is pinned on
    the SOURCE, the composition-test precedent.
    """
    tree = ast.parse(_REGISTRY_PATH.read_text("utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "require_analysis_wire_families"
    ]
    assert calls, (
        "registry.py must execute require_analysis_wire_families at "
        "import: an unexecuted grammar is narration"
    )


def test_the_real_wire_population_passes_the_gate() -> None:
    """Witness that the instrument is on: 19 families, 94 fact fields.

    93 until the authority ``violations`` family gained ``locations``, the
    one published authority column measured NOT derivable from the stored
    subset and therefore canonicalized rather than projected. One family
    gained one wire column; no family was added or removed.
    """
    families = _wire_field_names()
    assert len(families) == 19
    assert sum(len(fields) for fields in families.values()) == 94
    require_analysis_wire_families(families)


# ---------------------------------------------------------------------------
# Vocabulary self-integrity: each refusal branch reachable by fixture.
# ---------------------------------------------------------------------------


def test_overlapping_marker_vocabularies_are_refused() -> None:
    with pytest.raises(GrammarViolation, match="claim two tiers"):
        require_closed_vocabularies(
            comparison_markers=frozenset({"novelty", "verdict"}),
            evaluation_markers=frozenset({"verdict"}),
        )


def test_annotation_kind_outside_the_productions_is_refused() -> None:
    with pytest.raises(GrammarViolation, match=r"not.*grammar productions"):
        require_closed_vocabularies(
            annotation_kinds=frozenset({"novelty_annotation", "vibes_annotation"}),
            subject_tiers={
                "novelty_annotation": frozenset({ANALYSIS_TIER}),
                "vibes_annotation": frozenset({ANALYSIS_TIER}),
            },
        )


def test_annotation_kind_without_a_subject_rule_is_refused() -> None:
    with pytest.raises(GrammarViolation, match="subject-tier rule"):
        require_closed_vocabularies(
            subject_tiers={"novelty_annotation": frozenset({ANALYSIS_TIER})}
        )


def test_annotation_subject_rule_never_admits_comparison() -> None:
    poisoned = {
        "novelty_annotation": frozenset({ANALYSIS_TIER, COMPARISON_TIER}),
        "delta_annotation": frozenset({ANALYSIS_TIER, EVALUATION_TIER}),
        "metric_baseline_result": frozenset({ANALYSIS_TIER}),
    }
    with pytest.raises(GrammarViolation, match="never annotate annotations"):
        require_closed_vocabularies(subject_tiers=poisoned)


# ---------------------------------------------------------------------------
# The landed §3 resident: grammar admitted it exactly as promised.
# ---------------------------------------------------------------------------


def test_analysis_population_is_a_landed_run_population_family() -> None:
    """RULING-2026-08-31 §3, landed: the execution-population singleton is
    a declared ``run_population`` production — analysis tier by
    derivation, admitted by the wire gate as part of the real registry
    (test_the_real_wire_population_passes_the_gate), and refused by
    every foreign house."""
    assert (
        FAMILY_SEMANTIC_GRAMMAR["analysis_population"].semantic_kind == "run_population"
    )
    assert tier_of_family("analysis_population") == ANALYSIS_TIER
    require_house_families(ANALYSIS_TIER, ("analysis_population",))
    with pytest.raises(GrammarViolation, match="analysis-tier"):
        require_house_families(COMPARISON_TIER, ("analysis_population",))
    with pytest.raises(GrammarViolation, match="analysis-tier"):
        require_house_families(EVALUATION_TIER, ("analysis_population",))
