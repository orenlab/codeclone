# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The facts one run lends the patch contract, from memory or from the store.

``check_patch_contract`` (and the verification ``finish_controlled_change``
runs) reads, of each run it is handed, a closed set of facts: the health
score, the budget's aggregates, the gate under a request, the finding
universe with its cards and paths, the per-symbol metric values and the
baseline status.  Everything else it states -- the run identity, the
execution witnesses that decide freshness and invariance, the request's
thresholds, the intent and its scope -- is the record's and the session's,
and stays read off the record on both sides.

Two answers to that one question live here, side by side, so the verifier
is written ONCE against :class:`PatchRun` and computed twice (consumer
migration C6): :class:`RecordPatchRun` answers from the in-memory record
through the very methods the verifier called before, and
:class:`StorePatchRun` answers from the run's rows in the run store
(``canonical.serving.ServedPatchRun``).  The run comparison reads its
memory side through the same facts, so the two runs of a verification are
compared by one comparison whichever side they come from.

Nothing here decides which answer is served; that is
``_run_store_serving.served_patch_contract``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Protocol

from ...api.run_residence import ResidentRun
from ...api.run_store_serving import (
    SERVING_REASON_SERVED,
    SERVING_SOURCE_RUN_STORE,
    RunStoreServingOutcome,
    ServedPatchRun,
    read_run_store_patch_run,
)
from ...utils.coerce import as_int as _coerce_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ...utils.finding_groups import baseline_tracked_group_keys
from . import _session_helpers as _helpers
from ._patch_contract import baseline_status
from ._run_residence import payload_evicted_outcome
from ._run_store_serving import PATCH_BUDGET_RUN, served_patch_contract
from ._session_finding_mixin import _FINDING_FAMILIES_BY_MODE
from ._session_shared import (
    FAMILY_CLONE,
    FAMILY_CLONES,
    GatingResult,
    MCPGateRequest,
    MCPHeldRun,
    MCPRunPayloadEvictedError,
    MCPRunRecord,
    MCPServiceContractError,
    MetricGateConfig,
    _evaluate_gate_state,
)
from .messages.patch_contract import (
    AMBIGUOUS_DECLARATION_IDENTITY_REASON,
    UNPAIRED_NO_COMPARABLE_PAIR,
    UNRESOLVED_NO_MEASURED_CHANGE,
    UNRESOLVED_POPULATIONS_DIFFER,
)

#: The value keys the verifier reads off each metric family's items, in the
#: order it tries them.
METRIC_VALUE_KEYS: Mapping[str, tuple[str, ...]] = {
    "complexity": ("cyclomatic_complexity", "complexity", "value"),
    "coupling": ("cbo", "coupling", "value"),
    "cohesion": ("lcom4", "cohesion", "value"),
}
#: One declaration's place in a run's metric index: ``(path, glued qualname)``.
MetricItemKey = tuple[str, str]
#: Where one measured declaration sits in its file: ``(start_line,
#: end_line)``, or ``None`` where the road that read the run does not carry
#: it (the store's class lane keeps no span).  A position is evidence, not
#: identity: it says where a measurement was taken, never which declaration
#: it belongs to across two runs.
DeclarationSpan = tuple[int, int] | None
#: One measured declaration of one family: its key, its span, its value.
MetricElement = tuple[MetricItemKey, DeclarationSpan, int]
#: A run's metric population for one family: every measured declaration as
#: one element, two declarations under one key as two elements.
MetricPopulation = tuple[MetricElement, ...]
#: The comparison card's fields, picked off the summary card of a finding
#: (``_session_finding_mixin._comparison_finding_card``).
COMPARISON_CARD_KEYS: tuple[str, ...] = ("id", "kind", "severity")

#: The families each focus of the run comparison keeps.
_FOCUS_FAMILIES: Mapping[str, frozenset[str]] = {
    "clones": frozenset({"clone"}),
    "structural": frozenset({"structural"}),
    "metrics": frozenset({"design", "dead_code"}),
}


def gate_config(request: MCPGateRequest) -> MetricGateConfig:
    """The gate configuration one request names -- one spelling for the
    gate over a run's document and the gate over its stored inputs."""
    return MetricGateConfig(
        fail_complexity=request.fail_complexity,
        fail_coupling=request.fail_coupling,
        fail_cohesion=request.fail_cohesion,
        fail_cycles=request.fail_cycles,
        fail_dead_code=request.fail_dead_code,
        fail_health=request.fail_health,
        fail_on_new_metrics=request.fail_on_new_metrics,
        fail_on_typing_regression=request.fail_on_typing_regression,
        fail_on_docstring_regression=request.fail_on_docstring_regression,
        fail_on_api_break=request.fail_on_api_break,
        fail_on_untested_hotspots=request.fail_on_untested_hotspots,
        min_typing_coverage=request.min_typing_coverage,
        min_docstring_coverage=request.min_docstring_coverage,
        coverage_min=request.coverage_min,
        fail_on_new=request.fail_on_new,
        fail_threshold=request.fail_threshold,
    )


def require_gate_coverage(
    request: MCPGateRequest, *, status: str | None, invalid_reason: str | None
) -> None:
    """Refuse a coverage gate over a run that joined no valid coverage
    report (``status`` ``None``: the run was handed none)."""
    if not request.fail_on_untested_hotspots:
        return
    if status is None:
        raise MCPServiceContractError(
            "Coverage gating requires a run created with coverage_xml."
        )
    if status != "ok":
        detail = invalid_reason or "invalid coverage input"
        raise MCPServiceContractError(
            f"Coverage gating requires a valid Cobertura XML input. Reason: {detail}"
        )


#: The finding family a finding-group container holds, where the two names
#: differ (``findings.groups.clones`` holds ``clone`` findings).
_GROUP_FINDING_FAMILY: Mapping[str, str] = {FAMILY_CLONES: FAMILY_CLONE}


def focus_is_analyzed(focus: str, *, analysis_mode: str) -> bool:
    """Whether a run comparison under ``focus`` compares any family the
    analysis mode produced: ``all`` always does; a focus whose families the
    mode never produced compares nothing (a clones-only pair asked for its
    structural or metrics findings), so it states no number."""
    families = _FOCUS_FAMILIES.get(focus)
    if families is None:
        return True
    produced = {
        _GROUP_FINDING_FAMILY.get(key, key)
        for key in _FINDING_FAMILIES_BY_MODE.get(
            analysis_mode, baseline_tracked_group_keys()
        )
    }
    return not families.isdisjoint(produced)


def focused_comparison_index(
    findings: Iterable[Mapping[str, object]], *, focus: str
) -> dict[str, dict[str, object]]:
    """The comparison's finding index under one focus, by canonical id."""
    families = _FOCUS_FAMILIES.get(focus)
    return {
        str(finding.get("id", "")): dict(finding)
        for finding in findings
        if families is None or str(finding.get("family", "")) in families
    }


class ComparisonFacts(Protocol):
    """What the run comparison reads of one run."""

    def health(self) -> int | None: ...

    def comparison_index(self, focus: str) -> dict[str, dict[str, object]]: ...

    def comparison_card(self, finding: Mapping[str, object]) -> dict[str, object]: ...


class PatchRun(ComparisonFacts, Protocol):
    """What the patch contract reads of one run, beside its record -- the
    record whole, or its resident identity when its payload was dropped:
    the verifier reads only the identity off it."""

    @property
    def record(self) -> MCPHeldRun: ...

    def current_state(self) -> dict[str, object]: ...

    def gate(self, request: MCPGateRequest) -> GatingResult: ...

    def finding_path_index(self) -> dict[str, frozenset[str]]: ...

    def metric_population(self, family: str) -> MetricPopulation: ...

    def baseline_status(self) -> str: ...


class PatchSession(Protocol):
    """The session methods the two answers are built from."""

    def _evaluate_gate_snapshot(
        self, *, record: MCPRunRecord, request: MCPGateRequest
    ) -> GatingResult: ...

    def _comparison_index(
        self, record: MCPRunRecord, *, focus: str
    ) -> dict[str, dict[str, object]]: ...

    def _comparison_finding_card(
        self, record: MCPRunRecord, finding: Mapping[str, object]
    ) -> dict[str, object]: ...

    def _finding_path_index(
        self, record: MCPRunRecord
    ) -> dict[str, frozenset[str]]: ...

    def _finding_path_index_for(
        self,
        findings: Sequence[Mapping[str, object]],
        *,
        canonical_to_short: Mapping[str, str],
    ) -> dict[str, frozenset[str]]: ...

    def _finding_id_maps_for_findings(
        self, findings: Sequence[Mapping[str, object]]
    ) -> tuple[dict[str, str], dict[str, str]]: ...

    def _project_finding_card(
        self,
        finding: Mapping[str, object],
        *,
        detail_level: str,
        short_finding_id: str,
    ) -> dict[str, object]: ...


# -- the record's facts: the verifier's own reads of a run's document -------


def record_current_state(record: MCPRunRecord) -> dict[str, object]:
    served_report = record.served_report
    # Each family by name: the consumer inventory reads which metric families
    # a consumer reads off its literal ``family=`` arguments
    # (``tests/test_projection_equivalence.py``).
    populations = {
        "complexity": record_metric_population(served_report, family="complexity"),
        "coupling": record_metric_population(served_report, family="coupling"),
        "cohesion": record_metric_population(served_report, family="cohesion"),
    }
    return {
        "health_score": _helpers._summary_health_score(record.summary),
        **population_maxima(populations.__getitem__),
        "dependency_cycles": len(_dependency_cycles(served_report)),
        "clone_groups": record.func_clones_count + record.block_clones_count,
        "dead_code_high_confidence": _dead_code_high_confidence(served_report),
    }


def record_metric_population(
    document: Mapping[str, object], *, family: str
) -> MetricPopulation:
    """The document's population of one family: every item, in document
    order, keyed by its path and symbol, with its span -- two items under
    one key are two elements, and nothing here decides which of them the
    key names."""
    value_keys = METRIC_VALUE_KEYS[family]
    return tuple(
        (
            (_item_path(item), _item_symbol(item)),
            _item_span(item),
            _first_int(item, keys=value_keys),
        )
        for item in _metric_family_items(document, family=family)
    )


def _item_span(item: Mapping[str, object]) -> DeclarationSpan:
    """The item's ``(start_line, end_line)``, or ``None`` when the item
    states no usable span (a missing or non-positive line, an end before
    its start): an unknown position is never spelled as a position."""
    start = _coerce_int(item.get("start_line"))
    end = _coerce_int(item.get("end_line"))
    return (start, end) if 0 < start <= end else None


def _metric_family_items(
    document: Mapping[str, object],
    *,
    family: str,
) -> tuple[Mapping[str, object], ...]:
    metrics = _as_mapping(document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    family_payload = _as_mapping(families.get(family))
    return tuple(
        _as_mapping(item) for item in _as_sequence(family_payload.get("items"))
    )


def _dead_code_high_confidence(document: Mapping[str, object]) -> int:
    return sum(
        1
        for item in _metric_family_items(document, family="dead_code")
        if str(item.get("confidence", "")).strip().lower() == "high"
    )


def _dependency_cycles(
    document: Mapping[str, object],
) -> tuple[object, ...]:
    metrics = _as_mapping(document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    dependencies = _as_mapping(families.get("dependencies"))
    return tuple(_as_sequence(dependencies.get("cycles")))


def _first_int(item: Mapping[str, object], *, keys: Sequence[str]) -> int:
    for key in keys:
        if key in item:
            return _coerce_int(item.get(key))
    return 0


def _item_path(item: Mapping[str, object]) -> str:
    for key in ("relative_path", "path", "filepath", "file"):
        value = str(item.get(key, "")).strip()
        if value:
            return value.replace("\\", "/")
    return ""


def _item_symbol(item: Mapping[str, object]) -> str:
    for key in ("qualname", "symbol", "name", "class_name", "function"):
        value = str(item.get(key, "")).strip()
        if value:
            return value
    return ""


# -- the per-declaration index: one rule for both roads -----------------------


def metric_item_index(
    population: Iterable[MetricElement],
) -> tuple[dict[MetricItemKey, int], dict[MetricItemKey, int]]:
    """``(resolved, counts)`` of one run's population of one family -- the
    store road's rows and the record road's document items alike, so the two
    roads cannot hold two rules.

    ``counts`` says how many declarations each key names, counted BEFORE any
    key is mapped to a value; ``resolved`` maps only the keys that name
    exactly one declaration, to its value.  A key that names two or more has
    no value at all: no element is chosen for it, first or last.  An element
    whose key names neither a path nor a symbol identifies no declaration
    and is counted nowhere (it still counts toward the population maximum).
    """
    elements = tuple(population)
    counts = Counter(key for key, _span, _value in elements if any(key))
    return (
        {key: value for key, _span, value in elements if counts[key] == 1},
        dict(counts),
    )


def population_maximum(population: Iterable[MetricElement]) -> int:
    """The largest value of the whole population: every declaration counts
    toward it, however its key resolves."""
    return max((value for _key, _span, value in population), default=0)


def population_maxima(
    population_of: Callable[[str], MetricPopulation],
) -> dict[str, int]:
    """``complexity_max`` / ``coupling_max`` / ``cohesion_max`` of one run,
    each over its family's whole population."""
    return {
        f"{family}_max": population_maximum(population_of(family))
        for family in METRIC_VALUE_KEYS
    }


def _ambiguous(counts: Mapping[MetricItemKey, int]) -> set[MetricItemKey]:
    return {key for key, count in counts.items() if count > 1}


def _key_record(family: str, key: MetricItemKey) -> dict[str, object]:
    return {"family": family, "path": key[0], "symbol": key[1]}


def compare_metric_items(
    family: str, *, before: MetricPopulation, after: MetricPopulation
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """One family's worsened symbols, unresolved keys and unpaired keys
    between two runs' populations, by the decision table below -- one
    outcome per pair of per-side states of a key (absent: 0 declarations,
    resolved: 1, ambiguous: 2 or more):

    ============  ============  ==============================================
    before        after         outcome
    ============  ============  ==============================================
    resolved      resolved      compared: ``worsened`` when the value grew
    ambiguous     resolved      ``unresolved``
    resolved      ambiguous     ``unresolved``
    ambiguous     ambiguous     ``unresolved``
    absent        ambiguous     ``unpaired``, ``added``
    ambiguous     absent        ``unpaired``, ``removed``
    absent        resolved      not compared (no before value exists)
    resolved      absent        not compared (no after value exists)
    ============  ============  ==============================================

    An ambiguous key present on one side only has no counterpart to match,
    so nothing of it is compared -- but the declarations it gained or lost
    are a structural fact, never dropped: ``unpaired`` names the key, the
    direction and both counts.  A unique key that appears or disappears is
    the ordinary new or removed declaration and is not listed.  Which
    unresolved keys still bind the patch is :func:`narrowed_unresolved`'s
    question, not this table's.
    """
    before_values, before_counts = metric_item_index(before)
    after_values, after_counts = metric_item_index(after)
    worsened: list[dict[str, object]] = [
        {
            **_key_record(family, key),
            "before": before_values[key],
            "after": value,
            "delta": value - before_values[key],
        }
        for key, value in after_values.items()
        if key in before_values and value > before_values[key]
    ]
    ambiguous = _ambiguous(before_counts) | _ambiguous(after_counts)
    unresolved: list[dict[str, object]] = [
        {
            **_key_record(family, key),
            "reason": AMBIGUOUS_DECLARATION_IDENTITY_REASON,
            "before_count": before_counts[key],
            "after_count": after_counts[key],
        }
        for key in ambiguous
        if key in before_counts and key in after_counts
    ]
    unpaired: list[dict[str, object]] = [
        {
            **_key_record(family, key),
            "direction": "removed" if key in before_counts else "added",
            "before_count": before_counts.get(key, 0),
            "after_count": after_counts.get(key, 0),
            "comparison": UNPAIRED_NO_COMPARABLE_PAIR,
        }
        for key in ambiguous
        if (key in before_counts) != (key in after_counts)
    ]
    return worsened, unresolved, unpaired


# -- positional narrowing: which unresolved keys still bind the patch ---------

#: One position a key's declarations occupy on one side, with the value of
#: every family the key is measured in there (``None``: that family measured
#: nothing at that position).
MeasuredSite = tuple[tuple[int, int], tuple[int | None, ...]]
_ElementsByKey = dict[MetricItemKey, list[tuple[DeclarationSpan, int]]]


def _elements_by_key(population: MetricPopulation) -> _ElementsByKey:
    grouped: _ElementsByKey = {}
    for key, span, value in population:
        grouped.setdefault(key, []).append((span, value))
    return grouped


def measured_sites(
    families: Sequence[str],
    elements: Mapping[str, Sequence[tuple[DeclarationSpan, int]]],
) -> tuple[MeasuredSite, ...] | None:
    """The multiset of ``(span, full vector)`` one key holds on one side:
    each position its declarations occupy, with the value of EVERY family in
    ``families`` measured there -- a class's coupling and cohesion together,
    a function's complexity -- in position order.

    ``None`` when the side holds no comparable sites: an element without a
    span (a position the road does not carry is not a position), or one
    position holding two elements of one family -- two identical
    declarations are two, never folded into one, and no vector can be
    paired to either of them.
    """
    sites: dict[tuple[int, int], dict[str, int]] = {}
    for family in families:
        for span, value in elements.get(family, ()):
            if span is None:
                return None
            measured = sites.setdefault(span, {})
            if family in measured:
                return None
            measured[family] = value
    return tuple(
        sorted(
            (
                (span, tuple(measured.get(family) for family in families))
                for span, measured in sites.items()
            ),
            key=lambda site: site[0],
        )
    )


def _key_populations_match(
    key: MetricItemKey,
    *,
    before: Mapping[str, _ElementsByKey],
    after: Mapping[str, _ElementsByKey],
) -> bool:
    """Whether the key's declarations hold the same measured metrics at the
    same positions on both sides: equal multisets of ``(span, vector)``
    over every family the key is measured in on either side."""
    families = tuple(
        family
        for family in METRIC_VALUE_KEYS
        if key in before[family] or key in after[family]
    )
    before_sites = measured_sites(
        families, {family: before[family].get(key, ()) for family in families}
    )
    after_sites = measured_sites(
        families, {family: after[family].get(key, ()) for family in families}
    )
    return before_sites is not None and before_sites == after_sites


def narrowed_unresolved(
    unresolved: Iterable[Mapping[str, object]],
    *,
    before: Mapping[str, MetricPopulation],
    after: Mapping[str, MetricPopulation],
) -> list[dict[str, object]]:
    """Each unresolved record with the ``population`` its key holds:

    ==============================================  ======================
    the key's ``(span, vector)`` multisets          ``population``
    ==============================================  ======================
    equal (cardinality, positions, every metric)    ``no_measured_change``
    different, or a side without comparable sites   ``differs``
    ==============================================  ======================

    ``no_measured_change`` says the measured metrics of these positions did
    not change -- nothing more: a position is not a declaration's identity,
    so it never says the same declarations are there, and no check but the
    worsened-symbols one reads it (API, behaviour, contracts and structural
    findings are judged as if it did not exist).  A shifted line is a
    different position and ``differs``, by design, until declarations carry
    an identity of their own.
    """
    before_by_key = {
        family: _elements_by_key(population) for family, population in before.items()
    }
    after_by_key = {
        family: _elements_by_key(population) for family, population in after.items()
    }
    verdicts: dict[MetricItemKey, str] = {}
    narrowed: list[dict[str, object]] = []
    for item in unresolved:
        key = (str(item["path"]), str(item["symbol"]))
        if key not in verdicts:
            verdicts[key] = (
                UNRESOLVED_NO_MEASURED_CHANGE
                if _key_populations_match(key, before=before_by_key, after=after_by_key)
                else UNRESOLVED_POPULATIONS_DIFFER
            )
        narrowed.append({**item, "population": verdicts[key]})
    return narrowed


def metric_item_changes(
    before: PatchRun, after: PatchRun
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Every family's worsened symbols, narrowed unresolved keys and unpaired
    keys between two runs, unordered (the verifier orders them)."""
    before_populations = {
        family: before.metric_population(family) for family in METRIC_VALUE_KEYS
    }
    after_populations = {
        family: after.metric_population(family) for family in METRIC_VALUE_KEYS
    }
    worsened: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    unpaired: list[dict[str, object]] = []
    for family in METRIC_VALUE_KEYS:
        family_worsened, family_unresolved, family_unpaired = compare_metric_items(
            family,
            before=before_populations[family],
            after=after_populations[family],
        )
        worsened.extend(family_worsened)
        unresolved.extend(family_unresolved)
        unpaired.extend(family_unpaired)
    return (
        worsened,
        narrowed_unresolved(
            unresolved, before=before_populations, after=after_populations
        ),
        unpaired,
    )


class RecordPatchRun:
    """One run's facts as the in-memory record holds them -- the verifier's
    own reads, unchanged."""

    def __init__(self, session: PatchSession, record: MCPRunRecord) -> None:
        self._session = session
        self._record = record

    @property
    def record(self) -> MCPRunRecord:
        return self._record

    def health(self) -> int | None:
        return _helpers._summary_health_score(self._record.summary)

    def current_state(self) -> dict[str, object]:
        return record_current_state(self._record)

    def gate(self, request: MCPGateRequest) -> GatingResult:
        return self._session._evaluate_gate_snapshot(
            record=self._record, request=request
        )

    def comparison_index(self, focus: str) -> dict[str, dict[str, object]]:
        return self._session._comparison_index(self._record, focus=focus)

    def comparison_card(self, finding: Mapping[str, object]) -> dict[str, object]:
        return self._session._comparison_finding_card(self._record, finding)

    def finding_path_index(self) -> dict[str, frozenset[str]]:
        return self._session._finding_path_index(self._record)

    def metric_population(self, family: str) -> MetricPopulation:
        return record_metric_population(self._record.served_report, family=family)

    def baseline_status(self) -> str:
        return baseline_status(self._record.served_report)


class StorePatchRun:
    """One run's facts as the run store holds them.

    The record still names the run and its execution (identity, root,
    request); every fact the verifier compares or evaluates is the stored
    one.  The finding universe is the run's tracked families under the
    STORED analysis mode -- the rule the record's universe follows under its
    request's mode -- and short ids, cards and paths are the session's own
    projections of it.
    """

    def __init__(
        self, session: PatchSession, record: MCPHeldRun, served: ServedPatchRun
    ) -> None:
        self._session = session
        self._record = record
        self._served = served
        families = _FINDING_FAMILIES_BY_MODE.get(
            served.analysis_mode, baseline_tracked_group_keys()
        )
        self._findings: tuple[Mapping[str, object], ...] = tuple(
            finding
            for family in families
            for finding in served.findings.get(family, ())
        )
        self._canonical_to_short = session._finding_id_maps_for_findings(
            self._findings
        )[0]

    @property
    def record(self) -> MCPHeldRun:
        return self._record

    def health(self) -> int | None:
        return self._served.health_score

    def current_state(self) -> dict[str, object]:
        return {
            "health_score": self._served.health_score,
            **population_maxima(self.metric_population),
            "dependency_cycles": self._served.dependency_cycles,
            "clone_groups": self._served.clone_groups,
            "dead_code_high_confidence": self._served.dead_code_high_confidence,
        }

    def gate(self, request: MCPGateRequest) -> GatingResult:
        """The same gate, under the same request, over the stored gate
        inputs: the same coverage refusal, the same configuration, the one
        evaluator."""
        require_gate_coverage(
            request,
            status=self._served.coverage_join_status,
            invalid_reason=self._served.coverage_invalid_reason,
        )
        return _evaluate_gate_state(
            state=self._served.gate_state,
            config=gate_config(request),
            lane_trust=self._served.lane_trust,
            enabled_lanes=self._served.enabled_lanes,
        )

    def comparison_index(self, focus: str) -> dict[str, dict[str, object]]:
        return focused_comparison_index(self._findings, focus=focus)

    def comparison_card(self, finding: Mapping[str, object]) -> dict[str, object]:
        canonical_id = str(finding.get("id", "")).strip()
        summary = self._session._project_finding_card(
            finding,
            detail_level="summary",
            short_finding_id=self._canonical_to_short.get(canonical_id, canonical_id),
        )
        return {key: summary.get(key) for key in COMPARISON_CARD_KEYS}

    def finding_path_index(self) -> dict[str, frozenset[str]]:
        return self._session._finding_path_index_for(
            self._findings, canonical_to_short=self._canonical_to_short
        )

    def metric_population(self, family: str) -> MetricPopulation:
        return self._served.metric_items[family]

    def baseline_status(self) -> str:
        return self._served.baseline_status


def serve_payload_evicted_answer(
    session: PatchSession,
    runs: Mapping[str, MCPHeldRun],
    answer: Callable[[Mapping[str, PatchRun]], dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    """An answer over runs one of which is held without its payload, and
    its ``serving`` block.

    There is no memory answer to shadow: every run is read through the
    patch-run door, which proves the run's membership before its first
    fact, and the answer is built over the stored facts -- a run held whole
    that the store does not answer for lends its own.  A run without its
    payload that the store does not answer for leaves nothing to answer
    from: the typed refusal, carrying where the store road went.
    """
    read = {
        side: read_run_store_patch_run(
            root=run.root, link=run.execution.run_snapshot_link
        )
        for side, run in runs.items()
    }
    facts: dict[str, PatchRun] = {}
    for side, run in runs.items():
        stored, _outcome = read[side]
        if stored is not None:
            facts[side] = StorePatchRun(session, run, stored)
        elif isinstance(run, MCPRunRecord):
            facts[side] = RecordPatchRun(session, run)
        else:
            raise MCPRunPayloadEvictedError(
                run, serving=payload_evicted_serving_block(runs, read)
            )
    return answer(facts), payload_evicted_serving_block(runs, read)


def payload_evicted_serving_block(
    runs: Mapping[str, MCPHeldRun],
    read: Mapping[str, tuple[ServedPatchRun | None, RunStoreServingOutcome]],
) -> dict[str, object]:
    """The ``serving`` block of an answer over runs one of which is held
    without its payload: the shape of the memory road's block (one run: the
    run's own outcome; a pair: an outcome and each run's under ``runs``),
    each run without its payload saying so; the outcome is the first such
    run the store refused, else ``served``."""
    own = {
        side: (
            payload_evicted_outcome(outcome)
            if isinstance(runs[side], ResidentRun)
            else outcome
        )
        for side, (_stored, outcome) in read.items()
    }
    if tuple(own) == (PATCH_BUDGET_RUN,):
        return own[PATCH_BUDGET_RUN].as_payload()
    refused = [
        outcome
        for side, outcome in own.items()
        if isinstance(runs[side], ResidentRun) and read[side][0] is None
    ]
    outcome = (
        refused[0]
        if refused
        else payload_evicted_outcome(
            RunStoreServingOutcome(
                source=SERVING_SOURCE_RUN_STORE, reason=SERVING_REASON_SERVED
            )
        )
    )
    return {
        **outcome.as_payload(),
        "runs": {side: outcome.as_payload() for side, outcome in own.items()},
    }


def serve_held_patch_answer(
    session: PatchSession,
    runs: Mapping[str, MCPHeldRun],
    answer: Callable[[Mapping[str, PatchRun], bool], dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    """The answer over runs held whole -- shadowed by the store's
    (:func:`serve_patch_answer`) -- or, when a run is held without its
    payload, over the stored facts alone, its audit events written
    (:func:`serve_payload_evicted_answer`)."""
    whole = {side: run for side, run in runs.items() if isinstance(run, MCPRunRecord)}
    if len(whole) == len(runs):
        return serve_patch_answer(session, whole, answer)
    return serve_payload_evicted_answer(
        session, runs, lambda facts: answer(facts, True)
    )


def serve_patch_answer(
    session: PatchSession,
    runs: Mapping[str, MCPRunRecord],
    answer: Callable[[Mapping[str, PatchRun], bool], dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    """The verifier's answer over the records -- its audit events written --
    shadowed by the same answer over the runs' stored facts, which writes
    none (``_run_store_serving.served_patch_contract`` decides which is
    served)."""
    memory = answer(
        {side: RecordPatchRun(session, record) for side, record in runs.items()},
        True,
    )
    return served_patch_contract(
        memory,
        runs,
        lambda stored: answer(
            {side: StorePatchRun(session, runs[side], stored[side]) for side in runs},
            False,
        ),
    )


__all__ = [
    "COMPARISON_CARD_KEYS",
    "METRIC_VALUE_KEYS",
    "ComparisonFacts",
    "DeclarationSpan",
    "MeasuredSite",
    "MetricElement",
    "MetricItemKey",
    "MetricPopulation",
    "PatchRun",
    "PatchSession",
    "RecordPatchRun",
    "StorePatchRun",
    "compare_metric_items",
    "focus_is_analyzed",
    "focused_comparison_index",
    "gate_config",
    "measured_sites",
    "metric_item_changes",
    "metric_item_index",
    "narrowed_unresolved",
    "payload_evicted_serving_block",
    "population_maxima",
    "population_maximum",
    "record_current_state",
    "record_metric_population",
    "require_gate_coverage",
    "serve_held_patch_answer",
    "serve_patch_answer",
    "serve_payload_evicted_answer",
]
