# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Final, cast

from ...contracts import (
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    population_carries_score,
)
from ...domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CLONE_NOVELTY_KNOWN,
    CLONE_NOVELTY_NEW,
    CLONE_NOVELTY_UNAVAILABLE,
    FAMILY_DEAD_CODE,
)
from ...domain.quality import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    EFFORT_WEIGHT,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    SEVERITY_RANK,
)
from ...findings.structural.detectors import normalize_structural_findings
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ..derived import (
    normalized_source_kind as _normalized_source_kind,
)
from ..derived import (
    relative_report_path,
    report_location_from_group_item,
)
from ..derived import (
    source_scope_from_counts as _report_source_scope_from_counts,
)
from ..derived import (
    source_scope_from_locations as _report_source_scope_from_locations,
)

if TYPE_CHECKING:
    from ...contracts import ObservedPopulation
    from ...models import (
        GroupMapLike,
        MetricsDiff,
        ProjectMetrics,
        SourceKind,
        StructuralFindingGroup,
        SuppressedCloneGroup,
        TrustVector,
    )

_OVERLOADED_MODULES_FAMILY = "overloaded_modules"
_COVERAGE_ADOPTION_FAMILY = "coverage_adoption"
_API_SURFACE_FAMILY = "api_surface"
_COVERAGE_JOIN_FAMILY = "coverage_join"
_SECURITY_SURFACES_FAMILY = "security_surfaces"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerced_nonnegative_threshold(value: object, *, default: int) -> int:
    threshold = _as_int(value, default)
    return threshold if threshold >= 0 else default


def _design_findings_thresholds_payload(
    raw_meta: Mapping[str, object] | None,
) -> dict[str, object]:
    meta = dict(raw_meta or {})
    return {
        "design_findings": {
            CATEGORY_COMPLEXITY: {
                "metric": "cyclomatic_complexity",
                "operator": ">",
                "value": _coerced_nonnegative_threshold(
                    meta.get("design_complexity_threshold"),
                    default=DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
                ),
            },
            CATEGORY_COUPLING: {
                "metric": "cbo",
                "operator": ">",
                "value": _coerced_nonnegative_threshold(
                    meta.get("design_coupling_threshold"),
                    default=DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
                ),
            },
            CATEGORY_COHESION: {
                "metric": "lcom4",
                "operator": ">=",
                "value": _coerced_nonnegative_threshold(
                    meta.get("design_cohesion_threshold"),
                    default=DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
                ),
            },
        }
    }


def _analysis_profile_payload(
    raw_meta: Mapping[str, object] | None,
) -> dict[str, int] | None:
    meta = dict(raw_meta or {})
    nested = _as_mapping(meta.get("analysis_profile"))
    if nested:
        meta = dict(nested)
    keys = (
        "min_loc",
        "min_stmt",
        "block_min_loc",
        "block_min_stmt",
        "segment_min_loc",
        "segment_min_stmt",
    )
    if any(key not in meta for key in keys):
        return None
    payload = {key: _as_int(meta.get(key), -1) for key in keys}
    if any(value < 0 for value in payload.values()):
        return None
    return payload


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def _is_absolute_path(value: str) -> bool:
    normalized = _normalize_path(value)
    if not normalized:
        return False
    if normalized.startswith("/"):
        return True
    return len(normalized) > 2 and normalized[1] == ":" and normalized[2] == "/"


def _contract_path(
    value: object,
    *,
    scan_root: str,
) -> tuple[str | None, str | None, str | None]:
    path_text = _optional_str(value)
    if path_text is None:
        return None, None, None
    normalized_path = _normalize_path(path_text)
    relative_path = relative_report_path(normalized_path, scan_root=scan_root)
    if relative_path and relative_path != normalized_path:
        return relative_path, "in_root", normalized_path
    if _is_absolute_path(normalized_path):
        return normalized_path.rsplit("/", maxsplit=1)[-1], "external", normalized_path
    return normalized_path, "relative", None


def _contract_report_location_path(location_path: str, *, scan_root: str) -> str:
    contract_path, _scope, _absolute = _contract_path(
        location_path,
        scan_root=scan_root,
    )
    return contract_path or ""


def _priority(
    severity: str,
    effort: str,
) -> float:
    severity_rank = SEVERITY_RANK.get(severity, 1)
    effort_rank = EFFORT_WEIGHT.get(effort, 1)
    return float(severity_rank) / float(effort_rank)


def _clone_novelty(
    *,
    group_key: str,
    lane_trusted: bool,
    new_keys: Collection[str] | None,
) -> tuple[str, str | None]:
    """Return ``(novelty, novelty_reason)`` for one clone-lane identity.

    Sole owner of the clone novelty word. Two of the three states are absences
    and they are different absences, so they carry different reasons: the lane
    itself is not comparable under current contracts (`B4` per-lane
    compatibility), or the lane is comparable but no comparison was executed
    for it in this run (`B4` comparison availability).

    ``new_keys is None`` is the second one, and it is the reason this returns a
    tuple rather than a word. Folding ``None`` into the empty set read an
    absent comparison as "compared, nothing new" and answered ``known`` --
    asserting a comparison that never ran (`B8`, `B9`). An empty difference set
    is only evidence of sameness when a comparison produced it.
    """

    if not lane_trusted:
        return CLONE_NOVELTY_UNAVAILABLE, NOVELTY_REASON_LANE_UNAVAILABLE
    if new_keys is None:
        return CLONE_NOVELTY_UNAVAILABLE, NOVELTY_REASON_COMPARISON_UNAVAILABLE
    if group_key in frozenset(new_keys):
        return CLONE_NOVELTY_NEW, None
    return CLONE_NOVELTY_KNOWN, None


# Novelty domains whose per-entity difference the baseline actually computes
# (``codeclone/baseline/diff.py``). Everything outside this set has no
# comparison term at all, so its findings can only ever say "unavailable".
ENTITY_NOVELTY_DOMAIN_COMPLEXITY: Final = CATEGORY_COMPLEXITY
ENTITY_NOVELTY_DOMAIN_COUPLING: Final = CATEGORY_COUPLING
ENTITY_NOVELTY_DOMAIN_DEPENDENCIES: Final = "dependencies"
ENTITY_NOVELTY_DOMAIN_DEAD_CODE: Final = FAMILY_DEAD_CODE
BASELINE_GOVERNED_ENTITY_DOMAINS: Final = (
    ENTITY_NOVELTY_DOMAIN_COMPLEXITY,
    ENTITY_NOVELTY_DOMAIN_COUPLING,
    ENTITY_NOVELTY_DOMAIN_DEPENDENCIES,
    ENTITY_NOVELTY_DOMAIN_DEAD_CODE,
)

NOVELTY_REASON_LANE_UNAVAILABLE: Final = "lane_unavailable"
NOVELTY_REASON_NOT_GOVERNED: Final = "not_baseline_governed"
NOVELTY_REASON_ENTITY_NOT_COMPARED: Final = "entity_not_compared"
#: The lane is comparable, and no comparison was executed for it in this run.
#: Distinct from ``lane_unavailable`` on purpose: a reader that cannot tell the
#: two apart cannot tell "regenerate the baseline" from "nothing was compared".
NOVELTY_REASON_COMPARISON_UNAVAILABLE: Final = "comparison_unavailable"

_ENTITY_NOVELTY_COMPARED_KEY: Final = "compared"
_ENTITY_NOVELTY_NEW_KEY: Final = "new"


def _lane_is_trusted(trust: TrustVector | None, lane: str) -> bool:
    return bool(
        trust is not None
        and trust.root_verified
        and any(item.name == lane and item.status == "trusted" for item in trust.lanes)
    )


def _entity_novelty_facts(
    *,
    project_metrics: ProjectMetrics | None,
    metrics_diff: MetricsDiff | None,
    baseline_trust: TrustVector | None,
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Route the per-entity differences the baseline already computed.

    ``codeclone/baseline/diff.py`` computes these set differences and sends
    them to the gates; without this they never reach the findings that were
    compared, and ``list_findings(novelty="new")`` disagrees with the gate
    about the same regression. A domain is published only when its lane is
    trusted, so an untrusted lane still yields an honest "unavailable".

    ``compared`` is the current snapshot's population for that domain — the
    exact set ``compute_metrics_diff`` subtracted the baseline from — so an
    entity outside it is never called "known".
    """

    if project_metrics is None or metrics_diff is None:
        return {}
    # The same builder the diff itself uses for its current snapshot, so the
    # identities here cannot drift from the identities that were subtracted.
    from ...baseline._metrics_baseline_payload import snapshot_from_project_metrics

    current = snapshot_from_project_metrics(project_metrics)
    domains: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
        (
            ENTITY_NOVELTY_DOMAIN_COMPLEXITY,
            "risk_observations",
            current.high_risk_functions,
            metrics_diff.new_high_risk_functions,
        ),
        (
            ENTITY_NOVELTY_DOMAIN_COUPLING,
            "coupling_cohesion_observations",
            current.high_coupling_classes,
            metrics_diff.new_high_coupling_classes,
        ),
        (
            ENTITY_NOVELTY_DOMAIN_DEPENDENCIES,
            "dependencies",
            tuple(
                # The snapshot carries DependencyCycleFact since the cycle-policy
                # split (members + binding kind), while ``new_cycles`` is still
                # plain member tuples. Both sides must spell the identity from
                # the members alone: key them differently and every cycle would
                # read "not compared" while the diff says otherwise.
                _dependency_cycle_identity(cycle.modules)
                for cycle in current.dependency_cycles
            ),
            tuple(
                _dependency_cycle_identity(cycle) for cycle in metrics_diff.new_cycles
            ),
        ),
        (
            ENTITY_NOVELTY_DOMAIN_DEAD_CODE,
            "dead_code",
            current.dead_code_items,
            metrics_diff.new_dead_code,
        ),
    )
    return {
        domain: {
            _ENTITY_NOVELTY_COMPARED_KEY: tuple(sorted(set(compared))),
            _ENTITY_NOVELTY_NEW_KEY: tuple(sorted(set(new_entities))),
        }
        for domain, lane, compared, new_entities in domains
        if _lane_is_trusted(baseline_trust, lane)
    }


def health_verdict_withheld(health: Mapping[str, object]) -> bool:
    """True when this health block carries no number to project.

    One reader for the whole document tree. The two builders that consume it —
    the metrics family and the derived overview — used to answer this each on
    their own, from ``score is None``, which is the *consequence* of the
    producer's decision rather than the decision itself. That worked while
    there was exactly one way to be absent; it stops working the moment there
    are two, because neither builder can then say which absence it is holding,
    and the surfaces downstream have to word them apart.

    The population state is put to its owner, ``population_carries_score``. A
    health block carrying no state at all is older than the fact — a hand-built
    payload, or a wire format from before the split — and falls back to the
    producer's own signal, unchanged.

    Both signals are consulted, and an absence in either one wins. On every
    block ``health_report_fields`` produces they agree, so a reader that
    checked only one looked correct and was untestable: reverting the state
    check left the whole suite green. They can only disagree on a corrupted or
    hand-built block, and there the fail-closed reading is the only honest
    one — a state saying "nothing was measured" beside a number does not make
    the number real, and a missing number beside "complete" does not make
    ``0`` a measurement.
    """

    score_absent = health.get("score") is None
    population = str(health.get("population", ""))
    if not population:
        return score_absent
    state_absent = not population_carries_score(cast("ObservedPopulation", population))
    return state_absent or score_absent


def _dependency_cycle_identity(modules: Iterable[str]) -> str:
    """Identity a dependency cycle is compared under.

    Producer (``_entity_novelty_facts``) and consumer (the dependency design
    group) must spell one cycle the same way; both call this.
    """

    return " -> ".join(str(module) for module in modules)


def _entity_novelty(
    *,
    identity: str,
    domain: str,
    entity_novelty_facts: Mapping[str, object] | None,
) -> tuple[str, str | None]:
    """Return ``(novelty, novelty_reason)`` for one baseline-comparable entity.

    Three honest outcomes, never folded into two: the domain carries no
    comparison at all, the lane that would carry it is not trusted, or the
    comparison ran and this entity was inside its population. Absence of
    evidence stays ``unavailable`` — calling it ``known`` would assert a
    comparison that never happened.
    """

    if domain not in BASELINE_GOVERNED_ENTITY_DOMAINS:
        return CLONE_NOVELTY_UNAVAILABLE, NOVELTY_REASON_NOT_GOVERNED
    domain_facts = _as_mapping(_as_mapping(entity_novelty_facts).get(domain))
    if not domain_facts:
        return CLONE_NOVELTY_UNAVAILABLE, NOVELTY_REASON_LANE_UNAVAILABLE
    compared = frozenset(
        str(value)
        for value in _as_sequence(domain_facts.get(_ENTITY_NOVELTY_COMPARED_KEY))
    )
    if identity not in compared:
        return CLONE_NOVELTY_UNAVAILABLE, NOVELTY_REASON_ENTITY_NOT_COMPARED
    return _clone_novelty(
        group_key=identity,
        lane_trusted=True,
        new_keys=frozenset(
            str(value)
            for value in _as_sequence(domain_facts.get(_ENTITY_NOVELTY_NEW_KEY))
        ),
    )


def _item_sort_key(item: Mapping[str, object]) -> tuple[str, int, int, str]:
    return (
        str(item.get("relative_path", "")),
        _as_int(item.get("start_line")),
        _as_int(item.get("end_line")),
        str(item.get("qualname", "")),
    )


#: Operational rank vocabularies, worst first. A value outside the vocabulary
#: ranks below every known one rather than sorting alphabetically into the top.
_RISK_RANK: Final[dict[str, int]] = {RISK_HIGH: 3, RISK_MEDIUM: 2, RISK_LOW: 1}
_CONFIDENCE_RANK: Final[dict[str, int]] = {
    "critical": 4,
    CONFIDENCE_HIGH: 3,
    CONFIDENCE_MEDIUM: 2,
    CONFIDENCE_LOW: 1,
}


def _operational_sort_key(
    item: Mapping[str, object],
    *,
    rank_field: str = "risk",
    rank_vocabulary: Mapping[str, int] = _RISK_RANK,
    metric_field: str | None = None,
) -> tuple[int, int, str, str, int, int]:
    """Rank an operational report row: the row a reviewer must act on first.

    Rank descending, then the metric that earned that rank descending, then the
    stable ``(relative_path, qualname)`` tiebreak the report is aligned on. Line
    numbers close the key so the order stays total: rows of equal operational
    weight in one file cannot swap between runs.

    Ordering the quality tables by file path instead buried every high-risk row
    below the fifty rows the report renders, so the tables opened on whatever
    the alphabet put first.
    """

    rank = rank_vocabulary.get(str(item.get(rank_field, "")).strip().lower(), 0)
    metric = _as_int(item.get(metric_field)) if metric_field is not None else 0
    return (
        -rank,
        -metric,
        str(item.get("relative_path", "")),
        str(item.get("qualname", "")),
        _as_int(item.get("start_line")),
        _as_int(item.get("end_line")),
    )


def _parse_bool_text(value: object) -> bool:
    text = str(value).strip().lower()
    return text in {"1", "true", "yes"}


def _parse_ratio_percent(value: object) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100.0
        except ValueError:
            return None
    try:
        numeric = float(text)
    except ValueError:
        return None
    return numeric if numeric <= 1.0 else numeric / 100.0


def _normalize_block_machine_facts(
    *,
    group_key: str,
    group_arity: int,
    block_facts: Mapping[str, str],
) -> tuple[dict[str, object], dict[str, str]]:
    facts: dict[str, object] = {
        "group_key": group_key,
        "group_arity": group_arity,
    }
    display_facts: dict[str, str] = {}
    for key in sorted(block_facts):
        value = str(block_facts[key])
        match key:
            case "group_arity":
                facts[key] = _as_int(value)
            case "block_size" | "consecutive_asserts" | "instance_peer_count":
                facts[key] = _as_int(value)
            case "merged_regions":
                facts[key] = _parse_bool_text(value)
            case "assert_ratio":
                ratio = _parse_ratio_percent(value)
                if ratio is not None:
                    facts[key] = ratio
                display_facts[key] = value
            case (
                "match_rule" | "pattern" | "signature_kind" | "hint" | "hint_confidence"
            ):
                facts[key] = value
            case _:
                display_facts[key] = value
    return facts, display_facts


def _source_scope_from_filepaths(
    filepaths: Iterable[str],
    *,
    scan_root: str,
) -> dict[str, object]:
    counts: Counter[SourceKind] = Counter()
    for filepath in filepaths:
        location = report_location_from_group_item(
            {"filepath": filepath, "start_line": 0, "end_line": 0, "qualname": ""},
            scan_root=scan_root,
        )
        counts[location.source_kind] += 1
    return _source_scope_from_counts(counts)


def _source_scope_from_counts(
    counts: Mapping[SourceKind, int],
) -> dict[str, object]:
    return _report_source_scope_from_counts(counts)


def _source_scope_from_locations(
    locations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    normalized_locations = [
        {"source_kind": _normalized_source_kind(location.get("source_kind"))}
        for location in locations
    ]
    return _report_source_scope_from_locations(normalized_locations)


def _collect_paths_from_metrics(metrics: Mapping[str, object]) -> set[str]:
    paths: set[str] = set()
    complexity = _as_mapping(metrics.get(CATEGORY_COMPLEXITY))
    for item in _as_sequence(complexity.get("functions")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    for family_name in (CATEGORY_COUPLING, CATEGORY_COHESION):
        family = _as_mapping(metrics.get(family_name))
        for item in _as_sequence(family.get("classes")):
            item_map = _as_mapping(item)
            filepath = _optional_str(item_map.get("filepath"))
            if filepath is not None:
                paths.add(filepath)
    dead_code = _as_mapping(metrics.get(FAMILY_DEAD_CODE))
    for item in _as_sequence(dead_code.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    for item in _as_sequence(dead_code.get("suppressed_items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    overloaded_modules = _as_mapping(metrics.get(_OVERLOADED_MODULES_FAMILY))
    for item in _as_sequence(overloaded_modules.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    coverage_adoption = _as_mapping(metrics.get(_COVERAGE_ADOPTION_FAMILY))
    for item in _as_sequence(coverage_adoption.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    api_surface = _as_mapping(metrics.get(_API_SURFACE_FAMILY))
    for item in _as_sequence(api_surface.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    coverage_join = _as_mapping(metrics.get(_COVERAGE_JOIN_FAMILY))
    for item in _as_sequence(coverage_join.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    security_surfaces = _as_mapping(metrics.get(_SECURITY_SURFACES_FAMILY))
    for item in _as_sequence(security_surfaces.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    return paths


def _dedupe_paths_by_contract(
    paths: Iterable[str],
    *,
    scan_root: str,
) -> list[str]:
    """Collapse every spelling of one file onto a single entry.

    Producers disagree on spelling: discovery contributes absolute paths while
    some metric families contribute repository-relative ones, and which
    producer spells a path which way depends on cache warmth. Deduplicating the
    raw strings would keep one entry per *spelling*, so identity here is the
    contract path -- the identity the registry itself publishes.

    The absolute spelling wins when a producer offered one, because downstream
    line counting opens these paths and must not depend on the working
    directory. Iteration runs over sorted input so the surviving spelling never
    depends on set iteration order.
    """

    chosen: dict[str, str] = {}
    for path in sorted(paths):
        contract, _scope, absolute = _contract_path(path, scan_root=scan_root)
        if contract is None:
            continue
        candidate = absolute or path
        current = chosen.get(contract)
        if current is None or (
            not _is_absolute_path(current) and _is_absolute_path(candidate)
        ):
            chosen[contract] = candidate
    return [chosen[contract] for contract in sorted(chosen)]


def _collect_report_file_list(
    *,
    inventory: Mapping[str, object] | None,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None = None,
    metrics: Mapping[str, object] | None,
    structural_findings: Sequence[StructuralFindingGroup] | None,
    scan_root: str,
) -> list[str]:
    files: set[str] = set()
    inventory_map = _as_mapping(inventory)
    for filepath in _as_sequence(inventory_map.get("file_list")):
        file_text = _optional_str(filepath)
        if file_text is not None:
            files.add(file_text)
    for groups in (func_groups, block_groups, segment_groups):
        for items in groups.values():
            for item in items:
                filepath = _optional_str(item.get("filepath"))
                if filepath is not None:
                    files.add(filepath)
    for suppressed_group in suppressed_clone_groups or ():
        for item in suppressed_group.items:
            filepath = _optional_str(item.get("filepath"))
            if filepath is not None:
                files.add(filepath)
    if metrics is not None:
        files.update(_collect_paths_from_metrics(metrics))
    if structural_findings:
        for structural_group in normalize_structural_findings(structural_findings):
            for occurrence in structural_group.items:
                filepath = _optional_str(occurrence.file_path)
                if filepath is not None:
                    files.add(filepath)
    return _dedupe_paths_by_contract(files, scan_root=scan_root)


def _count_file_lines(filepaths: Sequence[str]) -> int:
    total = 0
    for filepath in filepaths:
        total += _count_file_lines_for_path(filepath)
    return total


def _count_file_lines_for_path(filepath: str) -> int:
    try:
        with open(filepath, encoding="utf-8", errors="surrogateescape") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _normalize_nested_string_rows(value: object) -> list[list[str]]:
    rows: list[tuple[str, ...]] = []
    for row in _as_sequence(value):
        modules = tuple(
            str(module) for module in _as_sequence(row) if str(module).strip()
        )
        if modules:
            rows.append(modules)
    rows.sort(key=lambda row: (len(row), row))
    return [list(row) for row in rows]


__all__ = [
    "_collect_report_file_list",
    "health_verdict_withheld",
    "normalize_structural_findings",
]
