# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The published finding groups, rebuilt from canonical rows — one owner.

Canonical epoch E1 (2026-09-25).  The report document publishes one group
per finding under ``findings.groups.<family>``; every MCP consumer that
counts, filters or addresses findings reads those groups.  This module
rebuilds the ANALYSIS skeleton of every group out of the run store's
families, so the two can be held to each other byte for byte and a
consumer can one day read the store instead of the parent's memory.

**What is projected** is what a group asserts as analysis: its identity
(A3, spelled through the same ``findings.ids`` owner the document uses),
its family/category/kind, its count, the source scope and spread of its
sites, its items (site by site) and its facts.  The pieces are assembled
through ``findings.group_shapes`` — the owner the document builder itself
assembles them from since 2026-09-25 — so the skeleton and the document
cannot drift in two spellings.

**What is NOT projected**, named so it cannot rot: ``severity``,
``confidence`` (the quality tier), ``priority`` and ``clone_type`` are
evaluation; ``novelty`` and ``novelty_reason`` are comparison; the clone
items' per-kind metrics (``loc``, ``fingerprint``, ``size``…), the clone
facts beyond the key and arity (``loc_buckets``, the block machine facts)
and ``display_facts`` are not carried by the model; the ORDER of a family's
list is the document's priority order (evaluation) and is not reproduced —
the projection answers a family as a set keyed by identity.

Five of the eight families are stored as their own rows (the clone
populations, the structural, dead-code and hotspot groups); three are
derived from rows the model carried before E1 — dependency cycles from
``dependency_cycles`` + ``file_modules``, coverage groups from
``coverage_units`` + ``coverage_join`` + ``risk_observations`` through the
``metrics.coverage_join`` owners, authority groups from ``violations``
through ``canonical.authority_projection``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Final, cast

from codeclone.canonical.analysis_rows import (
    CloneItemRow,
    CohesionHotspotRow,
    ComplexityHotspotRow,
    CouplingHotspotRow,
    CoverageJoinRecord,
    CoverageUnitRow,
    DeadSymbolGroupRow,
    StructuralGroupRow,
    SuppressedCloneGroupRow,
    UnreachableStatementRow,
)
from codeclone.canonical.authority_projection import violation_projection_rows
from codeclone.canonical.codec import legacy_symbol_keys
from codeclone.canonical.identity import FileId, ModuleId, SymbolId
from codeclone.canonical.model import (
    AnalysisFacts,
    CanonicalModel,
    CloneGroupRow,
    DependencyCycleRow,
)
from codeclone.domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_COVERAGE,
    CATEGORY_DEPENDENCY,
    FAMILY_AUTHORITY,
    FAMILY_CLONE,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_STRUCTURAL,
    FINDING_KIND_AUTHORITY_VIOLATION,
    FINDING_KIND_CLONE_GROUP,
    FINDING_KIND_UNREACHABLE_STATEMENT,
    FINDING_KIND_UNUSED_SYMBOL,
)
from codeclone.findings.group_shapes import (
    DESIGN_HOTSPOT_KINDS,
    authority_group_facts,
    authority_location,
    cohesion_facts,
    cohesion_item_data,
    complexity_facts,
    complexity_item_data,
    coupling_facts,
    coupling_item_data,
    coverage_facts,
    coverage_group_kind,
    coverage_item_data,
    dead_symbol_facts,
    dependency_cycle_facts,
    dependency_member_item,
    module_classification_path,
    structural_facts,
    structural_signature,
    unreachable_statement_facts,
)
from codeclone.findings.ids import (
    authority_group_id,
    clone_group_id,
    dead_code_group_id,
    dependency_cycle_subject_key,
    design_group_id,
    structural_group_id,
)
from codeclone.metrics.cohesion import cohesion_risk
from codeclone.metrics.complexity import risk_level
from codeclone.metrics.coupling import coupling_risk
from codeclone.metrics.coverage_join import (
    coverage_hotspot,
    permille,
    scope_gap_hotspot,
)
from codeclone.models import ReportLocation, UnitCoverageFact
from codeclone.report.derived import (
    classify_source_kind,
    group_spread,
    source_scope_from_counts,
)
from codeclone.utils.coerce import as_mapping, as_sequence

if TYPE_CHECKING:
    from codeclone.metrics.coverage_join import _CoverageStatus

#: The document group keys this projection does NOT rebuild, by tier.
UNPROJECTED_GROUP_KEYS: Final[Mapping[str, str]] = {
    "severity": "evaluation",
    "confidence": "evaluation",
    "priority": "evaluation",
    "clone_type": "evaluation",
    "novelty": "comparison",
    "novelty_reason": "comparison",
    "display_facts": "presentation",
}

#: The published finding families, in the order the document walks them.
PROJECTED_FAMILIES: Final[tuple[str, ...]] = (
    FAMILY_CLONE,
    FAMILY_STRUCTURAL,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_AUTHORITY,
)

#: The item keys a clone-family item is projected with; the per-kind item
#: metrics (``loc``, ``stmt_count``, ``fingerprint``, ``size``…) stay with
#: the document.
SITE_ITEM_KEYS: Final[tuple[str, ...]] = (
    "relative_path",
    "qualname",
    "start_line",
    "end_line",
)

#: The clone facts projected: the key and the arity; ``loc_buckets`` and
#: the block machine facts stay with the document.
CLONE_FACT_KEYS: Final[tuple[str, ...]] = ("group_key", "group_arity")

_LegacyKeys = Mapping[SymbolId, str]
_Group = dict[str, object]


# -- sites -------------------------------------------------------------------


def _location(
    symbol: SymbolId, start_line: int, end_line: int, legacy: _LegacyKeys
) -> ReportLocation:
    return ReportLocation(
        filepath=symbol.file.path,
        relative_path=symbol.file.path,
        start_line=start_line,
        end_line=end_line,
        qualname=legacy[symbol],
        source_kind=classify_source_kind(symbol.file.path),
    )


def _site_locations(
    sites: Iterable[CloneItemRow], legacy: _LegacyKeys
) -> list[ReportLocation]:
    """The document's item order: path, start, end, qualname."""
    return sorted(
        (
            _location(site.symbol, site.start_line, site.end_line, legacy)
            for site in sites
        ),
        key=lambda location: (
            location.relative_path,
            location.start_line,
            location.end_line,
            location.qualname,
        ),
    )


def _item(location: ReportLocation) -> dict[str, object]:
    return {
        "relative_path": location.relative_path,
        "qualname": location.qualname,
        "start_line": location.start_line,
        "end_line": location.end_line,
    }


def _scope(locations: Iterable[ReportLocation]) -> dict[str, object]:
    return source_scope_from_counts(
        Counter(location.source_kind for location in locations)
    )


def _spread(locations: list[ReportLocation]) -> dict[str, int]:
    files, functions = group_spread(locations)
    return {"files": files, "functions": functions}


def _singleton(
    *,
    identity: str,
    family: str,
    category: str,
    kind: str,
    location: ReportLocation,
    item_data: Mapping[str, object],
    facts: Mapping[str, object],
) -> _Group:
    """One single-site group in the document's key order."""
    return {
        "id": identity,
        "family": family,
        "category": category,
        "kind": kind,
        "count": 1,
        "source_scope": _scope([location]),
        "spread": {"files": 1, "functions": 1 if location.qualname else 0},
        "items": [{**_item(location), **item_data}],
        "facts": dict(facts),
    }


# -- the clone populations (F8 and A1) --------------------------------------


def _clone_skeleton(
    kind: str, group_key: str, items: frozenset[CloneItemRow], legacy: _LegacyKeys
) -> _Group:
    locations = _site_locations(items, legacy)
    return {
        "id": clone_group_id(kind, group_key),
        "family": FAMILY_CLONE,
        "category": kind,
        "kind": FINDING_KIND_CLONE_GROUP,
        "clone_kind": kind,
        "count": len(items),
        "source_scope": _scope(locations),
        "spread": _spread(locations),
        "items": [_item(location) for location in locations],
        "facts": {"group_key": group_key, "group_arity": len(items)},
    }


def clone_group_skeletons(
    rows: Iterable[CloneGroupRow], legacy: _LegacyKeys
) -> list[_Group]:
    return [
        _clone_skeleton(row.clone_kind, row.group_key, row.items, legacy)
        for row in rows
    ]


def suppressed_clone_group_skeletons(
    rows: Iterable[SuppressedCloneGroupRow], legacy: _LegacyKeys
) -> list[_Group]:
    """A1: the suppressed population, with the suppressor's provenance
    after the facts — exactly where the document puts it."""
    skeletons: list[_Group] = []
    for row in rows:
        skeleton = _clone_skeleton(row.clone_kind, row.group_key, row.items, legacy)
        skeleton["suppression_rule"] = row.suppression_rule
        skeleton["suppression_source"] = row.suppression_source
        skeleton["matched_patterns"] = list(row.matched_patterns)
        skeletons.append(skeleton)
    return skeletons


# -- structural (A2) ----------------------------------------------------------


def structural_group_skeletons(
    rows: Iterable[StructuralGroupRow], legacy: _LegacyKeys
) -> list[_Group]:
    skeletons: list[_Group] = []
    for row in rows:
        locations = _site_locations(row.occurrences, legacy)
        signature = dict(row.signature)
        skeletons.append(
            {
                "id": structural_group_id(row.finding_kind, row.finding_key),
                "family": FAMILY_STRUCTURAL,
                "category": row.finding_kind,
                "kind": row.finding_kind,
                "count": len(row.occurrences),
                "source_scope": _scope(locations),
                "spread": _spread(locations),
                "signature": structural_signature(row.finding_kind, signature),
                "items": [_item(location) for location in locations],
                "facts": structural_facts(
                    row.finding_kind, signature, count=len(row.occurrences)
                ),
            }
        )
    return skeletons


# -- dead code (A2) -----------------------------------------------------------


def dead_symbol_group_skeletons(
    rows: Iterable[DeadSymbolGroupRow], legacy: _LegacyKeys
) -> list[_Group]:
    skeletons: list[_Group] = []
    for row in rows:
        location = _location(row.symbol, row.start_line, row.end_line, legacy)
        skeletons.append(
            _singleton(
                identity=dead_code_group_id(location.qualname),
                family=FAMILY_DEAD_CODE,
                category=row.candidate_kind,
                kind=FINDING_KIND_UNUSED_SYMBOL,
                location=location,
                item_data={},
                facts=dead_symbol_facts(
                    kind=row.candidate_kind,
                    confidence=row.confidence,
                    reason=row.reason,
                    test_reference_sources=row.test_reference_sources,
                ),
            )
        )
    return skeletons


def unreachable_statement_skeletons(
    rows: Iterable[UnreachableStatementRow], legacy: _LegacyKeys
) -> list[_Group]:
    skeletons: list[_Group] = []
    for row in rows:
        location = _location(row.symbol, row.start_line, row.end_line, legacy)
        skeletons.append(
            _singleton(
                identity=dead_code_group_id(
                    f"{location.qualname}#{row.start_line}-{row.end_line}"
                ),
                family=FAMILY_DEAD_CODE,
                category=FINDING_KIND_UNREACHABLE_STATEMENT,
                kind=FINDING_KIND_UNREACHABLE_STATEMENT,
                location=location,
                item_data={},
                facts=unreachable_statement_facts(
                    reason=row.reason, statement_count=row.statement_count
                ),
            )
        )
    return skeletons


# -- design (A2): the three stored hotspot families --------------------------


def _design_singleton(
    category: str,
    location: ReportLocation,
    item_data: Mapping[str, object],
    facts: Mapping[str, object],
) -> _Group:
    return _singleton(
        identity=design_group_id(category, location.qualname),
        family=FAMILY_DESIGN,
        category=category,
        kind=DESIGN_HOTSPOT_KINDS[category],
        location=location,
        item_data=item_data,
        facts=facts,
    )


def complexity_hotspot_skeletons(
    rows: Iterable[ComplexityHotspotRow], legacy: _LegacyKeys
) -> list[_Group]:
    """The ``risk`` label rides the item through its one owner, the
    complexity risk ladder — the class-B derivation the registry declares."""
    return [
        _design_singleton(
            CATEGORY_COMPLEXITY,
            _location(row.symbol, row.start_line, row.end_line, legacy),
            complexity_item_data(
                cyclomatic_complexity=row.cyclomatic_complexity,
                nesting_depth=row.nesting_depth,
                risk=risk_level(row.cyclomatic_complexity),
            ),
            complexity_facts(
                cyclomatic_complexity=row.cyclomatic_complexity,
                nesting_depth=row.nesting_depth,
            ),
        )
        for row in rows
    ]


def coupling_hotspot_skeletons(
    rows: Iterable[CouplingHotspotRow], legacy: _LegacyKeys
) -> list[_Group]:
    return [
        _design_singleton(
            CATEGORY_COUPLING,
            _location(row.symbol, row.start_line, row.end_line, legacy),
            coupling_item_data(
                cbo=row.cbo,
                risk=coupling_risk(row.cbo),
                coupled_classes=row.coupled_classes,
            ),
            coupling_facts(cbo=row.cbo, coupled_classes=row.coupled_classes),
        )
        for row in rows
    ]


def cohesion_hotspot_skeletons(
    rows: Iterable[CohesionHotspotRow], legacy: _LegacyKeys
) -> list[_Group]:
    return [
        _design_singleton(
            CATEGORY_COHESION,
            _location(row.symbol, row.start_line, row.end_line, legacy),
            cohesion_item_data(
                lcom4=row.lcom4,
                risk=cohesion_risk(row.lcom4),
                method_count=row.method_count,
                instance_var_count=row.instance_var_count,
            ),
            cohesion_facts(
                lcom4=row.lcom4,
                method_count=row.method_count,
                instance_var_count=row.instance_var_count,
            ),
        )
        for row in rows
    ]


# -- design: the two families derived from rows the model already carried ----


def dependency_cycle_skeletons(
    rows: Iterable[DependencyCycleRow], file_of_module: Mapping[ModuleId, FileId]
) -> list[_Group]:
    """The design/dependency groups: the members are the producer's SORTED
    strongly connected component (``metrics.dependencies.find_cycles`` sorts
    each), so the frozenset loses nothing; a member's path is the registry's
    FILE-MODULE relation, and a module without one claims no path."""
    skeletons: list[_Group] = []
    for row in rows:
        modules = sorted(module.module for module in row.modules)
        member_paths = [
            file_of_module[ModuleId(module)].path
            if ModuleId(module) in file_of_module
            else None
            for module in modules
        ]
        kinds = Counter(
            classify_source_kind(module_classification_path(module, member_path))
            for module, member_path in zip(modules, member_paths, strict=True)
        )
        skeletons.append(
            {
                "id": design_group_id(
                    CATEGORY_DEPENDENCY, dependency_cycle_subject_key(modules)
                ),
                "family": FAMILY_DESIGN,
                "category": CATEGORY_DEPENDENCY,
                "kind": row.kind,
                "count": len(modules),
                "source_scope": source_scope_from_counts(kinds),
                "spread": {"files": len(modules), "functions": 0},
                "items": [
                    dependency_member_item(module=module, member_path=member_path)
                    for module, member_path in zip(modules, member_paths, strict=True)
                ],
                "facts": dependency_cycle_facts(
                    kind=row.kind, cycle_length=len(modules)
                ),
            }
        )
    return skeletons


def _unit_complexity(facts: AnalysisFacts) -> dict[tuple[SymbolId, int], int]:
    """The cyclomatic complexity of every declaration, off the risk lane."""
    return {
        (row.symbol, row.start_line): row.numerator
        for row in facts.risk_observations
        if row.dimension == "cyclomatic_complexity"
    }


def _coverage_fact(
    row: CoverageUnitRow, complexity: int, legacy: _LegacyKeys
) -> UnitCoverageFact:
    return UnitCoverageFact(
        qualname=legacy[row.symbol],
        filepath=row.symbol.file.path,
        start_line=row.start_line,
        end_line=row.end_line,
        cyclomatic_complexity=complexity,
        risk=risk_level(complexity),
        executable_lines=row.executable_lines,
        covered_lines=row.covered_lines,
        coverage_permille=permille(row.covered_lines, row.executable_lines),
        # The row's status is a string of ``COVERAGE_UNIT_STATUSES``, the
        # fact's the owner's literal of the same three words.
        coverage_status=cast("_CoverageStatus", row.coverage_status),
    )


def coverage_group_skeletons(facts: AnalysisFacts, legacy: _LegacyKeys) -> list[_Group]:
    """The design/coverage groups: every unit the two hotspot rules select,
    the rules read through their owners in ``metrics.coverage_join``; the
    threshold is the join record's, the complexity the risk lane's."""
    record: CoverageJoinRecord | None = facts.coverage_join
    if record is None:
        return []
    complexity = _unit_complexity(facts)
    skeletons: list[_Group] = []
    for row in facts.coverage_units:
        fact = _coverage_fact(
            row, complexity.get((row.symbol, row.start_line), 1), legacy
        )
        hotspot = coverage_hotspot(
            fact=fact, hotspot_threshold_percent=record.hotspot_threshold_percent
        )
        scope_gap = scope_gap_hotspot(fact=fact)
        if not hotspot and not scope_gap:
            continue
        location = _location(row.symbol, row.start_line, row.end_line, legacy)
        subject = location.qualname or (
            f"{location.relative_path}:{row.start_line}:{row.end_line}"
        )
        kind, detail = coverage_group_kind(scope_gap_hotspot=scope_gap)
        skeletons.append(
            {
                "id": design_group_id(CATEGORY_COVERAGE, subject),
                "family": FAMILY_DESIGN,
                "category": CATEGORY_COVERAGE,
                "kind": kind,
                "count": 1,
                "source_scope": _scope([location]),
                "spread": {"files": 1, "functions": 1},
                "items": [
                    coverage_item_data(
                        relative_path=location.relative_path,
                        qualname=location.qualname,
                        start_line=row.start_line,
                        end_line=row.end_line,
                        risk=fact.risk,
                        cyclomatic_complexity=fact.cyclomatic_complexity,
                        coverage_permille=fact.coverage_permille,
                        coverage_status=fact.coverage_status,
                        covered_lines=fact.covered_lines,
                        executable_lines=fact.executable_lines,
                        coverage_hotspot=hotspot,
                        scope_gap_hotspot=scope_gap,
                    )
                ],
                "facts": coverage_facts(
                    coverage_permille=fact.coverage_permille,
                    hotspot_threshold_percent=record.hotspot_threshold_percent,
                    coverage_status=fact.coverage_status,
                    covered_lines=fact.covered_lines,
                    executable_lines=fact.executable_lines,
                    cyclomatic_complexity=fact.cyclomatic_complexity,
                    coverage_hotspot=hotspot,
                    scope_gap_hotspot=scope_gap,
                    detail=detail,
                ),
            }
        )
    return skeletons


# -- authority: derived from the violation rows through their projection -----


def authority_group_skeletons(model: CanonicalModel) -> list[_Group]:
    """The authority groups: one per unsuppressed violation row, built on
    the published violation row the one owner rebuilds."""
    skeletons: list[_Group] = []
    for row in violation_projection_rows(model):
        if bool(row["suppressed"]):
            continue
        locations = [
            authority_location(as_mapping(raw)) for raw in as_sequence(row["locations"])
        ]
        skeletons.append(
            {
                "id": authority_group_id(
                    str(row["contract_id"]), str(row["violation_id"])
                ),
                "family": FAMILY_AUTHORITY,
                "category": str(row["kind"]),
                "kind": FINDING_KIND_AUTHORITY_VIOLATION,
                "count": len(locations),
                "source_scope": source_scope_from_counts(
                    Counter(str(location["source_kind"]) for location in locations)
                ),
                "spread": {
                    "files": len(
                        {str(location["relative_path"]) for location in locations}
                    ),
                    "functions": len(
                        {
                            str(location["qualname"])
                            for location in locations
                            if str(location["qualname"])
                        }
                    ),
                },
                "items": locations,
                "facts": authority_group_facts(row),
            }
        )
    return skeletons


# -- the whole document skeleton ---------------------------------------------


def _symbols_of(facts: AnalysisFacts) -> set[SymbolId]:
    symbols: set[SymbolId] = set()
    for group in facts.clone_groups:
        symbols.update(item.symbol for item in group.items)
    for suppressed in facts.suppressed_clone_groups:
        symbols.update(item.symbol for item in suppressed.items)
    for structural in facts.structural_groups:
        symbols.update(item.symbol for item in structural.occurrences)
    symbols.update(row.symbol for row in facts.dead_symbol_groups)
    symbols.update(row.symbol for row in facts.unreachable_statement_groups)
    symbols.update(row.symbol for row in facts.complexity_hotspots)
    symbols.update(row.symbol for row in facts.coupling_hotspots)
    symbols.update(row.symbol for row in facts.cohesion_hotspots)
    symbols.update(row.symbol for row in facts.coverage_units)
    return symbols


def projected_finding_groups(model: CanonicalModel) -> dict[str, list[_Group]]:
    """Every published family's group skeletons, keyed by family, each
    family's list in a total ANALYSIS order (identity, then the items) —
    never the document's priority order, which is evaluation."""
    facts = model.facts.analysis
    legacy = legacy_symbol_keys(_symbols_of(facts), model.file_modules)
    file_of_module = {relation.module: relation.file for relation in model.file_modules}
    families: dict[str, list[_Group]] = {
        FAMILY_CLONE: clone_group_skeletons(facts.clone_groups, legacy),
        FAMILY_STRUCTURAL: structural_group_skeletons(facts.structural_groups, legacy),
        FAMILY_DEAD_CODE: [
            *dead_symbol_group_skeletons(facts.dead_symbol_groups, legacy),
            *unreachable_statement_skeletons(
                facts.unreachable_statement_groups, legacy
            ),
        ],
        FAMILY_DESIGN: [
            *complexity_hotspot_skeletons(facts.complexity_hotspots, legacy),
            *coupling_hotspot_skeletons(facts.coupling_hotspots, legacy),
            *cohesion_hotspot_skeletons(facts.cohesion_hotspots, legacy),
            *dependency_cycle_skeletons(facts.dependency_cycles, file_of_module),
            *coverage_group_skeletons(facts, legacy),
        ],
        FAMILY_AUTHORITY: authority_group_skeletons(model),
    }
    return {
        family: sorted(groups, key=group_order) for family, groups in families.items()
    }


def suppressed_clone_skeletons(model: CanonicalModel) -> list[_Group]:
    """A1: the suppressed population as the document's ``clones.suppressed``
    container publishes it, in the same total order."""
    facts = model.facts.analysis
    legacy = legacy_symbol_keys(_symbols_of(facts), model.file_modules)
    return sorted(
        suppressed_clone_group_skeletons(facts.suppressed_clone_groups, legacy),
        key=group_order,
    )


def group_order(group: Mapping[str, object]) -> tuple[str, str]:
    """A total order over one family's skeletons: identity, then the first
    site — two declarations of one qualname share a ``dead_code:`` identity
    and are told apart by where they sit."""
    items = as_sequence(group.get("items"))
    first = as_mapping(items[0]) if items else {}
    return (
        str(group.get("id", "")),
        f"{first.get('relative_path', '')}:{first.get('start_line', 0):012d}",
    )


__all__ = [
    "CLONE_FACT_KEYS",
    "PROJECTED_FAMILIES",
    "SITE_ITEM_KEYS",
    "UNPROJECTED_GROUP_KEYS",
    "authority_group_skeletons",
    "clone_group_skeletons",
    "cohesion_hotspot_skeletons",
    "complexity_hotspot_skeletons",
    "coupling_hotspot_skeletons",
    "coverage_group_skeletons",
    "dead_symbol_group_skeletons",
    "dependency_cycle_skeletons",
    "group_order",
    "projected_finding_groups",
    "structural_group_skeletons",
    "suppressed_clone_group_skeletons",
    "suppressed_clone_skeletons",
    "unreachable_statement_skeletons",
]
