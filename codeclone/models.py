# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

DEFAULT_OBSERVABILITY_RETENTION_DAYS = 7
DEFAULT_OBSERVABILITY_MAX_OPERATIONS = 2000
DEFAULT_OBSERVABILITY_MAX_SPANS = 100

ConfigCliKind = Literal[
    "positional",
    "value",
    "optional_path",
    "bool_optional",
    "store_true",
    "store_false",
    "help",
    "version",
]
CompatibilityPolicyKind = Literal[
    "exact",
    "supported_versions",
    "ordered_migration",
]
CompatibilityStatus = Literal[
    "compatible",
    "incompatible",
    "migration_required",
    "unknown_contract",
]
ImportMountOrigin = Literal["explicit", "conventional_src", "root"]
ModuleIdentityStrategy = ImportMountOrigin
PythonModuleOrigin = Literal["import_mount"]
PythonModuleNodeKind = Literal["module_file", "regular_package"]
ModuleInternality = Literal["analyzed", "known_internal_not_analyzed"]
DependencyResolution = Literal[
    "analyzed",
    "known_internal_not_analyzed",
    "external",
    "unresolved_relative",
    "ambiguous",
]
PackagePrefixNodeKind = Literal["namespace_package", "synthetic_prefix"]
AnalysisMountOrigin = Literal["analysis_only"]
PortablePathIssueKind = Literal[
    "ascii_control",
    "case_collision",
    "nfc_collision",
    "trailing_dot_or_space",
    "windows_device",
    "windows_forbidden_byte",
]

CONFIG_VALUE_UNSET = object()


@dataclass(frozen=True, slots=True)
class ConfigKeySpec:
    expected_type: type[object]
    allow_none: bool = False
    expected_name: str | None = None


@dataclass(frozen=True, slots=True)
class OptionSpec:
    dest: str
    group: str | None
    cli_kind: ConfigCliKind | None = None
    flags: tuple[str, ...] = ()
    default: object = CONFIG_VALUE_UNSET
    value_type: type[object] | None = None
    const: object | None = None
    nargs: str | int | None = None
    metavar: str | None = None
    help_text: str | None = None
    pyproject_key: str | None = None
    config_spec: ConfigKeySpec | None = None
    path_value: bool = False

    @property
    def has_default(self) -> bool:
        return self.default is not CONFIG_VALUE_UNSET


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    values: dict[str, object]
    explicit_cli_dests: frozenset[str]
    pyproject_values: dict[str, object]


class FoundationConfigInput(BaseModel):
    """Strict TOML-boundary model; never passed into analysis code."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_roots: tuple[str, ...] | None = None
    baseline_scope_id: str | None = None
    project_label: str | None = None

    @field_validator("baseline_scope_id")
    @classmethod
    def _canonical_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = UUID(value)
        except ValueError as exc:
            raise ValueError("baseline_scope_id must be a canonical UUID") from exc
        if str(parsed) != value:
            raise ValueError("baseline_scope_id must be a canonical UUID")
        return value


@dataclass(frozen=True, slots=True)
class FoundationConfig:
    source_roots: tuple[str, ...] | None
    baseline_scope_id: str | None
    project_label: str | None


@dataclass(frozen=True, slots=True)
class CompatibilityPolicy:
    kind: CompatibilityPolicyKind
    supported: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ContractVerdict:
    contract: str
    required: str
    actual: str | None
    status: CompatibilityStatus
    compatible: bool


@dataclass(frozen=True, slots=True)
class CompatibilityVerdict:
    status: CompatibilityStatus
    compatible: bool
    per_contract: tuple[ContractVerdict, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportMount:
    path: str
    module_prefix: str
    origin: ImportMountOrigin


@dataclass(frozen=True, slots=True, kw_only=True)
class FileIdentity:
    path: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PythonModuleIdentity:
    module: str
    package: str
    is_package: bool
    mount_path: str
    origin: PythonModuleOrigin
    node_kind: PythonModuleNodeKind

    def __post_init__(self) -> None:
        if not self.module:
            raise ValueError("python module identity requires a module name")
        if self.is_package != (self.node_kind == "regular_package"):
            raise ValueError("package flag and node kind must describe one state")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedSourceIdentity:
    file: FileIdentity
    python_module: PythonModuleIdentity | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PortablePathIssue:
    kind: PortablePathIssueKind
    paths: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PortablePathVerdict:
    eligible: bool
    normalized_paths: tuple[str, ...]
    issues: tuple[PortablePathIssue, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalysisMount:
    path: str
    origin: AnalysisMountOrigin = "analysis_only"


@dataclass(frozen=True, slots=True, kw_only=True)
class PathNormalizationPolicy:
    path_form: Literal["posix_nfc"] = "posix_nfc"
    case_sensitive: Literal[True] = True


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleIdentityManifest:
    module_identity_version: str
    strategy: ModuleIdentityStrategy
    import_mounts: tuple[ImportMount, ...]
    analysis_mount: AnalysisMount
    normalization: PathNormalizationPolicy


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleIdentityBuildResult:
    manifest: ModuleIdentityManifest
    manifest_json: str
    manifest_digest: str
    identities: tuple[ResolvedSourceIdentity, ...]
    portability: PortablePathVerdict


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleInventoryEntry:
    identity: ResolvedSourceIdentity
    analyzed: bool
    internality: ModuleInternality

    def __post_init__(self) -> None:
        expected = "analyzed" if self.analyzed else "known_internal_not_analyzed"
        if self.internality != expected:
            raise ValueError("module inventory internality must match analyzed state")


@dataclass(frozen=True, slots=True, kw_only=True)
class PackagePrefix:
    module: str
    node_kind: PackagePrefixNodeKind
    mount_paths: tuple[str, ...]
    contributing_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.module:
            raise ValueError("package prefix requires a non-empty module")
        if self.mount_paths != tuple(sorted(set(self.mount_paths))):
            raise ValueError("package prefix mount paths must be sorted and unique")
        if self.contributing_paths != tuple(sorted(set(self.contributing_paths))):
            raise ValueError(
                "package prefix contributing paths must be sorted and unique"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DigestObject:
    domain: Literal["codeclone.module-registry.v1"]
    algorithm: Literal["sha256"]
    value: str

    def __post_init__(self) -> None:
        if len(self.value) != 64 or any(
            character not in "0123456789abcdef" for character in self.value
        ):
            raise ValueError("sha256 digest values must be 64 lowercase hex characters")


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleInventoryIndex(Mapping[str, ModuleInventoryEntry]):
    """Picklable immutable registry index with deterministic key order."""

    rows: tuple[tuple[str, ModuleInventoryEntry], ...]

    def __post_init__(self) -> None:
        keys = tuple(key for key, _entry in self.rows)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("module inventory index keys must be sorted and unique")

    def __getitem__(self, key: str) -> ModuleInventoryEntry:
        low = 0
        high = len(self.rows)
        while low < high:
            middle = (low + high) // 2
            row_key, entry = self.rows[middle]
            if row_key < key:
                low = middle + 1
            elif row_key > key:
                high = middle
            else:
                return entry
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _entry in self.rows)

    def __len__(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleRegistryHandle:
    manifest: ModuleIdentityManifest
    entries_by_path: ModuleInventoryIndex
    entries_by_module: ModuleInventoryIndex
    package_prefixes: tuple[PackagePrefix, ...]
    digest: DigestObject


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservabilityConfig:
    enabled: bool
    persist: bool = True
    profile: bool = False
    capture_payload_sizes: bool = True
    retention_days: int = DEFAULT_OBSERVABILITY_RETENTION_DAYS
    max_operations_per_process: int = DEFAULT_OBSERVABILITY_MAX_OPERATIONS
    max_spans_per_operation: int = DEFAULT_OBSERVABILITY_MAX_SPANS

    def __post_init__(self) -> None:
        bounded = (
            self.retention_days,
            self.max_operations_per_process,
            self.max_spans_per_operation,
        )
        if any(value <= 0 for value in bounded):
            raise ValueError("observability retention and caps must be positive")


@dataclass(frozen=True, slots=True)
class StageCounterSnapshot:
    """Deterministic, mergeable worker counters applied by a parent stage."""

    counters: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(sorted(self.counters))
        keys = tuple(key for key, _value in normalized)
        if len(keys) != len(set(keys)):
            raise ValueError("stage counter snapshot keys must be unique")
        object.__setattr__(self, "counters", normalized)

    def merge(self, other: StageCounterSnapshot) -> StageCounterSnapshot:
        merged = dict(self.counters)
        for key, value in other.counters:
            merged[key] = merged.get(key, 0) + value
        return StageCounterSnapshot(tuple(merged.items()))


@dataclass(frozen=True, slots=True)
class ObserverCounterSemantics:
    stored_version: str | None
    current_version: int
    mixed_semantics: bool


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


RelationshipKind = Literal["call", "reference"]
RelationshipResolutionStatus = Literal["resolved", "unresolved"]
RelationshipOriginLane = Literal["production", "test"]


@dataclass(frozen=True, slots=True)
class RelationshipRecord:
    relation_kind: RelationshipKind
    resolution_status: RelationshipResolutionStatus
    origin_lane: RelationshipOriginLane
    source_qualname: str
    target_qualname: str | None
    path: str
    line: int
    expression: str | None = None
    resolution_rule: str | None = None


@dataclass(frozen=True, slots=True)
class FunctionRelationshipFacts:
    source_qualname: str
    relationships: tuple[RelationshipRecord, ...]


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
class ClassWalkFacts:
    couplings: frozenset[str]
    method_to_attrs: dict[str, set[str]]
    method_calls: dict[str, set[str]]
    all_method_count: int


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
    resolution: DependencyResolution = "external"
    inventory_expansion: bool = False
    level: int = 0
    requested_module: str | None = None
    requested_names: tuple[str, ...] = ()
    candidate_targets: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportObservation:
    source: ResolvedSourceIdentity
    syntax_kind: Literal["import", "from_import"]
    level: int
    requested_module: str | None
    requested_names: tuple[str, ...]
    resolution: DependencyResolution
    candidate_targets: tuple[str, ...]
    resolved_target: str | None
    inventory_expansion: bool = False

    def __post_init__(self) -> None:
        if self.candidate_targets != tuple(sorted(set(self.candidate_targets))):
            raise ValueError("import candidate targets must be sorted and unique")
        if self.resolution == "unresolved_relative":
            if self.resolved_target is not None:
                raise ValueError("unresolved relative imports cannot have a target")
        elif not self.resolved_target:
            raise ValueError("resolved import observations require a target")


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


RuntimeReachabilityFramework = Literal[
    "aiogram",
    "aiohttp",
    "celery",
    "click",
    "dependency_injector",
    "django",
    "fastapi",
    "flask",
    "pydantic",
    "sqlalchemy",
    "starlette",
    "typer",
]
RuntimeReachabilityEdgeKind = Literal[
    "declares_dependency",
    "provides",
    "registers_command",
    "registers_handler",
    "registers_task",
    "runtime_hook",
]
RuntimeReachabilityConfidence = Literal["high", "medium", "low"]
RuntimeReachabilityTargetKind = Literal["function", "class", "method"]


@dataclass(frozen=True, slots=True)
class RuntimeReachabilityFact:
    target_qualname: str
    filepath: str
    start_line: int
    end_line: int
    target_kind: RuntimeReachabilityTargetKind
    framework: RuntimeReachabilityFramework
    edge_kind: RuntimeReachabilityEdgeKind
    confidence: RuntimeReachabilityConfidence
    evidence: str
    evidence_symbol: str
    source_qualname: str = ""


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
    runtime_reachability: tuple[RuntimeReachabilityFact, ...] = ()
    security_surfaces: tuple[SecuritySurface, ...] = ()
    referenced_qualnames: frozenset[str] = field(default_factory=frozenset)
    typing_coverage: ModuleTypingCoverage | None = None
    docstring_coverage: ModuleDocstringCoverage | None = None
    api_surface: ModuleApiSurface | None = None
    function_relationship_facts: tuple[FunctionRelationshipFacts, ...] = ()


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
    runtime_reachability: tuple[RuntimeReachabilityFact, ...] = ()
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


@dataclass(slots=True)
class MetricProjectContext:
    units: tuple[GroupItemLike, ...]
    class_metrics: tuple[ClassMetrics, ...]
    module_deps: tuple[ModuleDep, ...]
    dead_candidates: tuple[DeadCandidate, ...]
    referenced_names: frozenset[str]
    referenced_qualnames: frozenset[str]
    module_registry: ModuleRegistryHandle
    runtime_reachability: tuple[RuntimeReachabilityFact, ...] = ()
    security_surfaces: tuple[SecuritySurface, ...] = ()
    typing_modules: tuple[ModuleTypingCoverage, ...] = ()
    docstring_modules: tuple[ModuleDocstringCoverage, ...] = ()
    api_modules: tuple[ModuleApiSurface, ...] = ()
    files_found: int = 0
    files_analyzed_or_cached: int = 0
    function_clone_groups: int = 0
    block_clone_groups: int = 0
    skip_dependencies: bool = False
    skip_dead_code: bool = False
    memo: dict[str, dict[str, object]] = field(default_factory=dict)


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
