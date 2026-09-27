# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The producer-native comparison facts (canonical epoch E2, 2026-09-26).

``core.reporting.report`` is the one scope in which the run's comparison
inputs are all alive at once — the baseline container and its trust vector,
the clone difference sets, the metric comparison and its availability
flags.  It hands them here as :class:`ComparisonInputs`, spelled by the SAME
owners the report document is built from (the document's comparison
section, its meta block, its enriched metric families, its novelty facts),
and this module turns them into the comparison house of the published run.

The novelty of a finding is decided by the document's own novelty owners
(``report.document._common``) over the finding ids the analysis families
project through their one id owner (``canonical.finding_projection``) — so
the store's novelty rows and the document's finding groups are two readings
of one decision, never two decisions.  The ingest oracle
(``canonical.comparison_ingest``) reads the same facts back out of the
serialized document; the equivalence pins hold the two apart.

Nothing here reaches the wire: the comparison house is model and store state
until its own wire-revision bump.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, NamedTuple

from ..canonical.codec import legacy_symbol_keys
from ..canonical.comparison_rows import (
    AVAILABILITY_COMPARED,
    CLONE_NOVELTY_LANES,
    COMPARED_LANES,
    COMPARISON_LANE_FAMILIES,
    DELTA_FAMILY_TERMS,
    LANE_TRUSTED,
    NOVELTY_FAMILY_ID_PREFIXES,
    BaselineWitnessRecord,
    ComparisonAvailabilityRow,
    DisabledCapabilityRow,
    FindingNoveltyRow,
    LaneTrustRow,
    MetricDeltaRow,
    MetricsBaselineWitnessRecord,
    baseline_statuses_stated,
    comparison_availability_state,
)
from ..canonical.finding_projection import (
    complexity_hotspot_skeletons,
    coupling_hotspot_skeletons,
    dead_symbol_group_skeletons,
    dependency_cycle_skeletons,
)
from ..canonical.identity import SymbolId
from ..canonical.model import AnalysisFacts, ComparisonFacts, FileModuleRelation
from ..findings.ids import clone_group_id
from ..report.document._common import (
    ENTITY_NOVELTY_DOMAIN_COMPLEXITY,
    ENTITY_NOVELTY_DOMAIN_COUPLING,
    ENTITY_NOVELTY_DOMAIN_DEAD_CODE,
    ENTITY_NOVELTY_DOMAIN_DEPENDENCIES,
    clone_novelty,
    entity_novelty,
    lane_is_trusted,
)
from ..utils.coerce import as_int, as_mapping, as_sequence

if TYPE_CHECKING:
    from ..models import TrustVector


class ComparisonInputs(NamedTuple):
    """What this run's baseline comparison produced, as the document's own
    owners spell it.

    ``section`` is the document's comparison section
    (``report.document.builder.baseline_projection``), ``meta`` its meta
    block (``report.document.inventory.meta_payload``), ``metrics`` the
    enriched metric families (``core.reporting._metrics_for_report``;
    ``None`` when the metrics never ran), ``entity_novelty_facts`` the
    per-entity differences (``report.document._common.entity_novelty_facts``).
    ``new_func`` / ``new_block`` are ``None`` for a clone lane that was not
    compared, a set for one that was.  A named tuple rather than a
    dataclass: runtime model shapes belong to the model store, and this is
    a producer-side carrier that lives for one publication.
    """

    section: Mapping[str, object]
    meta: Mapping[str, object]
    metrics: Mapping[str, object] | None
    trust: TrustVector | None
    new_func: frozenset[str] | None
    new_block: frozenset[str] | None
    entity_novelty_facts: Mapping[str, object]


#: The publisher evaluates the inputs inside its own containment, so a
#: comparison that cannot be spelled never takes the analysis down.
ComparisonInputsFactory = Callable[[], ComparisonInputs]

#: The document's summary key for each delta term, per delta family.
_SUMMARY_DELTA_KEYS: Mapping[str, Mapping[str, str]] = {
    "adoption_delta": {
        "docstring_permille_delta": "docstring_delta",
        "typing_param_permille_delta": "param_delta",
        "typing_return_permille_delta": "return_delta",
    },
    "api_surface_delta": {
        "api_breaking_changes": "breaking",
        "api_signature_changes": "changed",
        "new_api_symbols": "added",
    },
}
_DELTA_FAMILY_LANES: Mapping[str, str] = {
    "adoption_delta": "adoption_counts",
    "api_surface_delta": "api_surface",
}

_Identity = dict[str, "str | None"]


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _identity(section: Mapping[str, object]) -> _Identity:
    return {
        "baseline_scope_id": _optional_text(section.get("baseline_scope_id")),
        "root_digest": _optional_text(section.get("root_digest_or_null")),
    }


def _witnesses(
    inputs: ComparisonInputs, identity: _Identity
) -> tuple[BaselineWitnessRecord, MetricsBaselineWitnessRecord]:
    baseline = as_mapping(inputs.meta.get("baseline"))
    metrics = as_mapping(inputs.meta.get("metrics_baseline"))
    witness = BaselineWitnessRecord(
        **identity,
        state=str(inputs.section.get("state", "")),
        loaded=bool(baseline.get("loaded")),
        status=str(baseline.get("status", "")),
        fingerprint_version=_optional_text(baseline.get("fingerprint_version")),
        schema_version=_optional_text(baseline.get("schema_version")),
        python_tag=_optional_text(baseline.get("python_tag")),
        payload_sha256=_optional_text(baseline.get("payload_sha256")),
    )
    metrics_witness = MetricsBaselineWitnessRecord(
        **identity,
        loaded=bool(metrics.get("loaded")),
        status=str(metrics.get("status", "")),
        schema_version=_optional_text(metrics.get("schema_version")),
        payload_sha256=_optional_text(metrics.get("payload_sha256")),
    )
    return witness, metrics_witness


def _metric_summary(inputs: ComparisonInputs, lane: str) -> Mapping[str, object]:
    family = as_mapping(as_mapping(inputs.metrics).get(COMPARISON_LANE_FAMILIES[lane]))
    return as_mapping(family.get("summary"))


def _compared(inputs: ComparisonInputs, lane: str, *, lane_trusted: bool) -> bool:
    """Whether this lane's comparison ran.

    A clone lane is read the way the document's novelty owner reads it: a
    difference set under an UNTRUSTED lane is not a comparison.  That guard
    is load-bearing, not cautious — measured 2026-09-26, the CLI hands
    ``report`` its flattened sets (``set(comparison.new_func or ())``), so a
    lane nothing compared arrives as "compared, nothing new"; the document
    stays honest only because ``clone_novelty`` checks trust first, and the
    store has to read it the same way.
    """
    if lane == "clones.functions":
        return lane_trusted and inputs.new_func is not None
    if lane == "clones.blocks":
        return lane_trusted and inputs.new_block is not None
    return bool(_metric_summary(inputs, lane).get("baseline_diff_available"))


def _availability(
    inputs: ComparisonInputs,
    identity: _Identity,
    *,
    trusted: set[str],
    disabled: set[str],
) -> frozenset[ComparisonAvailabilityRow]:
    return frozenset(
        ComparisonAvailabilityRow(
            **identity,
            lane=lane,
            availability=comparison_availability_state(
                compared=_compared(inputs, lane, lane_trusted=lane in trusted),
                lane_trusted=lane in trusted,
            ),
        )
        for lane in COMPARED_LANES
        if lane not in disabled
    )


def _suffix(finding_id: str, family: str) -> str:
    prefix = next(
        prefix
        for prefix in NOVELTY_FAMILY_ID_PREFIXES[family]
        if finding_id.startswith(prefix)
    )
    return finding_id[len(prefix) :]


def _clone_novelty_rows(
    inputs: ComparisonInputs, facts: AnalysisFacts, identity: _Identity
) -> frozenset[FindingNoveltyRow]:
    """Function and block clone groups only: a segment group's novelty is its
    family's constant, never a comparison result."""
    rows: set[FindingNoveltyRow] = set()
    new_keys = {"clones.functions": inputs.new_func, "clones.blocks": inputs.new_block}
    for group in facts.clone_groups:
        finding_id = clone_group_id(group.clone_kind, group.group_key)
        lane = next(
            (
                lane
                for prefix, lane in CLONE_NOVELTY_LANES.items()
                if finding_id.startswith(prefix)
            ),
            None,
        )
        if lane is None:
            continue
        novelty, reason = clone_novelty(
            group_key=group.group_key,
            lane_trusted=lane_is_trusted(inputs.trust, lane),
            new_keys=new_keys[lane],
        )
        rows.add(
            FindingNoveltyRow(
                **identity,
                finding_id=finding_id,
                novelty=novelty,
                novelty_reason=reason,
            )
        )
    return frozenset(rows)


def _entity_novelty_rows(
    inputs: ComparisonInputs,
    family: str,
    domain: str,
    finding_ids: Iterable[str],
    identity: _Identity,
) -> frozenset[FindingNoveltyRow]:
    rows: set[FindingNoveltyRow] = set()
    for finding_id in finding_ids:
        novelty, reason = entity_novelty(
            identity=_suffix(finding_id, family),
            domain=domain,
            entity_novelty_facts=inputs.entity_novelty_facts,
        )
        rows.add(
            FindingNoveltyRow(
                **identity,
                finding_id=finding_id,
                novelty=novelty,
                novelty_reason=reason,
            )
        )
    return frozenset(rows)


def _governed_finding_ids(
    facts: AnalysisFacts, file_modules: frozenset[FileModuleRelation]
) -> dict[str, list[str]]:
    """The published ids of the four governed entity families, through the
    one id owner the finding projection uses."""
    symbols: set[SymbolId] = {row.symbol for row in facts.dead_symbol_groups}
    symbols.update(row.symbol for row in facts.complexity_hotspots)
    symbols.update(row.symbol for row in facts.coupling_hotspots)
    legacy = legacy_symbol_keys(symbols, file_modules)
    file_of_module = {relation.module: relation.file for relation in file_modules}
    return {
        "complexity_novelty": [
            str(group["id"])
            for group in complexity_hotspot_skeletons(facts.complexity_hotspots, legacy)
        ],
        "coupling_novelty": [
            str(group["id"])
            for group in coupling_hotspot_skeletons(facts.coupling_hotspots, legacy)
        ],
        "dead_symbol_novelty": [
            str(group["id"])
            for group in dead_symbol_group_skeletons(facts.dead_symbol_groups, legacy)
        ],
        "dependency_cycle_novelty": [
            str(group["id"])
            for group in dependency_cycle_skeletons(
                facts.dependency_cycles, file_of_module
            )
        ],
    }


_ENTITY_DOMAINS: Mapping[str, str] = {
    "complexity_novelty": ENTITY_NOVELTY_DOMAIN_COMPLEXITY,
    "coupling_novelty": ENTITY_NOVELTY_DOMAIN_COUPLING,
    "dead_symbol_novelty": ENTITY_NOVELTY_DOMAIN_DEAD_CODE,
    "dependency_cycle_novelty": ENTITY_NOVELTY_DOMAIN_DEPENDENCIES,
}


def _deltas(
    inputs: ComparisonInputs,
    identity: _Identity,
    availability: frozenset[ComparisonAvailabilityRow],
) -> dict[str, frozenset[MetricDeltaRow]]:
    compared = {
        row.lane for row in availability if row.availability == AVAILABILITY_COMPARED
    }
    deltas: dict[str, frozenset[MetricDeltaRow]] = {}
    for family, lane in _DELTA_FAMILY_LANES.items():
        summary = _metric_summary(inputs, lane)
        keys = _SUMMARY_DELTA_KEYS[family]
        deltas[family] = (
            frozenset(
                MetricDeltaRow(
                    **identity, delta=term, value=as_int(summary.get(keys[term]))
                )
                for term in DELTA_FAMILY_TERMS[family]
            )
            if lane in compared
            else frozenset()
        )
    return deltas


def comparison_facts_from_producers(
    inputs: ComparisonInputs,
    facts: AnalysisFacts,
    file_modules: frozenset[FileModuleRelation],
) -> ComparisonFacts:
    """The comparison house of one run, straight off its comparison inputs
    and the analysis families the same run publishes.

    A run whose meta states no baseline status for either baseline (a caller
    that handed ``report`` an empty meta) witnessed no comparison, and the
    answer is the empty house — the rule the ingest oracle reads a document
    by (``baseline_statuses_stated``)."""
    if not baseline_statuses_stated(inputs.meta):
        return ComparisonFacts()
    identity = _identity(inputs.section)
    witness, metrics_witness = _witnesses(inputs, identity)
    lane_trust = frozenset(
        LaneTrustRow(
            **identity,
            lane=str(row.get("name", "")),
            status=str(row.get("status", "")),
            reason=str(row.get("reason", "")),
        )
        for row in (
            as_mapping(item)
            for item in as_sequence(inputs.section.get("sorted_lane_trust"))
        )
    )
    disabled = {
        str(lane) for lane in as_sequence(inputs.section.get("disabled_capabilities"))
    }
    availability = _availability(
        inputs,
        identity,
        trusted={row.lane for row in lane_trust if row.status == LANE_TRUSTED},
        disabled=disabled,
    )
    finding_ids = _governed_finding_ids(facts, file_modules)
    entity = {
        family: _entity_novelty_rows(
            inputs, family, _ENTITY_DOMAINS[family], ids, identity
        )
        for family, ids in finding_ids.items()
    }
    deltas = _deltas(inputs, identity, availability)
    return ComparisonFacts(
        baseline_witness=witness,
        metrics_baseline_witness=metrics_witness,
        lane_trust=lane_trust,
        comparison_availability=availability,
        disabled_capabilities=frozenset(
            DisabledCapabilityRow(**identity, lane=lane) for lane in disabled
        ),
        clone_novelty=_clone_novelty_rows(inputs, facts, identity),
        complexity_novelty=entity["complexity_novelty"],
        coupling_novelty=entity["coupling_novelty"],
        dependency_cycle_novelty=entity["dependency_cycle_novelty"],
        dead_symbol_novelty=entity["dead_symbol_novelty"],
        adoption_delta=deltas["adoption_delta"],
        api_surface_delta=deltas["api_surface_delta"],
    )


def comparison_house(
    comparison: ComparisonInputsFactory | None,
    facts: AnalysisFacts,
    file_modules: frozenset[FileModuleRelation],
) -> ComparisonFacts:
    """The comparison house the publisher stores: the run's comparison when
    it was handed one — evaluated here, inside the publication's
    containment — and the unwitnessed empty house when it was not."""
    if comparison is None:
        return ComparisonFacts()
    return comparison_facts_from_producers(comparison(), facts, file_modules)


__all__ = [
    "ComparisonInputs",
    "ComparisonInputsFactory",
    "comparison_facts_from_producers",
    "comparison_house",
]
