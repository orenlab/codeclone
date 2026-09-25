# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The canonical epoch's first wave (E1, 2026-09-25): the published finding
groups, the external coverage join, the overloaded-module facts and the
dead-code population summary as families of the analysis tier.

Every row here is what the report document PUBLISHES for one grouped
finding or one producer fact — the population a consumer reads through
``findings.groups.*`` and ``metrics.families.*`` — spelled once as a typed
row with its natural key, so the run store can carry it and a projection
with one owner can rebuild the published skeleton byte for byte.  The
observation lanes the model already carries (``dead_code_observations``,
``risk_observations``, ``coupling_cohesion_observations``) are a DIFFERENT
population: measured on this repository @ ebe362d5, the dead-code lane
carries 19 929 rows while the document publishes 36 unused-symbol groups,
and the liveness verdict that selects those 36 is the producer's policy,
not a function of the lane rows.  A grouped finding is therefore stored as
the producer's verdict — the F7 cycle-kind precedent — never re-derived on
read.

Field epistemics follow the three-class law.  What a row carries is the
finding's OWN analysis payload as the document publishes it; a published
column that is strictly derivable from the row plus a versioned contract is
declared in the registry as contract-derived with its one formula owner
(the ``risk`` label of a hotspot, owned by the metric's risk ladder; the
coverage permille and hotspot flags, owned by ``metrics.coverage_join``)
and is never stored.  Values the document publishes at a fixed precision
(the overloaded-module scores, four decimals) are canonical AT that
precision: the row refuses a value the document could not have carried.

Shared validators keep the family laws in one spelling: a span is positive
and never backwards, a count is a non-negative int and never a bool, a
vocabulary member is proven against the identity module's closed tuple.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields

from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.identity import (
    CLONE_KINDS,
    COVERAGE_JOIN_STATUSES,
    COVERAGE_UNIT_MEASURED,
    COVERAGE_UNIT_STATUSES,
    DEAD_CODE_CANDIDATE_KINDS,
    DEAD_SYMBOL_CONFIDENCES,
    DEAD_SYMBOL_REASONS,
    OVERLOADED_CANDIDATE_STATUSES,
    SECURITY_SOURCE_KINDS,
    STRUCTURAL_FINDING_KINDS,
    UNREACHABLE_REASONS,
    WORLD_CONTRACTS,
    FileId,
    SymbolId,
)

#: The published precision of every overloaded-module score: the document
#: rounds each to four decimals (``report/document/metrics.py``), and the
#: canonical value IS the published one — a finer float would be a value no
#: reader of the document could ever have seen.
OVERLOADED_SCORE_DECIMALS = 4

#: The dead-symbol reason whose evidence list is non-empty by contract.
DEAD_SYMBOL_TEST_ONLY_REASON = "test_only_reference"

#: The coverage-join status under which no unit was measured.
COVERAGE_JOIN_INVALID = "invalid"


def _require_member(value: str, vocabulary: tuple[str, ...], what: str) -> None:
    if value not in vocabulary:
        raise CanonicalModelError(f"unknown {what}: {value!r}")


def _require_count(value: int, what: str, *, floor: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < floor:
        raise CanonicalModelError(
            f"{what} must be an int of at least {floor}: {value!r}"
        )


def _require_span(start_line: int, end_line: int, what: str) -> None:
    _require_count(start_line, f"{what} start line", floor=1)
    if isinstance(end_line, bool) or not isinstance(end_line, int):
        raise CanonicalModelError(f"{what} end line must be an int: {end_line!r}")
    if end_line < start_line:
        raise CanonicalModelError(
            f"{what} end line must not precede its start: {end_line!r}"
        )


def _require_text(value: str, what: str) -> None:
    if not isinstance(value, str) or not value:
        raise CanonicalModelError(f"{what} must be a non-empty string: {value!r}")


def _require_texts(values: Iterable[str], what: str) -> None:
    for value in values:
        _require_text(value, f"{what} member")


def _require_sorted_unique(values: tuple[str, ...], what: str) -> None:
    _require_texts(values, what)
    if values != tuple(sorted(set(values))):
        raise CanonicalModelError(f"{what} must be sorted and unique: {values!r}")


def _require_published_score(value: float, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, float):
        raise CanonicalModelError(f"{what} must be a float: {value!r}")
    if value != value or value in (float("inf"), float("-inf")) or value < 0.0:
        raise CanonicalModelError(f"{what} must be a finite non-negative float")
    if round(value, OVERLOADED_SCORE_DECIMALS) != value:
        raise CanonicalModelError(
            f"{what} carries more than {OVERLOADED_SCORE_DECIMALS} decimals, "
            f"which the document never publishes: {value!r}"
        )


@dataclass(frozen=True, slots=True)
class CloneItemRow:
    """One member of an emitted clone group: the unit and its span.

    The span IS part of the member's identity — the corpus's block group
    carries an intra-function pair (one SYMBOL, two spans), so group arity
    and item identity are different measurements and a span-blind member
    would silently collapse the pair.  Per-kind item metrics (``loc``,
    ``fingerprint``, ``size``, ``segment_hash``…) stay with the legacy
    document for a later wave — the wave subset decides what is carried
    (the candidate-scoring precedent).

    Shared by the emitted and the suppressed clone families (E1): the two
    are different populations of the SAME member shape, so one row type
    keeps the member law in one spelling.
    """

    symbol: SymbolId
    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        _require_span(self.start_line, self.end_line, "clone item")


@dataclass(frozen=True, slots=True, kw_only=True)
class SuppressedCloneGroupRow:
    """A1: one clone group the suppression policy took OUT of the emitted
    population, with the provenance of that decision.

    A different population from ``clone_groups`` (ruling 2026-08-24 §10),
    stored as its own family and never mixed in: the emitted family is what
    the gate and the baseline lane read, and a suppressed group that leaked
    into it would move both.  The natural key is the producer's own,
    ``(clone_kind, group_key)``, exactly as on the emitted family — one
    producer key string may exist under two kinds.  The provenance triple
    is the suppressor's statement: which rule (``golden_fixture``), from
    which source (``project_config``), matched which patterns, in the order
    the suppressor recorded them (a producer order is a fact, the
    ``output_facts`` precedent).  Every suppressed group carries at least
    one matched pattern by the producer's own law
    (``findings/clones/golden_fixtures.py``: a group without a pattern is
    never suppressed), and at least two members like any clone group.
    """

    clone_kind: str
    group_key: str
    items: frozenset[CloneItemRow]
    suppression_rule: str
    suppression_source: str
    matched_patterns: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_member(self.clone_kind, CLONE_KINDS, "clone kind")
        _require_text(self.group_key, "suppressed clone group key")
        if len(self.items) < 2:
            raise CanonicalModelError(
                "a suppressed clone group names at least two items (a group "
                "of one is not a grouping the producer makes)"
            )
        _require_text(self.suppression_rule, "suppression rule")
        _require_text(self.suppression_source, "suppression source")
        if not self.matched_patterns:
            raise CanonicalModelError(
                "a suppressed clone group names at least one matched pattern "
                "(the suppressor never suppresses without one)"
            )
        _require_texts(self.matched_patterns, "matched patterns")


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuralGroupRow:
    """A2: one structural finding group as the detectors publish it.

    Natural key: the producer's ``(finding_kind, finding_key)`` — the same
    pair the document's ``structural:{kind}:{key}`` identity is spelled
    from through its one owner (``findings.ids.structural_group_id``).  The
    signature is the detector's raw ``dict[str, str]`` as sorted unique
    pairs (the document publishes it verbatim under ``signature.debug`` and
    derives the typed ``stable`` block from it through
    ``findings.group_shapes.structural_signature``); the occurrences are
    the group's member sites, each a unit and its span, and a group names
    at least one.
    """

    finding_kind: str
    finding_key: str
    signature: tuple[tuple[str, str], ...]
    occurrences: frozenset[CloneItemRow]

    def __post_init__(self) -> None:
        _require_member(self.finding_kind, STRUCTURAL_FINDING_KINDS, "finding kind")
        _require_text(self.finding_key, "structural finding key")
        keys = tuple(key for key, _value in self.signature)
        _require_sorted_unique(keys, "structural signature keys")
        for _key, value in self.signature:
            if not isinstance(value, str):
                raise CanonicalModelError(
                    f"structural signature values must be strings: {value!r}"
                )
        if not self.occurrences:
            raise CanonicalModelError(
                "a structural group names at least one occurrence"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadSymbolGroupRow:
    """A2: one unused-symbol finding as the liveness policy published it.

    Natural key ``(SYMBOL, start_line)`` — the declaration-site key of
    ``unit_spans``, for the same measured reason: different declarations
    share one qualname (``@overload`` families, property/setter pairs), and
    the document's own ``dead_code:{qualname}`` identity is blind to them.
    The payload is the producer's ``DeadItem`` verbatim: the candidate
    kind, the confidence tier, the reason, and the sorted unique test
    references whose presence is bound to the reason by the producer's own
    contract (``models.DeadItem``: test-only evidence is non-empty exactly
    when the reason says test-only).
    """

    symbol: SymbolId
    start_line: int
    end_line: int
    candidate_kind: str
    confidence: str
    reason: str
    test_reference_sources: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_span(self.start_line, self.end_line, "dead symbol")
        _require_member(
            self.candidate_kind, DEAD_CODE_CANDIDATE_KINDS, "dead-code candidate kind"
        )
        _require_member(
            self.confidence, DEAD_SYMBOL_CONFIDENCES, "dead-symbol confidence"
        )
        _require_member(self.reason, DEAD_SYMBOL_REASONS, "dead-symbol reason")
        _require_sorted_unique(self.test_reference_sources, "test reference sources")
        test_only = self.reason == DEAD_SYMBOL_TEST_ONLY_REASON
        if test_only != bool(self.test_reference_sources):
            raise CanonicalModelError(
                "dead-symbol test references are non-empty exactly when the "
                f"reason is {DEAD_SYMBOL_TEST_ONLY_REASON!r}: "
                f"{self.reason!r} with {self.test_reference_sources!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class UnreachableStatementRow:
    """A2: one unreachable region inside a live unit (39Y Y9), as the CFG
    producer published it.

    Natural key ``(SYMBOL, start_line)``: a region starts at one line of
    one unit.  ``reason`` is the producer's closed vocabulary and
    ``statement_count`` is at least one — the producer's own floor
    (``models.UnreachableStatementItem``).  The confidence and the policy
    version the document publishes beside these are constants of the
    finding kind, owned by ``findings.group_shapes.unreachable_statement_facts``.
    """

    symbol: SymbolId
    start_line: int
    end_line: int
    reason: str
    statement_count: int

    def __post_init__(self) -> None:
        _require_span(self.start_line, self.end_line, "unreachable region")
        _require_member(self.reason, UNREACHABLE_REASONS, "unreachable reason")
        _require_count(self.statement_count, "unreachable statement count", floor=1)


@dataclass(frozen=True, slots=True, kw_only=True)
class ComplexityHotspotRow:
    """A2 (design, complexity): one function the run's own design
    threshold classified a hotspot, with the measures the finding
    publishes.

    Natural key ``(SYMBOL, start_line)``.  The threshold that selected the
    row lives in the run's analysis contract (``meta.analysis_thresholds``)
    and not in this family: the row IS the verdict, the F7 precedent.  The
    ``risk`` label the document publishes beside the measures is
    contract-derived through the complexity risk ladder and never stored.
    """

    symbol: SymbolId
    start_line: int
    end_line: int
    cyclomatic_complexity: int
    nesting_depth: int

    def __post_init__(self) -> None:
        _require_span(self.start_line, self.end_line, "complexity hotspot")
        _require_count(self.cyclomatic_complexity, "cyclomatic complexity", floor=1)
        _require_count(self.nesting_depth, "nesting depth")


@dataclass(frozen=True, slots=True, kw_only=True)
class CouplingHotspotRow:
    """A2 (design, coupling): one class the run's coupling threshold
    classified a hotspot.  Natural key ``(SYMBOL, start_line)``.

    ``coupled_classes`` is the producer's sorted unique label set — the
    per-class attribution the standalone ``coupled_sets`` value family
    deliberately does not carry.
    """

    symbol: SymbolId
    start_line: int
    end_line: int
    cbo: int
    coupled_classes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_span(self.start_line, self.end_line, "coupling hotspot")
        _require_count(self.cbo, "cbo")
        _require_sorted_unique(self.coupled_classes, "coupled classes")


@dataclass(frozen=True, slots=True, kw_only=True)
class CohesionHotspotRow:
    """A2 (design, cohesion): one class the run's cohesion threshold
    classified a hotspot.  Natural key ``(SYMBOL, start_line)``."""

    symbol: SymbolId
    start_line: int
    end_line: int
    lcom4: int
    method_count: int
    instance_var_count: int

    def __post_init__(self) -> None:
        _require_span(self.start_line, self.end_line, "cohesion hotspot")
        _require_count(self.lcom4, "lcom4")
        _require_count(self.method_count, "method count")
        _require_count(self.instance_var_count, "instance variable count")


#: The overloaded-module counters, in wire order: every one a non-negative
#: observed count of the producer (zero is measured).
OVERLOADED_MODULE_COUNTERS = (
    "callable_count",
    "classes",
    "complexity_max",
    "complexity_total",
    "fan_in",
    "fan_out",
    "functions",
    "import_edges",
    "loc",
    "methods",
    "reimport_edges",
    "total_deps",
)

#: The overloaded-module scores, in wire order: each published at
#: :data:`OVERLOADED_SCORE_DECIMALS`.
OVERLOADED_MODULE_SCORES = (
    "dependency_score",
    "hub_balance",
    "instability",
    "reimport_ratio",
    "score",
    "shape_score",
    "size_score",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OverloadedModuleRow:
    """A4: one module of the overloaded-modules producer, keyed by FILE.

    Measured 1 247/1 247 unique on path and on module @ ebe362d5 (a dated
    observation).  The document's ``module`` column is the registry's
    FILE-MODULE projection (the file's module, or its path when it has
    none) and is never stored.  ``source_kind`` is the classification
    VERDICT of the one owner (``SOURCE_KIND_POLICY_VERSION``), stored as a
    fact — the F10 precedent.  The twelve counters are observed; the seven
    scores are the producer's composite, canonical at the document's
    four-decimal precision; ``candidate_status`` is the producer's closed
    verdict and ``candidate_reasons`` its ordered reasons.
    """

    file: FileId
    source_kind: str
    callable_count: int
    classes: int
    complexity_max: int
    complexity_total: int
    fan_in: int
    fan_out: int
    functions: int
    import_edges: int
    loc: int
    methods: int
    reimport_edges: int
    total_deps: int
    dependency_score: float
    hub_balance: float
    instability: float
    reimport_ratio: float
    score: float
    shape_score: float
    size_score: float
    candidate_status: str
    candidate_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_member(self.source_kind, SECURITY_SOURCE_KINDS, "source kind")
        for counter in OVERLOADED_MODULE_COUNTERS:
            _require_count(getattr(self, counter), f"overloaded module {counter}")
        for score in OVERLOADED_MODULE_SCORES:
            _require_published_score(getattr(self, score), f"overloaded module {score}")
        _require_member(
            self.candidate_status,
            OVERLOADED_CANDIDATE_STATUSES,
            "overloaded candidate status",
        )
        _require_texts(self.candidate_reasons, "overloaded candidate reasons")


def overloaded_module_row(
    *,
    file: FileId,
    source_kind: str,
    candidate_status: str,
    candidate_reasons: tuple[str, ...],
    counters: Mapping[str, int],
    scores: Mapping[str, float],
) -> OverloadedModuleRow:
    """The one spelling of the row from its two column groups.

    Every reader of the family (wire, store, ingest, the producer-native
    builder) collects the twelve counters and the seven scores by name
    through :data:`OVERLOADED_MODULE_COUNTERS` and
    :data:`OVERLOADED_MODULE_SCORES`; this constructor is where those names
    meet the row's fields, once, so a column cannot be wired to the wrong
    field in one reader and not another.
    """
    return OverloadedModuleRow(
        file=file,
        source_kind=source_kind,
        callable_count=counters["callable_count"],
        classes=counters["classes"],
        complexity_max=counters["complexity_max"],
        complexity_total=counters["complexity_total"],
        fan_in=counters["fan_in"],
        fan_out=counters["fan_out"],
        functions=counters["functions"],
        import_edges=counters["import_edges"],
        loc=counters["loc"],
        methods=counters["methods"],
        reimport_edges=counters["reimport_edges"],
        total_deps=counters["total_deps"],
        dependency_score=scores["dependency_score"],
        hub_balance=scores["hub_balance"],
        instability=scores["instability"],
        reimport_ratio=scores["reimport_ratio"],
        score=scores["score"],
        shape_score=scores["shape_score"],
        size_score=scores["size_score"],
        candidate_status=candidate_status,
        candidate_reasons=candidate_reasons,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageUnitRow:
    """A5: one unit's joined line coverage, from the external Cobertura
    report the run was handed.  Natural key ``(SYMBOL, start_line)``.

    Only what the join OBSERVED is stored: the executable and covered line
    counts inside the unit's span and the status that says whether the
    report mapped the unit at all.  The permille, the risk label, the
    complexity and the two hotspot flags the document publishes beside
    them are derived through their owners (``metrics.coverage_join`` and
    the ``risk_observations`` family) and never stored.  The producer's own
    laws ride the row: a measured unit has executable lines, and a unit
    the report never mapped (or one without executable lines) has none.
    """

    symbol: SymbolId
    start_line: int
    end_line: int
    executable_lines: int
    covered_lines: int
    coverage_status: str

    def __post_init__(self) -> None:
        _require_span(self.start_line, self.end_line, "coverage unit")
        _require_count(self.executable_lines, "executable lines")
        _require_count(self.covered_lines, "covered lines")
        _require_member(self.coverage_status, COVERAGE_UNIT_STATUSES, "coverage status")
        if self.covered_lines > self.executable_lines:
            raise CanonicalModelError(
                "covered lines cannot exceed executable lines: "
                f"{self.covered_lines}/{self.executable_lines}"
            )
        measured = self.coverage_status == COVERAGE_UNIT_MEASURED
        if measured != (self.executable_lines > 0):
            raise CanonicalModelError(
                "a coverage unit is measured exactly when it has executable "
                f"lines: {self.coverage_status!r} with {self.executable_lines}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageJoinRecord:
    """A5: the coverage join's own record — ONE per run, present exactly
    when the run was handed a coverage report.

    ``None`` on the model is the honest absence (no ``--coverage-xml``);
    a record with ``status="invalid"`` is a report that could not be read,
    carrying the reason and no units.  ``source`` is the report's path as
    the document contracts it (in-root relative, or the file name of an
    external path); ``files`` is the number of files the report mapped
    into the run — a fact of the XML, not of the units; the threshold is
    the run's request.  The counters the document publishes beside these
    (``units``, ``measured_units``, the overall line sums and permille, the
    two hotspot counts) are sums over the unit family and are derived, not
    stored.
    """

    status: str
    source: str
    files: int
    hotspot_threshold_percent: int
    invalid_reason: str | None

    def __post_init__(self) -> None:
        _require_member(self.status, COVERAGE_JOIN_STATUSES, "coverage join status")
        _require_text(self.source, "coverage join source")
        _require_count(self.files, "coverage join files")
        _require_count(self.hotspot_threshold_percent, "coverage hotspot threshold")
        invalid = self.status == COVERAGE_JOIN_INVALID
        if invalid != (self.invalid_reason is not None):
            raise CanonicalModelError(
                "a coverage join carries an invalid reason exactly when its "
                f"status is invalid: {self.status!r} with {self.invalid_reason!r}"
            )
        if self.invalid_reason is not None:
            _require_text(self.invalid_reason, "coverage join invalid reason")
        if invalid and self.files:
            raise CanonicalModelError("an invalid coverage join mapped no file")


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadCodeSummaryRecord:
    """A7: the dead-code lane's population counters — ONE record per run.

    Measured NOT derivable from the observation lane (@ ebe362d5 on this
    repository: candidates 18 621 + nested 1 309 against 19 929 lane rows,
    the abstention lanes absent from it entirely), so the producer's own
    counters are stored as facts (``ProjectMetrics``: the abstention lane
    sizes, the judged population, the world contract every verdict was
    derived under, the live roots).  The three counters the document
    publishes beside these that ARE derivable — ``total`` and
    ``high_confidence`` from ``dead_symbol_groups``,
    ``unreachable_statements`` from ``unreachable_statement_groups`` — are
    projected, never stored.  Zero is measured on every counter.
    """

    suppressed: int
    unresolved: int
    unresolved_internal: int
    unresolved_external_override: int
    candidates: int
    nested_candidates: int
    live_roots: int
    world_contract: str

    def __post_init__(self) -> None:
        for record_field in fields(self):
            if record_field.name != "world_contract":
                _require_count(
                    getattr(self, record_field.name),
                    f"dead-code summary {record_field.name}",
                )
        _require_member(self.world_contract, WORLD_CONTRACTS, "world contract")


__all__ = [
    "COVERAGE_JOIN_INVALID",
    "DEAD_SYMBOL_TEST_ONLY_REASON",
    "OVERLOADED_MODULE_COUNTERS",
    "OVERLOADED_MODULE_SCORES",
    "OVERLOADED_SCORE_DECIMALS",
    "CloneItemRow",
    "CohesionHotspotRow",
    "ComplexityHotspotRow",
    "CouplingHotspotRow",
    "CoverageJoinRecord",
    "CoverageUnitRow",
    "DeadCodeSummaryRecord",
    "DeadSymbolGroupRow",
    "OverloadedModuleRow",
    "StructuralGroupRow",
    "SuppressedCloneGroupRow",
    "UnreachableStatementRow",
    "overloaded_module_row",
]
