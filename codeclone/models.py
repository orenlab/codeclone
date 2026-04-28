# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypedDict


@dataclass(frozen=True, slots=True)
class Unit:
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    loc: int
    stmt_count: int
    fingerprint: str
    loc_bucket: str
    cyclomatic_complexity: int = 1
    nesting_depth: int = 0
    risk: Literal["low", "medium", "high"] = "low"
    raw_hash: str = ""
    entry_guard_count: int = 0
    entry_guard_terminal_profile: str = "none"
    entry_guard_has_side_effect_before: bool = False
    terminal_kind: str = "fallthrough"
    try_finally_profile: str = "none"
    side_effect_order_profile: str = "none"


@dataclass(frozen=True, slots=True)
class BlockUnit:
    block_hash: str
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    size: int


@dataclass(frozen=True, slots=True)
class SegmentUnit:
    segment_hash: str
    segment_sig: str
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    size: int


@dataclass(frozen=True, slots=True)
class SourceStats:
    """Structural counters collected while processing source files."""

    lines: int
    functions: int
    methods: int
    classes: int


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    cbo: int
    lcom4: int
    method_count: int
    instance_var_count: int
    risk_coupling: Literal["low", "medium", "high"]
    risk_cohesion: Literal["low", "medium", "high"]
    coupled_classes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModuleDep:
    source: str
    target: str
    import_type: Literal["import", "from_import"]
    line: int


@dataclass(frozen=True, slots=True)
class DepGraph:
    modules: frozenset[str]
    edges: tuple[ModuleDep, ...]
    cycles: tuple[tuple[str, ...], ...]
    max_depth: int
    avg_depth: float
    p95_depth: int
    longest_chains: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class DeadItem:
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    kind: Literal["function", "class", "method", "import"]
    confidence: Literal["high", "medium"]


@dataclass(frozen=True, slots=True)
class DeadCandidate:
    qualname: str
    local_name: str
    filepath: str
    start_line: int
    end_line: int
    kind: Literal["function", "class", "method", "import"]
    suppressed_rules: tuple[str, ...] = field(default_factory=tuple)


SecuritySurfaceCategory = Literal[
    "archive_extraction",
    "crypto_transport",
    "database_boundary",
    "deserialization",
    "dynamic_execution",
    "dynamic_loading",
    "filesystem_mutation",
    "identity_token",
    "network_boundary",
    "process_boundary",
]
SecuritySurfaceLocationScope = Literal["module", "class", "callable"]
SecuritySurfaceClassificationMode = Literal[
    "exact_builtin",
    "exact_call",
    "exact_import",
]
SecuritySurfaceEvidenceKind = Literal["builtin", "call", "import"]


@dataclass(frozen=True, slots=True)
class SecuritySurface:
    category: SecuritySurfaceCategory
    capability: str
    module: str
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    location_scope: SecuritySurfaceLocationScope
    classification_mode: SecuritySurfaceClassificationMode
    evidence_kind: SecuritySurfaceEvidenceKind
    evidence_symbol: str


@dataclass(frozen=True, slots=True)
class FileMetrics:
    class_metrics: tuple[ClassMetrics, ...]
    module_deps: tuple[ModuleDep, ...]
    dead_candidates: tuple[DeadCandidate, ...]
    referenced_names: frozenset[str]
    import_names: frozenset[str]
    class_names: frozenset[str]
    security_surfaces: tuple[SecuritySurface, ...] = ()
    referenced_qualnames: frozenset[str] = field(default_factory=frozenset)
    typing_coverage: ModuleTypingCoverage | None = None
    docstring_coverage: ModuleDocstringCoverage | None = None
    api_surface: ModuleApiSurface | None = None


@dataclass(frozen=True, slots=True)
class HealthScore:
    total: int
    grade: Literal["A", "B", "C", "D", "F"]
    dimensions: dict[str, int]


SourceKind = Literal["production", "tests", "fixtures", "mixed", "other"]


@dataclass(frozen=True, slots=True)
class ReportLocation:
    filepath: str
    relative_path: str
    start_line: int
    end_line: int
    qualname: str
    source_kind: SourceKind


@dataclass(frozen=True, slots=True)
class Suggestion:
    severity: Literal["critical", "warning", "info"]
    category: Literal[
        "clone",
        "structural",
        "complexity",
        "coupling",
        "cohesion",
        "dead_code",
        "dependency",
    ]
    title: str
    location: str
    steps: tuple[str, ...]
    effort: Literal["easy", "moderate", "hard"]
    priority: float
    finding_family: Literal["clones", "structural", "metrics"] = "metrics"
    finding_kind: str = ""
    subject_key: str = ""
    fact_kind: str = ""
    fact_summary: str = ""
    fact_count: int = 0
    spread_files: int = 0
    spread_functions: int = 0
    clone_type: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    source_kind: SourceKind = "other"
    source_breakdown: tuple[tuple[SourceKind, int], ...] = field(default_factory=tuple)
    representative_locations: tuple[ReportLocation, ...] = field(default_factory=tuple)
    location_label: str = ""


@dataclass(frozen=True, slots=True)
class ProjectMetrics:
    complexity_avg: float
    complexity_max: int
    high_risk_functions: tuple[str, ...]
    coupling_avg: float
    coupling_max: int
    high_risk_classes: tuple[str, ...]
    cohesion_avg: float
    cohesion_max: int
    low_cohesion_classes: tuple[str, ...]
    dependency_modules: int
    dependency_edges: int
    dependency_edge_list: tuple[ModuleDep, ...]
    dependency_cycles: tuple[tuple[str, ...], ...]
    dependency_max_depth: int
    dependency_longest_chains: tuple[tuple[str, ...], ...]
    dead_code: tuple[DeadItem, ...]
    health: HealthScore
    typing_param_total: int = 0
    typing_param_annotated: int = 0
    typing_return_total: int = 0
    typing_return_annotated: int = 0
    typing_any_count: int = 0
    docstring_public_total: int = 0
    docstring_public_documented: int = 0
    typing_modules: tuple[ModuleTypingCoverage, ...] = ()
    docstring_modules: tuple[ModuleDocstringCoverage, ...] = ()
    api_surface: ApiSurfaceSnapshot | None = None


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    max_complexity: int
    high_risk_functions: tuple[str, ...]
    max_coupling: int
    high_coupling_classes: tuple[str, ...]
    max_cohesion: int
    low_cohesion_classes: tuple[str, ...]
    dependency_cycles: tuple[tuple[str, ...], ...]
    dependency_max_depth: int
    dead_code_items: tuple[str, ...]
    health_score: int
    health_grade: Literal["A", "B", "C", "D", "F"]
    typing_param_permille: int = 0
    typing_return_permille: int = 0
    docstring_permille: int = 0
    typing_any_count: int = 0


@dataclass(frozen=True, slots=True)
class MetricsDiff:
    new_high_risk_functions: tuple[str, ...]
    new_high_coupling_classes: tuple[str, ...]
    new_cycles: tuple[tuple[str, ...], ...]
    new_dead_code: tuple[str, ...]
    health_delta: int
    typing_param_permille_delta: int = 0
    typing_return_permille_delta: int = 0
    docstring_permille_delta: int = 0
    new_api_symbols: tuple[str, ...] = ()
    new_api_breaking_changes: tuple[ApiBreakingChange, ...] = ()


@dataclass(frozen=True, slots=True)
class ApiParamSpec:
    name: str
    kind: Literal["pos_only", "pos_or_kw", "vararg", "kw_only", "kwarg"]
    has_default: bool
    annotation_hash: str = ""


@dataclass(frozen=True, slots=True)
class PublicSymbol:
    qualname: str
    kind: Literal["function", "class", "method", "constant"]
    start_line: int
    end_line: int
    params: tuple[ApiParamSpec, ...] = ()
    returns_hash: str = ""
    exported_via: Literal["all", "name"] = "name"


@dataclass(frozen=True, slots=True)
class ModuleApiSurface:
    module: str
    filepath: str
    symbols: tuple[PublicSymbol, ...]
    all_declared: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class ApiSurfaceSnapshot:
    modules: tuple[ModuleApiSurface, ...]


@dataclass(frozen=True, slots=True)
class ApiBreakingChange:
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    symbol_kind: Literal["function", "class", "method", "constant"]
    change_kind: Literal["removed", "signature_break"]
    detail: str


@dataclass(frozen=True, slots=True)
class ModuleTypingCoverage:
    module: str
    filepath: str
    callable_count: int
    params_total: int
    params_annotated: int
    returns_total: int
    returns_annotated: int
    any_annotation_count: int


@dataclass(frozen=True, slots=True)
class ModuleDocstringCoverage:
    module: str
    filepath: str
    public_symbol_total: int
    public_symbol_documented: int


@dataclass(frozen=True, slots=True)
class UnitCoverageFact:
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    cyclomatic_complexity: int
    risk: Literal["low", "medium", "high"]
    executable_lines: int
    covered_lines: int
    coverage_permille: int
    coverage_status: Literal["measured", "missing_from_report", "no_executable_lines"]


@dataclass(frozen=True, slots=True)
class CoverageJoinResult:
    coverage_xml: str
    status: Literal["ok", "invalid"]
    hotspot_threshold_percent: int
    files: int = 0
    measured_units: int = 0
    overall_executable_lines: int = 0
    overall_covered_lines: int = 0
    coverage_hotspots: int = 0
    scope_gap_hotspots: int = 0
    units: tuple[UnitCoverageFact, ...] = ()
    invalid_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SuppressedCloneGroup:
    kind: Literal["function", "block", "segment"]
    group_key: str
    items: tuple[GroupItem, ...]
    matched_patterns: tuple[str, ...] = ()
    suppression_rule: str = ""
    suppression_source: str = ""


GroupItem = dict[str, object]
GroupItemLike = Mapping[str, object]
GroupItemsLike = Sequence[GroupItemLike]
GroupMapLike = Mapping[str, Sequence[GroupItemLike]]


class FunctionGroupItemBase(TypedDict):
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    loc: int
    stmt_count: int
    fingerprint: str
    loc_bucket: str


class FunctionGroupItem(FunctionGroupItemBase, total=False):
    cyclomatic_complexity: int
    nesting_depth: int
    risk: Literal["low", "medium", "high"]
    raw_hash: str
    entry_guard_count: int
    entry_guard_terminal_profile: str
    entry_guard_has_side_effect_before: bool
    terminal_kind: str
    try_finally_profile: str
    side_effect_order_profile: str


class BlockGroupItem(TypedDict):
    block_hash: str
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    size: int


class SegmentGroupItem(TypedDict):
    segment_hash: str
    segment_sig: str
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    size: int


GroupMap = dict[str, list[GroupItem]]


@dataclass(frozen=True, slots=True)
class StructuralFindingOccurrence:
    """Single occurrence of a structural finding (e.g. one duplicate branch)."""

    finding_kind: str
    finding_key: str
    file_path: str
    qualname: str
    start: int
    end: int
    signature: dict[str, str]


@dataclass(frozen=True, slots=True)
class StructuralFindingGroup:
    """Group of structurally equivalent occurrences (e.g. duplicate branches)."""

    finding_kind: str
    finding_key: str
    signature: dict[str, str]
    items: tuple[StructuralFindingOccurrence, ...]
