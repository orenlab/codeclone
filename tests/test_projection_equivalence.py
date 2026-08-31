# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The projection-equivalence instrument, and the proof that it can say no.

Backend P0 step 4. Step 8 moves a consumer off the report document and onto
the canonical run store; this suite is what makes that a measurement instead
of a hope. Every property below is a mutation target: the instrument is only
worth its verdict if breaking the behaviour it pins turns one of these red.

Four things are pinned, in the order they can fail:

1. *Reachability.* Every lane has non-empty assertions on both sides. A lane
   that compares nothing would report ``equivalent`` forever -- the exact
   theatre this suite exists to prevent, and the exact bug the clone lane had
   while its container name was singular.
2. *Both boundaries.* A perturbed report and a perturbed model each turn
   their lane ``divergent``, and each reds a different test.
3. *Witness before count.* A family the run did not declare is
   ``unmeasured``, never ``equivalent``, even when both sides are byte for
   byte the same. All three witness owners -- the metric-family declaration,
   the sealed observation contract, and the presence of the declaration
   itself -- are proved separately. The witness is also a lane of its own:
   the run's declaration is compared against the stored
   ``AnalysisPopulation``, so a disagreement between what a run says it
   measured and what the store says it measured is a red assertion rather
   than an assumption nobody checks.
4. *What is not compared is named*, and is derived from the rows rather than
   declared, so a report that grows a key cannot quietly widen the claim.

The consumer inventory is mechanical: it comes from the repository's own
report-read chain reconstructor over the consumers' source text, never from
a grep and never from reading them by eye.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from codeclone.canonical import ADOPTION_FEATURES, RISK_DIMENSIONS

from ._projection_equivalence import (
    _ADOPTION_COLUMNS,
    _CLONE_CONTAINERS,
    LANES,
    VERDICT_DIVERGENT,
    VERDICT_EQUIVALENT,
    VERDICT_PARTIAL,
    VERDICT_UNMEASURED,
    WITNESS_DECLARED,
    WITNESS_WITHHELD,
    ProjectionCorpus,
    build_corpus,
    compare_projections,
    consumer_reads,
    declaration_witness,
    document_sections,
    family_items,
    family_witness,
    lane_placeholder_fields,
    lane_witness,
    stale_represented_fields,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: The lanes that carry the same assertions on both sides AND read nothing
#: the canonical model cannot answer. This is the migration frontier: a
#: consumer confined to these lanes can move to the store today.
_MIGRATABLE = (
    "analysis_population.states",
    "dependencies.relations",
    "dependencies.occurrences",
)

#: Measured, not assumed: the report's dead-code family is a classification
#: over the observation population, and the model carries the population.
_DEAD_CODE_LANE = "dead_code.candidates"


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> ProjectionCorpus:
    """One real pipeline run, published and read back, shared by the suite."""

    base = tmp_path_factory.mktemp("projection-equivalence")
    tree = base / "tree"
    tree.mkdir()
    return build_corpus(tree, store_path=base / "runs.sqlite3")


def test_the_store_round_trip_returns_the_ingested_model(
    corpus: ProjectionCorpus,
) -> None:
    assert corpus.stored_model == corpus.model
    assert corpus.run_id


def test_every_lane_is_reached_by_the_corpus(corpus: ProjectionCorpus) -> None:
    """No lane may be judged on an empty comparison.

    A lane whose two sides are both empty answers ``equivalent`` for any
    implementation whatsoever, so its verdict is evidence of nothing. This
    is the guard that caught the clone lane reading ``function`` out of a
    container the document names ``functions``.
    """

    report = compare_projections(corpus.document, corpus.stored_model)
    empty = {
        lane.lane: (lane.report_count, lane.model_count)
        for lane in report.lanes
        if not lane.report_count or not lane.model_count
    }
    assert not empty, f"lanes decided on an empty comparison: {empty}"


def test_lane_names_are_unique_and_cover_the_declared_specs(
    corpus: ProjectionCorpus,
) -> None:
    report = compare_projections(corpus.document, corpus.stored_model)
    names = [lane.lane for lane in report.lanes]
    assert names == [spec.name for spec in LANES]
    assert len(set(names)) == len(names)


def test_no_lane_is_unmeasured_on_a_full_run(corpus: ProjectionCorpus) -> None:
    """The corpus declares every family it populates, so nothing abstains."""

    report = compare_projections(corpus.document, corpus.stored_model)
    abstained = [
        lane.lane for lane in report.lanes if lane.verdict == VERDICT_UNMEASURED
    ]
    assert abstained == []
    assert {lane.witness for lane in report.lanes} == {WITNESS_DECLARED}


def test_the_migration_frontier_is_exactly_the_equivalent_lanes(
    corpus: ProjectionCorpus,
) -> None:
    """Which consumers can move today, stated as a number and not a feeling."""

    report = compare_projections(corpus.document, corpus.stored_model)
    assert report.migratable_lanes == _MIGRATABLE
    assert report.verdict == VERDICT_DIVERGENT
    for lane in report.lanes:
        if lane.lane in _MIGRATABLE:
            assert lane.verdict == VERDICT_EQUIVALENT
            assert lane.unrepresented_fields == ()


def test_a_partial_lane_is_never_migratable(corpus: ProjectionCorpus) -> None:
    """Matching on the compared subset is not permission to migrate.

    A lane that agrees on everything it compares but reads a field the model
    cannot answer is ``partial``. Calling that ``equivalent`` is how a
    consumer would be moved onto a store that silently drops what it needs.
    """

    report = compare_projections(corpus.document, corpus.stored_model)
    partial = [lane for lane in report.lanes if lane.verdict == VERDICT_PARTIAL]
    assert partial, "no partial lane in the corpus; the guard is inert"
    for lane in partial:
        assert lane.unrepresented_fields
        assert not lane.migratable
        assert lane.only_in_report == ()
        assert lane.only_in_model == ()


# -- both boundaries ------------------------------------------------------


def _perturbed_document(corpus: ProjectionCorpus) -> dict[str, Any]:
    """A copy whose first dependency row names a target nobody imported."""

    document = deepcopy(dict(corpus.document))
    rows = family_items(document, "dependencies")
    assert rows, "corpus lost its dependency rows; the perturbation is inert"
    metrics: Any = document["metrics"]
    items = metrics["families"]["dependencies"]["items"]
    items[0] = dict(items[0]) | {"target": "pkg.no_such_module"}
    return document


def test_a_report_row_the_model_does_not_carry_turns_the_lane_divergent(
    corpus: ProjectionCorpus,
) -> None:
    """First boundary: the mechanism must not call a difference equal."""

    report = compare_projections(_perturbed_document(corpus), corpus.stored_model)
    lane = report.lane("dependencies.relations")
    assert lane.verdict == VERDICT_DIVERGENT
    assert not lane.migratable
    assert any(
        "pkg.no_such_module" in assertion for assertion in lane.only_in_report
    ), lane.only_in_report
    assert lane.only_in_model, "the displaced row must be named on the model side"
    assert report.verdict == VERDICT_DIVERGENT


def test_a_model_row_the_report_does_not_carry_turns_the_lane_divergent(
    corpus: ProjectionCorpus,
) -> None:
    """Second boundary, mutated on the other side and pinned by another test.

    Dropping a relation from the model must be named as ``only_in_report``:
    the report still asserts it and the store no longer does.
    """

    facts = corpus.stored_model.facts
    relations = sorted(
        facts.analysis.dependency_relations,
        key=lambda row: (str(row.source), str(row.target), row.dependency_type),
    )
    assert relations, "corpus lost its relations; the perturbation is inert"
    thinned = corpus.stored_model.__class__(
        files=corpus.stored_model.files,
        modules=corpus.stored_model.modules,
        analyzed_files=corpus.stored_model.analyzed_files,
        file_modules=corpus.stored_model.file_modules,
        facts=facts.__class__(
            analysis=facts.analysis.__class__(
                **{
                    **{
                        name: getattr(facts.analysis, name)
                        for name in (
                            "contracts",
                            "graph_nodes",
                            "sink_roles",
                            "candidates",
                            "semantic_edges",
                            "dependency_occurrences",
                            "dependency_cycles",
                            "clone_groups",
                            "dead_code_observations",
                            "violations",
                            "coupling_cohesion_observations",
                            "api_symbols",
                            "risk_observations",
                            "adoption_counts",
                            "security_surfaces",
                            "run_scalars",
                        )
                    },
                    "dependency_relations": frozenset(relations[1:]),
                }
            ),
            comparison=facts.comparison,
            evaluation=facts.evaluation,
        ),
        coupled_sets=corpus.stored_model.coupled_sets,
    )
    report = compare_projections(corpus.document, thinned)
    lane = report.lane("dependencies.relations")
    assert lane.verdict == VERDICT_DIVERGENT
    assert lane.only_in_report, "the dropped relation must be named"
    assert lane.only_in_model == ()
    assert lane.model_count is not None
    assert lane.report_count == lane.model_count + 1


def test_an_untouched_lane_stays_equivalent_under_a_neighbours_perturbation(
    corpus: ProjectionCorpus,
) -> None:
    """A divergence must be attributed, not spread across the report."""

    report = compare_projections(_perturbed_document(corpus), corpus.stored_model)
    assert report.lane("security_surfaces.items").only_in_report == ()
    assert report.lane("clones.groups").only_in_model == ()


# -- witness before count -------------------------------------------------


def test_an_undeclared_metric_family_is_unmeasured_not_equivalent(
    corpus: ProjectionCorpus,
) -> None:
    """Byte-identical sides plus no declaration is a refusal, not a match.

    Nothing about the payload changes here: only the run's own statement
    that it measured the family is withdrawn. A mechanism that answers from
    the payload alone would still say ``equivalent``.
    """

    document = deepcopy(dict(corpus.document))
    meta: Any = document["meta"]
    meta["computed_metric_families"] = [
        name for name in meta["computed_metric_families"] if name != "dependencies"
    ]
    assert family_witness(document, "dependencies") == WITNESS_WITHHELD
    assert family_items(document, "dependencies") == family_items(
        corpus.document, "dependencies"
    )

    report = compare_projections(document, corpus.stored_model)
    for name in ("dependencies.relations", "dependencies.occurrences"):
        lane = report.lane(name)
        assert lane.verdict == VERDICT_UNMEASURED
        assert lane.witness == WITNESS_WITHHELD
        assert lane.report_count is None
        assert lane.model_count is None
        assert not lane.migratable
    assert report.lane("security_surfaces.items").witness == WITNESS_DECLARED
    assert report.migratable_lanes == ()


def test_a_withheld_observation_lane_is_unmeasured_not_equivalent(
    corpus: ProjectionCorpus,
) -> None:
    """The second witness owner, proved on its own.

    ``findings.groups.clones`` is not a metric family, so its declaration is
    the sealed observation contract. One witness passing does not prove the
    other is wired.
    """

    document = deepcopy(dict(corpus.document))
    source_facts: Any = document["source_facts"]
    contract = source_facts["observation_contract"]
    contract["enabled_lanes"] = [
        name for name in contract["enabled_lanes"] if name != "clones.functions"
    ]
    assert lane_witness(document, "clones.functions") == WITNESS_WITHHELD

    report = compare_projections(document, corpus.stored_model)
    clones = report.lane("clones.groups")
    assert clones.verdict == VERDICT_UNMEASURED
    assert clones.report_count is None
    assert report.lane("dependencies.relations").verdict == VERDICT_EQUIVALENT


def test_every_witness_owner_answers_for_the_run_that_did_measure(
    corpus: ProjectionCorpus,
) -> None:
    assert family_witness(corpus.document, "dependencies") == WITNESS_DECLARED
    assert family_witness(corpus.document, "no_such_family") == WITNESS_WITHHELD
    assert lane_witness(corpus.document, "clones.functions") == WITNESS_DECLARED
    assert lane_witness(corpus.document, "no_such_lane") == WITNESS_WITHHELD
    assert (
        declaration_witness(corpus.document, "computed_metric_families")
        == WITNESS_DECLARED
    )
    assert declaration_witness(corpus.document, "no_such_key") == WITNESS_WITHHELD


def _document_declaring_nothing(corpus: ProjectionCorpus) -> dict[str, Any]:
    """A run that honestly declares it computed nothing.

    Present-and-empty, not absent: an absent key means a legacy document
    that never declared, and its own door law keeps every family. Empty is
    the run stating it measured none of them while the container still
    carries the zeros it always carries.
    """

    document = deepcopy(dict(corpus.document))
    meta: Any = document["meta"]
    meta["computed_metric_families"] = []
    return document


def test_an_unmeasured_lane_is_never_equivalent(corpus: ProjectionCorpus) -> None:
    """The refusal itself, pinned as an assertion rather than a crash.

    Turning ``unmeasured`` into ``equivalent`` used to be caught only by the
    arithmetic downstream blowing up on ``None`` counts -- a defence, but a
    blunt one: an error is not a statement about what went wrong. This
    asserts the verdict FIRST, so the class dies red and says why.
    """

    report = compare_projections(
        _document_declaring_nothing(corpus), corpus.stored_model
    )
    unmeasured = [lane for lane in report.lanes if lane.witness == WITNESS_WITHHELD]
    assert unmeasured, "no lane lost its witness; the guard is inert"
    for lane in unmeasured:
        assert lane.verdict == VERDICT_UNMEASURED, lane
        assert lane.verdict != VERDICT_EQUIVALENT
        assert not lane.migratable
        assert lane.report_count is None
        assert lane.model_count is None
    assert report.migratable_lanes == ()
    assert report.verdict != VERDICT_EQUIVALENT


def test_the_population_lane_compares_the_witness_instead_of_trusting_it(
    corpus: ProjectionCorpus,
) -> None:
    """A run whose declaration disagrees with the stored population reds.

    The document says it computed nothing; the model published from the
    untouched run says every family is ``complete``. Before the tier grammar
    landed ``AnalysisPopulation`` the model could not answer at all and this
    instrument could only read the report side.
    """

    report = compare_projections(
        _document_declaring_nothing(corpus), corpus.stored_model
    )
    lane = report.lane("analysis_population.states")
    assert lane.witness == WITNESS_DECLARED
    assert lane.verdict == VERDICT_DIVERGENT
    assert any(
        assertion[:1] == ("producer_state",) and assertion[2] == "not_executed"
        for assertion in lane.only_in_report
    ), lane.only_in_report
    assert any(
        assertion[:1] == ("producer_state",) and assertion[2] == "complete"
        for assertion in lane.only_in_model
    ), lane.only_in_model


def test_the_population_lane_agrees_on_mode_and_profile(
    corpus: ProjectionCorpus,
) -> None:
    """The corpus carries what the live product carries, or this reds.

    ``meta.analysis_profile`` is the key whose absence made the whole suite
    error after the tier grammar landed its population oracle: a corpus that
    hand-writes the subset a consumer happens to read stops being
    representative the moment somebody reads one more key.
    """

    lane = compare_projections(corpus.document, corpus.stored_model).lane(
        "analysis_population.states"
    )
    assert lane.verdict == VERDICT_EQUIVALENT
    population = corpus.stored_model.facts.analysis.analysis_population
    assert population is not None
    assert population.analysis_mode == "full"
    assert dict(population.analysis_profile) == {
        "min_loc": 6,
        "min_stmt": 4,
        "block_min_loc": 20,
        "block_min_stmt": 8,
        "segment_min_loc": 20,
        "segment_min_stmt": 10,
    }
    assert {state for _family, state in population.producer_states} == {"complete"}


def test_the_declaration_witness_separates_absence_from_emptiness(
    corpus: ProjectionCorpus,
) -> None:
    """The third owner, proved on its own and on both of its states."""

    key = "computed_metric_families"
    assert declaration_witness(corpus.document, key) == WITNESS_DECLARED
    assert declaration_witness(_document_declaring_nothing(corpus), key) == (
        WITNESS_DECLARED
    )
    absent = deepcopy(dict(corpus.document))
    meta: Any = absent["meta"]
    del meta[key]
    assert declaration_witness(absent, key) == WITNESS_WITHHELD
    lane = compare_projections(absent, corpus.stored_model).lane(
        "analysis_population.states"
    )
    assert lane.verdict == VERDICT_UNMEASURED
    assert lane.report_count is None


# -- what is not compared -------------------------------------------------


def test_unrepresented_fields_are_derived_from_the_rows(
    corpus: ProjectionCorpus,
) -> None:
    """The gap list is computed from this run's rows, not written down.

    A hand-written list of what the model cannot answer rots the day the
    report grows a key. Deriving it as ``row keys - represented`` makes a
    new key unrepresented by default, and makes an invented representation
    claim visible as a stale entry.
    """

    report = compare_projections(corpus.document, corpus.stored_model)
    for spec in LANES:
        stale = stale_represented_fields(spec, corpus.document)
        assert stale == (), f"{spec.name} claims to represent absent keys: {stale}"
        lane = report.lane(spec.name)
        placeholders = lane_placeholder_fields(spec, corpus.document)
        overlap = set(lane.unrepresented_fields) & set(spec.represented_fields)
        assert overlap == set(), f"{spec.name}: {overlap}"
        assert set(lane.unrepresented_fields) & set(placeholders) == set()

    complexity = report.lane("complexity.cyclomatic")
    assert "risk" in complexity.unrepresented_fields
    assert "cfg_cyclomatic_complexity" in complexity.unrepresented_fields
    clones = report.lane("clones.groups")
    for annotation in ("novelty", "novelty_reason", "severity", "priority"):
        assert annotation in clones.unrepresented_fields


def test_the_union_shaped_authority_container_does_not_read_as_a_gap(
    corpus: ProjectionCorpus,
) -> None:
    """A sink row carries ``candidate_id: ""``; that is not a missing fact.

    The authority family is one union of four item kinds. Counting a kind's
    empty placeholder columns as things the model failed to carry would tell
    step 8 that a migratable lane cannot migrate.
    """

    spec = next(item for item in LANES if item.name == "authority.sinks")
    placeholders = lane_placeholder_fields(spec, corpus.document)
    assert "candidate_id" in placeholders
    assert "level" in placeholders
    report = compare_projections(corpus.document, corpus.stored_model)
    assert "candidate_id" not in report.lane("authority.sinks").unrepresented_fields


def test_the_class_b_authority_handles_survive_the_store(
    corpus: ProjectionCorpus,
) -> None:
    """Candidate and violation ids recompute out of the normalized model.

    The report carries the ids as strings the producer emitted; the model
    carries no id at all and the canonical side rebuilds them from
    ``(level, shared_fact, producers)`` through ``file_modules``. Agreement
    here is the proof that the store kept enough to speak the public
    identity -- the one that settles in review receipts.
    """

    report = compare_projections(corpus.document, corpus.stored_model)
    for name in ("authority.candidates", "authority.violations"):
        lane = report.lane(name)
        assert lane.only_in_report == ()
        assert lane.only_in_model == ()
        assert lane.model_count is not None
        assert lane.report_count == lane.model_count > 0


# -- the measured "no" ----------------------------------------------------


def test_dead_code_classification_does_not_survive_the_projection(
    corpus: ProjectionCorpus,
) -> None:
    """The load-bearing negative verdict, on live producer output.

    ``metrics.families.dead_code.items`` is not a projection of a model
    family: it is a classification over one. The model carries the whole
    candidate population and none of the classification, so the report's
    entity set is strictly smaller and the lane is ``divergent`` with no
    perturbation at all.
    """

    report = compare_projections(corpus.document, corpus.stored_model)
    lane = report.lane(_DEAD_CODE_LANE)
    assert lane.verdict == VERDICT_DIVERGENT
    assert lane.only_in_report == ()
    assert lane.only_in_model, "the population/classification gap vanished"
    assert lane.model_count is not None
    assert lane.report_count is not None
    assert lane.model_count > lane.report_count > 0
    assert "confidence" in lane.unrepresented_fields
    assert "reason" in lane.unrepresented_fields


def test_the_budget_dead_code_count_cannot_be_rebuilt_from_the_model(
    corpus: ProjectionCorpus,
) -> None:
    """``check_patch_contract(mode="budget")`` would get a different number.

    The consumer counts report items whose ``confidence`` is ``high``. The
    model carries no confidence, so the nearest reconstruction is
    ``reference_count == 0``. The two numbers disagree on this corpus, which
    is what makes the gap a migration blocker rather than a cosmetic one.
    """

    high_confidence = sum(
        1
        for row in family_items(corpus.document, "dead_code")
        if str(row.get("confidence", "")).strip().lower() == "high"
    )
    unreferenced = sum(
        1
        for row in corpus.stored_model.facts.analysis.dead_code_observations
        if row.reference_count == 0
    )
    assert high_confidence > 0
    assert unreferenced != high_confidence, (
        "the model's nearest reconstruction now matches the consumer's count; "
        "re-measure before calling this gap closed"
    )


# -- vocabulary and container names ---------------------------------------


def test_adoption_columns_bind_the_ratified_feature_vocabulary() -> None:
    """The lane's column binding is the domain's vocabulary, not a guess."""

    assert tuple(feature for feature, _n, _d in _ADOPTION_COLUMNS) == tuple(
        sorted(ADOPTION_FEATURES)
    )


def test_risk_lane_compares_every_dimension_the_model_carries(
    corpus: ProjectionCorpus,
) -> None:
    """Comparing one dimension and calling the rest a gap understates it."""

    dimensions = {
        row.dimension for row in corpus.stored_model.facts.analysis.risk_observations
    }
    assert dimensions == set(RISK_DIMENSIONS)
    lane = compare_projections(corpus.document, corpus.stored_model).lane(
        "complexity.cyclomatic"
    )
    assert set(RISK_DIMENSIONS).isdisjoint(lane.unrepresented_fields)


def test_clone_containers_are_the_plural_names_the_document_carries(
    corpus: ProjectionCorpus,
) -> None:
    """The singular name reads nothing, and nothing reads as an empty family.

    This pins the shape of the bug the reachability guard caught: a reader
    addressing ``clones.function`` finds no rows and its lane reports a
    perfect match with an empty model side.
    """

    groups: Any = corpus.document["findings"]
    clones = groups["groups"]["clones"]
    assert set(clones) == {container for container, _kind in _CLONE_CONTAINERS}
    assert any(clones[container] for container, _kind in _CLONE_CONTAINERS)
    for _container, kind in _CLONE_CONTAINERS:
        assert kind not in clones


# -- consumer inventory ---------------------------------------------------

#: Every candidate consumer of the migration, and the report-document key
#: paths it reads, reconstructed from its own source by the repository's own
#: chain scanner. Two-sided: a consumer that starts or stops reading a path
#: turns this red rather than drifting.
_CONSUMER_PATHS: dict[str, tuple[str, ...]] = {
    "codeclone/surfaces/mcp/_authority_candidates.py": (
        "metrics",
        "metrics.families",
        "metrics.families.semantic_authority",
        "metrics.families.semantic_authority.items",
    ),
    "codeclone/surfaces/mcp/_session_patch_contract_mixin.py": (
        "metrics",
        "metrics.families",
        "metrics.families.dependencies",
        "metrics.families.dependencies.cycles",
    ),
    "codeclone/analysis/blast_radius.py": (
        "findings",
        "findings.groups",
        "findings.groups.clones",
        "inventory",
        "inventory.file_registry",
        "inventory.file_registry.items",
        "metrics",
        "metrics.families",
        "metrics.families.complexity",
        "metrics.families.complexity.items",
        "metrics.families.coupling",
        "metrics.families.coupling.items",
        "metrics.families.coverage_join",
        "metrics.families.coverage_join.items",
        "metrics.families.dependencies",
        "metrics.families.dependencies.cycles",
        "metrics.families.dependencies.dynamic_boundaries",
        "metrics.families.dependencies.items",
        "metrics.families.overloaded_modules",
        "metrics.families.overloaded_modules.items",
    ),
    "codeclone/surfaces/mcp/_implementation_context.py": (
        "metrics",
        "metrics.families",
        "metrics.families.api_surface",
        "metrics.families.api_surface.items",
        "metrics.families.dependencies",
        "metrics.families.dependencies.dynamic_boundaries",
        "metrics.families.dependencies.items",
    ),
    "codeclone/surfaces/cli/patch_verify.py": (
        "evaluation",
        "evaluation.outcome",
        "evaluation.outcome.exit_code",
        "evaluation.outcome.reasons",
    ),
}

#: Metric families addressed by a constant ``family=`` argument. The chain
#: scanner cannot see these -- the key is a parameter -- so an inventory
#: built from paths alone would report that the budget consumer reads no
#: metric family at all.
_CONSUMER_FAMILY_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "codeclone/surfaces/mcp/_authority_candidates.py": (),
    "codeclone/surfaces/mcp/_session_patch_contract_mixin.py": (
        "cohesion",
        "complexity",
        "coupling",
        "dead_code",
    ),
    "codeclone/analysis/blast_radius.py": (),
    "codeclone/surfaces/mcp/_implementation_context.py": (),
    "codeclone/surfaces/cli/patch_verify.py": (),
}


@pytest.mark.parametrize("module", sorted(_CONSUMER_PATHS))
def test_consumer_report_reads_are_the_inventoried_ones(
    module: str, corpus: ProjectionCorpus
) -> None:
    reads = consumer_reads(
        module=module,
        source=(_REPO_ROOT / module).read_text("utf-8"),
        sections=document_sections(corpus.document),
    )
    assert reads.paths == _CONSUMER_PATHS[module]
    assert reads.family_arguments == _CONSUMER_FAMILY_ARGUMENTS[module]


def test_the_inventory_filter_drops_reads_that_are_not_document_reads(
    corpus: ProjectionCorpus,
) -> None:
    """The scanner anchors on a name; a local mapping shares that name.

    ``_authority_candidates`` builds a cursor ``payload`` and reads
    ``offset`` and ``ordering_version`` out of it. Those are not report
    reads, and the section filter -- measured off a real document, never
    listed by hand -- removes them without anyone judging a variable name.
    """

    source = (_REPO_ROOT / "codeclone/surfaces/mcp/_authority_candidates.py").read_text(
        "utf-8"
    )
    sections = document_sections(corpus.document)
    unfiltered = consumer_reads(
        module="probe", source=source, sections=sections | {"offset"}
    )
    filtered = consumer_reads(module="probe", source=source, sections=sections)
    assert "offset" in unfiltered.paths
    assert "offset" not in filtered.paths
    assert "metrics.families.semantic_authority.items" in filtered.paths


def test_the_budget_consumer_reads_families_no_path_scan_can_see(
    corpus: ProjectionCorpus,
) -> None:
    """Named separately because it is the inventory's measured blind spot."""

    module = "codeclone/surfaces/mcp/_session_patch_contract_mixin.py"
    reads = consumer_reads(
        module=module,
        source=(_REPO_ROOT / module).read_text("utf-8"),
        sections=document_sections(corpus.document),
    )
    assert not any(
        path.startswith("metrics.families.complexity") for path in reads.paths
    )
    assert "complexity" in reads.family_arguments
    assert "dead_code" in reads.family_arguments
