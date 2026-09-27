# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The comparison half of the ingest oracle (canonical epoch E2, 2026-09-26).

The report document already publishes this run's comparison: the top-level
``baseline`` section (``state``, the container identity, per-lane trust,
disabled capabilities), the ``meta.baseline`` / ``meta.metrics_baseline``
blocks, the ``novelty`` / ``novelty_reason`` of every finding group, and the
``baseline_diff_available`` summaries of the metric families.  This module
reads each family from the container the document builder writes it to —
the oracle side of the shadow; the producer-native snapshot
(``core.comparison_snapshot``) is the other side, built by the same owners.

A document that carries no ``baseline`` section never witnessed a
comparison, and the answer is the EMPTY house — "not witnessed by this
artifact" — never a fabricated ``missing`` witness.  A section that is
present is read whole; a malformed member is a typed refusal.

The document cannot express one absence: a trusted clone lane that was not
compared is visible only through the ``comparison_unavailable`` reason of
its groups, so a lane with no groups reads as compared.  The comparison
door compares every trusted clone lane, so the case is unreachable through
it; the producer-native snapshot states it exactly, and the equivalence pin
would red on a population that reached it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import cast

from codeclone.canonical.comparison_rows import (
    CLONE_KIND_LANES,
    COMPARED_LANES,
    COMPARISON_LANE_FAMILIES,
    DELTA_FAMILY_TERMS,
    LANE_TRUSTED,
    NOVELTY_REASON_COMPARISON_UNAVAILABLE,
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
from codeclone.canonical.errors import LegacyIngestError
from codeclone.canonical.model import ComparisonFacts

#: The document summary key that spells each delta term, per delta family.
_DOCUMENT_DELTA_KEYS: dict[str, dict[str, str]] = {
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
#: The lane whose comparison states each delta family.
_DELTA_FAMILY_LANES: dict[str, str] = {
    "adoption_delta": "adoption_counts",
    "api_surface_delta": "api_surface",
}
#: The governed design categories and the novelty family each one feeds.
_DESIGN_NOVELTY_FAMILIES: dict[str, str] = {
    "complexity": "complexity_novelty",
    "coupling": "coupling_novelty",
    "dependency": "dependency_cycle_novelty",
}
_DEAD_SYMBOL_KIND = "unused_symbol"

_Identity = dict[str, "str | None"]


def _mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise LegacyIngestError(f"{where} is not an object")
    return cast("Mapping[str, object]", value)


def _sequence(value: object, where: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LegacyIngestError(f"{where} is not an array")
    return value


def _field(container: Mapping[str, object], key: str, where: str) -> object:
    if key not in container:
        raise LegacyIngestError(f"{where} is missing {key!r}")
    return container[key]


def _text(container: Mapping[str, object], key: str, where: str) -> str:
    value = _field(container, key, where)
    if not isinstance(value, str):
        raise LegacyIngestError(f"{where}.{key} is not a string")
    return value


def _optional_text(container: Mapping[str, object], key: str, where: str) -> str | None:
    value = _field(container, key, where)
    if value is not None and not isinstance(value, str):
        raise LegacyIngestError(f"{where}.{key} is neither a string nor null")
    return value


def _flag(container: Mapping[str, object], key: str, where: str) -> bool:
    value = _field(container, key, where)
    if not isinstance(value, bool):
        raise LegacyIngestError(f"{where}.{key} is not a boolean")
    return value


def _number(container: Mapping[str, object], key: str, where: str) -> int:
    value = _field(container, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LegacyIngestError(f"{where}.{key} is not an int")
    return value


def _rows(
    container: Mapping[str, object], key: str, where: str
) -> list[Mapping[str, object]]:
    return [
        _mapping(row, f"{where}.{key}[]")
        for row in _sequence(_field(container, key, where), f"{where}.{key}")
    ]


def _witness(
    section: Mapping[str, object], meta: Mapping[str, object], identity: _Identity
) -> tuple[BaselineWitnessRecord, MetricsBaselineWitnessRecord]:
    baseline = _mapping(_field(meta, "baseline", "meta"), "meta.baseline")
    metrics = _mapping(
        _field(meta, "metrics_baseline", "meta"), "meta.metrics_baseline"
    )
    where, metrics_where = "meta.baseline", "meta.metrics_baseline"
    witness = BaselineWitnessRecord(
        **identity,
        state=_text(section, "state", "baseline"),
        loaded=_flag(baseline, "loaded", where),
        status=_text(baseline, "status", where),
        fingerprint_version=_optional_text(baseline, "fingerprint_version", where),
        schema_version=_optional_text(baseline, "schema_version", where),
        python_tag=_optional_text(baseline, "python_tag", where),
        payload_sha256=_optional_text(baseline, "payload_sha256", where),
    )
    metrics_witness = MetricsBaselineWitnessRecord(
        **identity,
        loaded=_flag(metrics, "loaded", metrics_where),
        status=_text(metrics, "status", metrics_where),
        schema_version=_optional_text(metrics, "schema_version", metrics_where),
        payload_sha256=_optional_text(metrics, "payload_sha256", metrics_where),
    )
    return witness, metrics_witness


def _clone_groups(
    document: Mapping[str, object],
) -> dict[str, list[Mapping[str, object]]]:
    findings = _mapping(_field(document, "findings", "document"), "findings")
    groups = _mapping(_field(findings, "groups", "findings"), "findings.groups")
    clones = _mapping(_field(groups, "clones", "findings.groups"), "clones")
    return {
        kind: _rows(clones, f"{kind}s", "findings.groups.clones")
        for kind in CLONE_KIND_LANES
    }


def _group_rows(
    document: Mapping[str, object], family: str
) -> list[Mapping[str, object]]:
    findings = _mapping(_field(document, "findings", "document"), "findings")
    groups = _mapping(_field(findings, "groups", "findings"), "findings.groups")
    container = _mapping(
        _field(groups, family, "findings.groups"), f"findings.groups.{family}"
    )
    return _rows(container, "groups", f"findings.groups.{family}")


def _metric_summary(
    document: Mapping[str, object], family: str
) -> Mapping[str, object]:
    """One metric family's summary, or the empty mapping when the document
    carries no such family (a clones-only run carries none)."""
    metrics = document.get("metrics")
    if not isinstance(metrics, Mapping):
        return {}
    families = metrics.get("families")
    if not isinstance(families, Mapping):
        return {}
    container = families.get(family)
    if not isinstance(container, Mapping):
        return {}
    return _mapping(container.get("summary", {}), f"metrics.families.{family}.summary")


def _metric_compared(document: Mapping[str, object], lane: str) -> bool:
    summary = _metric_summary(document, COMPARISON_LANE_FAMILIES[lane])
    return bool(summary.get("baseline_diff_available", False))


def _clone_compared(groups: Iterable[Mapping[str, object]], lane_trusted: bool) -> bool:
    """A trusted clone lane was compared unless its own groups say it was
    not (``comparison_unavailable``) — the one absence the document spells
    per group rather than per lane."""
    return lane_trusted and not any(
        group.get("novelty_reason") == NOVELTY_REASON_COMPARISON_UNAVAILABLE
        for group in groups
    )


def _availability(
    document: Mapping[str, object],
    identity: _Identity,
    *,
    trusted: set[str],
    disabled: set[str],
    clone_groups: Mapping[str, list[Mapping[str, object]]],
) -> frozenset[ComparisonAvailabilityRow]:
    clone_lanes = {lane: kind for kind, lane in CLONE_KIND_LANES.items()}
    rows: list[ComparisonAvailabilityRow] = []
    for lane in COMPARED_LANES:
        if lane in disabled:
            continue
        lane_trusted = lane in trusted
        if lane in clone_lanes:
            compared = _clone_compared(clone_groups[clone_lanes[lane]], lane_trusted)
        else:
            compared = _metric_compared(document, lane)
        rows.append(
            ComparisonAvailabilityRow(
                **identity,
                lane=lane,
                availability=comparison_availability_state(
                    compared=compared, lane_trusted=lane_trusted
                ),
            )
        )
    return frozenset(rows)


def _novelty(
    group: Mapping[str, object], identity: _Identity, where: str
) -> FindingNoveltyRow:
    return FindingNoveltyRow(
        **identity,
        finding_id=_text(group, "id", where),
        novelty=_text(group, "novelty", where),
        novelty_reason=_optional_text(group, "novelty_reason", where),
    )


def _novelty_families(
    document: Mapping[str, object],
    identity: _Identity,
    clone_groups: Mapping[str, list[Mapping[str, object]]],
) -> dict[str, frozenset[FindingNoveltyRow]]:
    families: dict[str, set[FindingNoveltyRow]] = {
        "clone_novelty": {
            _novelty(group, identity, f"{kind} clone group")
            for kind, groups in clone_groups.items()
            for group in groups
        },
        "dead_symbol_novelty": {
            _novelty(group, identity, "dead_code group")
            for group in _group_rows(document, "dead_code")
            if group.get("kind") == _DEAD_SYMBOL_KIND
        },
        **{family: set() for family in _DESIGN_NOVELTY_FAMILIES.values()},
    }
    for group in _group_rows(document, "design"):
        family = _DESIGN_NOVELTY_FAMILIES.get(str(group.get("category", "")))
        if family is not None:
            # Two groups of one declaration name (overloads) share one id
            # and one novelty: the set absorbs the repeat, and a
            # contradiction between them is the model's key refusal.
            families[family].add(_novelty(group, identity, "design group"))
    return {family: frozenset(rows) for family, rows in families.items()}


def _deltas(
    document: Mapping[str, object], identity: _Identity, compared: Mapping[str, str]
) -> dict[str, frozenset[MetricDeltaRow]]:
    deltas: dict[str, frozenset[MetricDeltaRow]] = {}
    for family, lane in _DELTA_FAMILY_LANES.items():
        if compared.get(lane) != "compared":
            deltas[family] = frozenset()
            continue
        document_family = COMPARISON_LANE_FAMILIES[lane]
        summary = _metric_summary(document, document_family)
        keys = _DOCUMENT_DELTA_KEYS[family]
        deltas[family] = frozenset(
            MetricDeltaRow(
                **identity,
                delta=term,
                value=_number(
                    summary, keys[term], f"metrics.families.{document_family}.summary"
                ),
            )
            for term in DELTA_FAMILY_TERMS[family]
        )
    return deltas


def comparison_facts_from_document(document: Mapping[str, object]) -> ComparisonFacts:
    """The comparison house the report document publishes — or the empty
    house for a document that never witnessed a comparison."""
    if "baseline" not in document:
        return ComparisonFacts()
    section = _mapping(document["baseline"], "baseline")
    meta = _mapping(_field(document, "meta", "document"), "meta")
    if not baseline_statuses_stated(meta):
        return ComparisonFacts()
    identity: _Identity = {
        "baseline_scope_id": _optional_text(section, "baseline_scope_id", "baseline"),
        "root_digest": _optional_text(section, "root_digest_or_null", "baseline"),
    }
    witness, metrics_witness = _witness(section, meta, identity)
    lane_trust = frozenset(
        LaneTrustRow(
            **identity,
            lane=_text(row, "name", "baseline.sorted_lane_trust[]"),
            status=_text(row, "status", "baseline.sorted_lane_trust[]"),
            reason=_text(row, "reason", "baseline.sorted_lane_trust[]"),
        )
        for row in _rows(section, "sorted_lane_trust", "baseline")
    )
    disabled_lanes = {
        str(lane)
        for lane in _sequence(
            _field(section, "disabled_capabilities", "baseline"),
            "baseline.disabled_capabilities",
        )
    }
    clone_groups = _clone_groups(document)
    availability = _availability(
        document,
        identity,
        trusted={row.lane for row in lane_trust if row.status == LANE_TRUSTED},
        disabled=disabled_lanes,
        clone_groups=clone_groups,
    )
    novelty = _novelty_families(document, identity, clone_groups)
    deltas = _deltas(
        document, identity, {row.lane: row.availability for row in availability}
    )
    return ComparisonFacts(
        baseline_witness=witness,
        metrics_baseline_witness=metrics_witness,
        lane_trust=lane_trust,
        comparison_availability=availability,
        disabled_capabilities=frozenset(
            DisabledCapabilityRow(**identity, lane=lane) for lane in disabled_lanes
        ),
        clone_novelty=novelty["clone_novelty"],
        complexity_novelty=novelty["complexity_novelty"],
        coupling_novelty=novelty["coupling_novelty"],
        dependency_cycle_novelty=novelty["dependency_cycle_novelty"],
        dead_symbol_novelty=novelty["dead_symbol_novelty"],
        adoption_delta=deltas["adoption_delta"],
        api_surface_delta=deltas["api_surface_delta"],
    )


__all__ = ["comparison_facts_from_document"]
