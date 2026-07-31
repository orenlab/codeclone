# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, field_validator

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
ApiParameterKind = Literal["pos_only", "pos_or_kw", "vararg", "kw_only", "kwarg"]
ApiSymbolKind = Literal["function", "class", "method", "constant"]
ApiVisibility = Literal["all", "name"]
ImportSyntaxKind = Literal["import", "from_import"]
DeadCodeCandidateKind = Literal["function", "class", "method", "import"]
# The dead-code lane's extensibility axis, orthogonal to DeadCodeCandidateKind:
# "symbol" asks whether a definition is referenced, "unreachable_statement"
# whether a statement inside a live definition can run (39Y Y9). Extending this
# literal is what the lane's payload_schema "3" already bought — the kind is the
# whole extension point, so a new row type costs no further bump.
DeadCodeObservationKind = Literal["symbol", "unreachable_statement"]
# Why a symbol is held live by a root rule rather than by a plain reference.
# Evidence, not a verdict: it explains an already-live outcome.
LiveRootReason = Literal["external_decorator", "export_root"]
DependencyResolution = Literal[
    "analyzed",
    "known_internal_not_analyzed",
    "external",
    "unresolved_relative",
    "unresolved_dynamic",
    "ambiguous",
]
# How the import edge is expressed in source: a static statement, or a dynamic
# load call captured by the sole dynamic-loading detector.
DependencyMechanism = Literal["static", "dynamic"]
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
GitObjectFormat = Literal["sha1", "sha256"]
CacheContentDecisionReason = Literal[
    "blob_hit",
    "digest_hit",
    "digest_miss",
    "stat_mismatch",
]
GitContentFallbackReason = Literal[
    "dirty",
    "git_unavailable",
    "index_ambiguous",
    "racy",
    "untracked",
]
DigestDomain = Literal[
    "ccmi2:manifest",
    "ccapi1:sig",
    "codeclone.analysis-scope.v1",
    "codeclone.baseline.lane.v1",
    "codeclone.baseline.legacy-evidence.v1",
    "codeclone.baseline.root.v1",
    "codeclone.cache.binding-context.v1",
    "codeclone.cache.profile.dependent.v1",
    "codeclone.cache.profile.neutral.v1",
    "codeclone.module-registry.v1",
    "codeclone.source-observations.v1",
    "codeclone.source-content.v1",
]
ReportDigestKind = Literal[
    "source_observations",
    "analysis_facts",
    "comparison",
    "evaluation",
    "report_envelope",
]
ReportReadFailureKind = Literal[
    "duplicate_key",
    "incompatible_schema",
    "invalid_json",
    "invalid_shape",
    "too_large",
    "unreadable",
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


class GitStatusEntryInput(BaseModel):
    """Strict subprocess-boundary shape for one porcelain status entry."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status_xy: str
    path: str

    @field_validator("status_xy")
    @classmethod
    def _valid_status_xy(cls, value: str) -> str:
        if len(value) != 2:
            raise ValueError("git status_xy must contain exactly two characters")
        return value

    @field_validator("path")
    @classmethod
    def _non_empty_status_path(cls, value: str) -> str:
        if not value:
            raise ValueError("git status path must be non-empty")
        return value


class GitIndexEntryInput(BaseModel):
    """Strict subprocess-boundary shape for one batched index entry."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tag: str
    mode: str
    object_id: str
    stage: int
    path: str
    mtime_ns: int
    size: int
    flags: int

    @field_validator("tag")
    @classmethod
    def _valid_tag(cls, value: str) -> str:
        if len(value) != 1:
            raise ValueError("git index tag must contain exactly one character")
        return value

    @field_validator("path", "mode", "object_id")
    @classmethod
    def _non_empty_index_text(cls, value: str) -> str:
        if not value:
            raise ValueError("git index text fields must be non-empty")
        return value


@dataclass(frozen=True, slots=True, kw_only=True)
class GitStatusEntry:
    status_xy: str
    path: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GitIndexEntry:
    tag: str
    mode: str
    object_id: str
    stage: int
    path: str
    mtime_ns: int
    size: int
    flags: int


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


def derive_python_module_identity(path: str) -> PythonModuleIdentity:
    """Rebuild a module identity from its repository-relative path.

    Sole owner of the derivation rule: everything except the path itself is a
    function of the path, so the wire stores paths and exceptions only.
    """

    stem = path[:-3] if path.endswith(".py") else path
    is_package = path.endswith("/__init__.py")
    if is_package:
        stem = stem[: -len("/__init__")]
    module = stem.replace("/", ".")
    return PythonModuleIdentity(
        module=module,
        package=module if is_package else module.rpartition(".")[0],
        is_package=is_package,
        mount_path=".",
        origin="import_mount",
        node_kind="regular_package" if is_package else "module_file",
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ThinIdentityTable:
    """Sorted paths plus the exceptions the derivation rule cannot produce."""

    paths: tuple[str, ...]
    module_null: tuple[int, ...] = ()
    node_kind_exc: tuple[tuple[int, PythonModuleNodeKind], ...] = ()

    def __post_init__(self) -> None:
        if self.paths != tuple(sorted(set(self.paths))):
            raise ValueError("identity table paths must be sorted and unique")
        if any(path.startswith("/") or not path for path in self.paths):
            raise ValueError("identity table paths must be repository-relative")
        _validate_ascending_indices(self.module_null, len(self.paths), "module_null")
        _validate_ascending_indices(
            tuple(index for index, _kind in self.node_kind_exc),
            len(self.paths),
            "node_kind_exc",
        )
        if set(self.module_null) & {index for index, _kind in self.node_kind_exc}:
            raise ValueError("a null-module identity cannot carry a node kind")

    def identity(self, index: int) -> ResolvedSourceIdentity:
        path = self.paths[index]
        if index in frozenset(self.module_null):
            return ResolvedSourceIdentity(
                file=FileIdentity(path=path), python_module=None
            )
        module = derive_python_module_identity(path)
        for exception_index, kind in self.node_kind_exc:
            if exception_index == index:
                module = replace(
                    module, node_kind=kind, is_package=kind == "regular_package"
                )
                break
        return ResolvedSourceIdentity(
            file=FileIdentity(path=path), python_module=module
        )


def _validate_ascending_indices(
    indices: tuple[int, ...],
    row_count: int,
    label: str,
) -> None:
    if indices != tuple(sorted(set(indices))):
        raise ValueError(f"{label} indices must be strictly ascending and unique")
    if any(index < 0 or index >= row_count for index in indices):
        raise ValueError(f"{label} indices must be inside the row range")


def _validate_sorted_table(values: tuple[str, ...], label: str) -> None:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{label} table must be sorted and duplicate-free")


def _validate_column_references(
    column: tuple[int, ...],
    table_size: int,
    label: str,
) -> None:
    if any(index < 0 or index >= table_size for index in column):
        raise ValueError(f"{label} column references a value outside its table")


def _validate_equal_column_lengths(columns: dict[str, int]) -> int:
    sizes = set(columns.values())
    if len(sizes) != 1:
        raise ValueError(f"columnar lane requires equal column lengths: {columns}")
    return sizes.pop()


def _validate_columnar_frame(
    *,
    tables: Mapping[str, tuple[str, ...]],
    columns: Mapping[str, int],
    references: Mapping[str, tuple[tuple[int, ...], int]],
) -> int:
    """Validate the shape shared by every columnar lane and return the row count."""

    for label, values in tables.items():
        _validate_sorted_table(values, label)
    rows = _validate_equal_column_lengths(dict(columns))
    for label, (column, size) in references.items():
        _validate_column_references(column, size, label)
    return rows


@dataclass(frozen=True, slots=True, kw_only=True)
class AdoptionColumnarPayload:
    """Wire form of the adoption lane (payload schema 2)."""

    scopes: tuple[str, ...]
    features: tuple[str, ...]
    scope: tuple[int, ...]
    feature: tuple[int, ...]
    numerator: tuple[int, ...]
    denominator: tuple[int, ...]

    def __post_init__(self) -> None:
        rows = _validate_columnar_frame(
            tables={"scopes": self.scopes, "features": self.features},
            columns={
                "scope": len(self.scope),
                "feature": len(self.feature),
                "numerator": len(self.numerator),
                "denominator": len(self.denominator),
            },
            references={
                "scope": (self.scope, len(self.scopes)),
                "feature": (self.feature, len(self.features)),
            },
        )
        for row in range(rows):
            if self.denominator[row] <= 0 or self.numerator[row] < 0:
                raise ValueError("adoption counts require non-negative/positive values")
            if self.numerator[row] > self.denominator[row]:
                raise ValueError("adoption numerator cannot exceed denominator")
        order = tuple(
            (self.scopes[self.scope[row]], self.features[self.feature[row]])
            for row in range(rows)
        )
        if order != tuple(sorted(order)):
            raise ValueError("columnar rows must be sorted")


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadCodeMarkerException:
    """One dead-code row whose runtime markers differ from the lane default."""

    row: int
    runtime_marker_count: int
    source_markers: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.runtime_marker_count < 0:
            raise ValueError("dead-code observation counts must be non-negative")
        if self.source_markers != tuple(sorted(set(self.source_markers))):
            raise ValueError("dead-code source markers must be sorted and unique")


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadCodeLiveRootException:
    """One dead-code row held live by a root rule, carrying the reason why.

    Sparse by construction: only a minority of candidates are roots, so the
    reason rides an exception list rather than a mostly-empty column.
    """

    row: int
    reason: LiveRootReason


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadCodeColumnarPayload:
    """Wire form of the dead-code lane (payload schema 3)."""

    prefixes: tuple[str, ...]
    kinds: tuple[str, ...]
    observation_kinds: tuple[str, ...]
    prefix: tuple[int, ...]
    qualname: tuple[str, ...]
    kind: tuple[int, ...]
    observation_kind: tuple[int, ...]
    reference_count: tuple[int, ...]
    reachable_true: tuple[int, ...] = ()
    abstained: tuple[int, ...] = ()
    live_roots: tuple[DeadCodeLiveRootException, ...] = ()
    markers: tuple[DeadCodeMarkerException, ...] = ()

    def __post_init__(self) -> None:
        rows = _validate_columnar_frame(
            tables={
                "prefixes": self.prefixes,
                "kinds": self.kinds,
                "observation_kinds": self.observation_kinds,
            },
            columns={
                "prefix": len(self.prefix),
                "qualname": len(self.qualname),
                "kind": len(self.kind),
                "observation_kind": len(self.observation_kind),
                "reference_count": len(self.reference_count),
            },
            references={
                "prefix": (self.prefix, len(self.prefixes)),
                "kind": (self.kind, len(self.kinds)),
                "observation_kind": (
                    self.observation_kind,
                    len(self.observation_kinds),
                ),
            },
        )
        if any(value < 0 for value in self.reference_count):
            raise ValueError("dead-code observation counts must be non-negative")
        _validate_ascending_indices(self.reachable_true, rows, "reachable_true")
        _validate_ascending_indices(self.abstained, rows, "abstained")
        _validate_ascending_indices(
            tuple(item.row for item in self.live_roots), rows, "live_roots"
        )
        _validate_ascending_indices(
            tuple(item.row for item in self.markers), rows, "markers"
        )
        order = tuple(
            (
                self.prefixes[self.prefix[row]],
                self.qualname[row],
                self.kinds[self.kind[row]],
            )
            for row in range(rows)
        )
        if order != tuple(sorted(order)):
            raise ValueError("columnar rows must be sorted")


@dataclass(frozen=True, slots=True, kw_only=True)
class DigestMeta:
    """The one algorithm/domain pair shared by every digest in a lane."""

    algorithm: Literal["sha256"]
    domain: DigestDomain


@dataclass(frozen=True, slots=True, kw_only=True)
class ApiParameterDef:
    """One unique parameter definition referenced by the parameter-list table."""

    name: str
    kind: ApiParameterKind
    has_default: bool
    annotation_digest: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ApiSurfaceColumnarPayload:
    """Wire form of the api-surface lane (payload schema 2)."""

    identities: ThinIdentityTable
    digests: tuple[str, ...]
    digest_meta: DigestMeta | None
    symbol_kinds: tuple[str, ...]
    visibilities: tuple[str, ...]
    parameter_defs: tuple[ApiParameterDef, ...]
    parameter_lists: tuple[tuple[int, ...], ...]
    owner: tuple[int, ...]
    name: tuple[str, ...]
    symbol_kind: tuple[int, ...]
    visibility: tuple[int, ...]
    returns_digest: tuple[int | None, ...]
    parameters: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.digests and self.digest_meta is None:
            raise ValueError("digest values require their algorithm and domain")
        _validate_sorted_table(self.digests, "digests")
        _validate_sorted_table(self.symbol_kinds, "symbol_kinds")
        _validate_sorted_table(self.visibilities, "visibilities")
        rows = _validate_equal_column_lengths(
            {
                "owner": len(self.owner),
                "name": len(self.name),
                "symbol_kind": len(self.symbol_kind),
                "visibility": len(self.visibility),
                "returns_digest": len(self.returns_digest),
                "parameters": len(self.parameters),
            }
        )
        _validate_column_references(self.owner, len(self.identities.paths), "owner")
        _validate_column_references(
            self.symbol_kind, len(self.symbol_kinds), "symbol_kind"
        )
        _validate_column_references(
            self.visibility, len(self.visibilities), "visibility"
        )
        _validate_column_references(
            self.parameters, len(self.parameter_lists), "parameters"
        )
        _validate_column_references(
            tuple(value for value in self.returns_digest if value is not None),
            len(self.digests),
            "returns_digest",
        )
        definition_keys = tuple(
            (
                item.name,
                item.kind,
                item.has_default,
                -1 if item.annotation_digest is None else item.annotation_digest,
            )
            for item in self.parameter_defs
        )
        if definition_keys != tuple(sorted(set(definition_keys))):
            raise ValueError("parameter_defs table must be sorted and duplicate-free")
        _validate_column_references(
            tuple(
                item.annotation_digest
                for item in self.parameter_defs
                if item.annotation_digest is not None
            ),
            len(self.digests),
            "annotation_digest",
        )
        if self.parameter_lists != tuple(sorted(set(self.parameter_lists))):
            raise ValueError("parameter_lists table must be sorted and duplicate-free")
        for definition_list in self.parameter_lists:
            _validate_column_references(
                definition_list, len(self.parameter_defs), "parameter_lists"
            )
        order = tuple(
            (self.identities.paths[self.owner[row]], self.name[row])
            for row in range(rows)
        )
        if order != tuple(sorted(order)):
            raise ValueError("columnar rows must be sorted")


def _null_first(value: str | None) -> tuple[int, str]:
    """Total order over an optional string: null sorts before any value."""

    return (0, "") if value is None else (1, value)


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyColumnarPayload:
    """Wire form of the dependency lane (payload schema 4)."""

    identities: ThinIdentityTable
    modules: tuple[str, ...]
    resolutions: tuple[str, ...]
    syntax_kinds: tuple[str, ...]
    source: tuple[int, ...]
    requested_module: tuple[int | None, ...]
    requested_names: tuple[tuple[int, ...], ...]
    resolution: tuple[int, ...]
    resolved_target: tuple[int | None, ...]
    syntax_kind: tuple[int, ...]
    level: tuple[int, ...]
    inventory_expansion: tuple[int, ...] = ()
    mechanism_dynamic: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _validate_sorted_table(self.modules, "modules")
        _validate_sorted_table(self.resolutions, "resolutions")
        _validate_sorted_table(self.syntax_kinds, "syntax_kinds")
        rows = _validate_equal_column_lengths(
            {
                "source": len(self.source),
                "requested_module": len(self.requested_module),
                "requested_names": len(self.requested_names),
                "resolution": len(self.resolution),
                "resolved_target": len(self.resolved_target),
                "syntax_kind": len(self.syntax_kind),
                "level": len(self.level),
            }
        )
        _validate_column_references(self.source, len(self.identities.paths), "source")
        _validate_column_references(
            self.resolution, len(self.resolutions), "resolution"
        )
        _validate_column_references(
            self.syntax_kind, len(self.syntax_kinds), "syntax_kind"
        )
        for label, column in (
            ("requested_module", self.requested_module),
            ("resolved_target", self.resolved_target),
        ):
            _validate_column_references(
                tuple(value for value in column if value is not None),
                len(self.modules),
                label,
            )
        for names in self.requested_names:
            _validate_column_references(names, len(self.modules), "requested_names")
        if any(value < 0 for value in self.level):
            raise ValueError("dependency import level must be non-negative")
        _validate_ascending_indices(
            self.inventory_expansion, rows, "inventory_expansion"
        )
        _validate_ascending_indices(self.mechanism_dynamic, rows, "mechanism_dynamic")
        dynamic = frozenset(self.mechanism_dynamic)
        order = tuple(
            (
                self.identities.paths[self.source[row]],
                _null_first(
                    None
                    if (reference := self.requested_module[row]) is None
                    else self.modules[reference]
                ),
                tuple(self.modules[name] for name in self.requested_names[row]),
                self.syntax_kinds[self.syntax_kind[row]],
                "dynamic" if row in dynamic else "static",
                self.level[row],
                self.resolutions[self.resolution[row]],
                _null_first(
                    None
                    if (target := self.resolved_target[row]) is None
                    else self.modules[target]
                ),
                row in frozenset(self.inventory_expansion),
            )
            for row in range(rows)
        )
        if order != tuple(sorted(order)):
            raise ValueError("columnar rows must be sorted")


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleEntryException:
    """One registry entry whose analyzed state differs from the lane default."""

    row: int
    analyzed: bool
    internality: ModuleInternality


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleIdentityColumnarPayload:
    """Wire form of the module-identity lane (payload schema 3)."""

    identities: ThinIdentityTable
    manifest: ModuleIdentityManifest
    manifest_digest: DigestObject
    registry_digest: DigestObject
    package_prefixes: tuple[PackagePrefix, ...]
    other: tuple[ModuleEntryException, ...] = ()

    def __post_init__(self) -> None:
        _validate_ascending_indices(
            tuple(item.row for item in self.other), len(self.identities.paths), "other"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class IntegerColumnarPayload:
    """Wire form of the two integer observation lanes (payload schema 3)."""

    identities: ThinIdentityTable
    qualnames: tuple[str, ...]
    dimensions: tuple[str, ...]
    identity: tuple[int, ...]
    qualname: tuple[int, ...]
    dimension: tuple[int, ...]
    numerator: tuple[int, ...]
    entity_population: int

    def __post_init__(self) -> None:
        rows = _validate_columnar_frame(
            tables={"qualnames": self.qualnames, "dimensions": self.dimensions},
            columns={
                "identity": len(self.identity),
                "qualname": len(self.qualname),
                "dimension": len(self.dimension),
                "numerator": len(self.numerator),
            },
            references={
                "identity": (self.identity, len(self.identities.paths)),
                "qualname": (self.qualname, len(self.qualnames)),
                "dimension": (self.dimension, len(self.dimensions)),
            },
        )
        if any(value < 0 for value in self.numerator):
            raise ValueError("observation numerators must be non-negative")
        if self.entity_population < 0:
            raise ValueError("observation entity population must be non-negative")
        order = tuple(
            (
                self.identities.paths[self.identity[row]],
                self.qualnames[self.qualname[row]],
                self.dimensions[self.dimension[row]],
            )
            for row in range(rows)
        )
        if order != tuple(sorted(order)):
            raise ValueError("columnar rows must be sorted")
        counts: dict[int, int] = {}
        for index in self.dimension:
            counts[index] = counts.get(index, 0) + 1
        if any(count > self.entity_population for count in counts.values()):
            raise ValueError(
                "observation rows per dimension cannot exceed the entity population"
            )


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
    domain: DigestDomain
    algorithm: Literal["sha256"]
    value: str

    def __post_init__(self) -> None:
        if len(self.value) != 64 or any(
            character not in "0123456789abcdef" for character in self.value
        ):
            raise ValueError("sha256 digest values must be 64 lowercase hex characters")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportDigest:
    kind: ReportDigestKind
    algorithm: Literal["sha256"]
    digest_version: Literal["1"]
    value: str

    def __post_init__(self) -> None:
        if len(self.value) != 64 or any(
            character not in "0123456789abcdef" for character in self.value
        ):
            raise ValueError("report digest values must be 64 lowercase hex characters")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportReadSuccess:
    document: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportReadFailure:
    reason: ReportReadFailureKind
    detail: str


ReportReadResult = ReportReadSuccess | ReportReadFailure


@dataclass(frozen=True, slots=True, kw_only=True)
class GitBlobIdentity:
    object_format: GitObjectFormat
    object_id: str

    def __post_init__(self) -> None:
        expected_length = 40 if self.object_format == "sha1" else 64
        if len(self.object_id) != expected_length or any(
            character not in "0123456789abcdef" for character in self.object_id
        ):
            raise ValueError("git object id does not match its declared format")


class FileStat(TypedDict):
    mtime_ns: int
    size: int


class SourceStatsDict(TypedDict):
    lines: int
    functions: int
    methods: int
    classes: int


class RelationshipRecordDict(TypedDict):
    relation_kind: str
    resolution_status: str
    origin_lane: str
    source_qualname: str
    target_qualname: str | None
    path: str
    line: int
    expression: str | None
    resolution_rule: str | None


class FunctionRelationshipFactsDict(TypedDict):
    source_qualname: str
    relationships: list[RelationshipRecordDict]


class ClassMetricsDictBase(TypedDict):
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    cbo: int
    lcom4: int
    method_count: int
    instance_var_count: int
    risk_coupling: str
    risk_cohesion: str


class ClassMetricsDict(ClassMetricsDictBase, total=False):
    coupled_classes: list[str]
    # CACHE_VERSION 3.2 imported-domain call candidates, each packed as
    # `label|module:symbol`. Optional for the same reason as the rows below.
    instantiation_candidates: list[str]
    # CACHE_VERSION 3.2 rule-3 facts. Optional: a 3.1 row decodes to the
    # dataclass defaults, which is exactly "no evidence recorded".
    base_names: list[str]
    has_unresolved_external_base: bool
    decorator_evidenced_methods: list[str]
    self_dispatched_methods: list[str]


class ModuleDepDictBase(TypedDict):
    source: str
    target: str
    import_type: Literal["import", "from_import"]
    line: int


class ModuleDepDict(ModuleDepDictBase, total=False):
    resolution: DependencyResolution
    mechanism: DependencyMechanism
    inventory_expansion: bool
    level: int
    requested_module: str | None
    requested_names: list[str]
    candidate_targets: list[str]


class DeadCandidateDictBase(TypedDict):
    qualname: str
    local_name: str
    filepath: str
    start_line: int
    end_line: int
    kind: str


class DeadCandidateDict(DeadCandidateDictBase, total=False):
    suppressed_rules: list[str]
    # CACHE_VERSION 3.2 liveness-reason fact. Optional: a row written without
    # it decodes to None, which is exactly "no root rule fired".
    live_root_reason: str


class SecuritySurfaceDict(TypedDict):
    category: str
    capability: str
    module: str
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    location_scope: str
    classification_mode: str
    evidence_kind: str
    evidence_symbol: str


class RuntimeReachabilityFactDict(TypedDict):
    target_qualname: str
    filepath: str
    start_line: int
    end_line: int
    target_kind: str
    framework: str
    edge_kind: str
    confidence: str
    evidence: str
    evidence_symbol: str
    source_qualname: str


class ModuleTypingCoverageDict(TypedDict):
    module: str
    filepath: str
    callable_count: int
    params_total: int
    params_annotated: int
    returns_total: int
    returns_annotated: int
    any_annotation_count: int


class ModuleDocstringCoverageDict(TypedDict):
    module: str
    filepath: str
    public_symbol_total: int
    public_symbol_documented: int


class ApiParamSpecDict(TypedDict):
    name: str
    kind: str
    has_default: bool
    annotation_hash: str


class PublicSymbolDict(TypedDict):
    qualname: str
    kind: str
    start_line: int
    end_line: int
    params: list[ApiParamSpecDict]
    returns_hash: str
    exported_via: str


class ModuleApiSurfaceDict(TypedDict):
    module: str
    filepath: str
    all_declared: list[str]
    symbols: list[PublicSymbolDict]


class StructuralFindingOccurrenceDict(TypedDict):
    qualname: str
    start: int
    end: int


class StructuralFindingGroupDict(TypedDict):
    finding_kind: str
    finding_key: str
    signature: dict[str, str]
    items: list[StructuralFindingOccurrenceDict]


CacheLaneReuseReason = Literal[
    "binding_context_mismatch",
    "content_miss",
    "dependent_profile_mismatch",
    "hit",
    "malformed_payload",
    "neutral_profile_mismatch",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheNeutralUnit:
    local_name: str
    start_line: int
    end_line: int
    loc: int
    stmt_count: int
    fingerprint: str
    loc_bucket: str
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
    statement_sequence: tuple[NearMissElement, ...] = ()
    unreachable_statements: tuple[UnreachableStatementItem, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheNeutralBlock:
    local_name: str
    start_line: int
    end_line: int
    size: int
    block_hash: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheNeutralSegment:
    local_name: str
    start_line: int
    end_line: int
    size: int
    segment_hash: str
    segment_sig: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheNeutralPayload:
    source_stats: SourceStatsDict
    units: tuple[CacheNeutralUnit, ...]
    blocks: tuple[CacheNeutralBlock, ...]
    segments: tuple[CacheNeutralSegment, ...]
    semantic_facts: SemanticFileFacts


@dataclass(frozen=True, slots=True, kw_only=True)
class RehydratedCacheNeutral:
    source_stats: SourceStats
    units: tuple[Unit, ...]
    blocks: tuple[BlockUnit, ...]
    segments: tuple[SegmentUnit, ...]
    semantic_facts: SemanticFileFacts


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheDependentPayload:
    class_metrics: tuple[ClassMetricsDict, ...]
    module_deps: tuple[ModuleDepDict, ...]
    dead_candidates: tuple[DeadCandidateDict, ...]
    referenced_names: tuple[str, ...]
    referenced_qualnames: tuple[str, ...]
    import_names: tuple[str, ...]
    class_names: tuple[str, ...]
    runtime_reachability: tuple[RuntimeReachabilityFactDict, ...]
    security_surfaces: tuple[SecuritySurfaceDict, ...]
    function_relationship_facts: tuple[FunctionRelationshipFactsDict, ...]
    typing_coverage: ModuleTypingCoverageDict | None
    docstring_coverage: ModuleDocstringCoverageDict | None
    api_surface: ModuleApiSurfaceDict | None
    structural_findings: tuple[StructuralFindingGroupDict, ...] | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheEntryV3:
    cache_content_binding_version: Literal["1"]
    stat: FileStat
    source_content_digest: DigestObject
    # The one fingerprint input that does NOT live in this file's bytes: where
    # its relative imports point, which follows the module's package position.
    # Content identity cannot see that move, so it rides the key on its own.
    binding_context_digest: DigestObject
    git_blob_id_at_write: GitBlobIdentity | None
    module_neutral_profile: DigestObject
    module_dependent_profile: DigestObject
    module_neutral: CacheNeutralPayload
    module_dependent: CacheDependentPayload


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheLaneVerdict:
    hit: bool
    reason: CacheLaneReuseReason


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheReuseDecision:
    neutral: CacheLaneVerdict
    dependent: CacheLaneVerdict


@dataclass(frozen=True, slots=True, kw_only=True)
class GitTrackedContent:
    path: str
    blob: GitBlobIdentity
    source_content_digest: DigestObject


@dataclass(frozen=True, slots=True, kw_only=True)
class GitDirtyEntry:
    path: str
    status_xy: str
    digest: str | None
    digest_status: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GitWorkspaceSnapshot:
    git_available: bool
    entries: tuple[GitDirtyEntry, ...]

    def __post_init__(self) -> None:
        paths = tuple(entry.path for entry in self.entries)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("git workspace snapshot paths must be sorted and unique")


@dataclass(frozen=True, slots=True, kw_only=True)
class GitContentSnapshot:
    root: str
    git_available: bool
    object_format: GitObjectFormat | None
    tracked: tuple[GitTrackedContent, ...]
    dirty_paths: frozenset[str]
    untracked_paths: frozenset[str]
    index_ambiguous_paths: frozenset[str]
    racy_paths: frozenset[str]

    def __post_init__(self) -> None:
        paths = tuple(item.path for item in self.tracked)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("git tracked content paths must be sorted and unique")
        if not self.git_available and self.object_format is not None:
            raise ValueError("unavailable git snapshot cannot declare an object format")

    def repository_path(self, path: str | Path) -> str | None:
        candidate = Path(path)
        if not candidate.is_absolute():
            return candidate.as_posix()
        try:
            return candidate.resolve().relative_to(Path(self.root).resolve()).as_posix()
        except (OSError, ValueError):
            return None

    def tracked_content(self, path: str | Path) -> GitTrackedContent | None:
        repository_path = self.repository_path(path)
        if repository_path is None:
            return None
        low = 0
        high = len(self.tracked)
        while low < high:
            middle = (low + high) // 2
            item = self.tracked[middle]
            if item.path < repository_path:
                low = middle + 1
            elif item.path > repository_path:
                high = middle
            else:
                return item
        return None

    def fallback_reason(
        self,
        path: str | Path,
    ) -> GitContentFallbackReason | None:
        if not self.git_available:
            return "git_unavailable"
        repository_path = self.repository_path(path)
        if repository_path is None:
            return "index_ambiguous"
        if repository_path in self.untracked_paths:
            return "untracked"
        if repository_path in self.dirty_paths:
            return "dirty"
        if repository_path in self.racy_paths:
            return "racy"
        if (
            repository_path in self.index_ambiguous_paths
            or self.tracked_content(repository_path) is None
        ):
            return "index_ambiguous"
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentIdentityVerdict:
    hit: bool
    reason: CacheContentDecisionReason
    git_fallback_reason: GitContentFallbackReason | None
    digest_verify_cost_us: int
    stat_fast_reject: bool


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
    manifest_digest: DigestObject
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


# One element of a unit's normalized statement sequence: an equality token
# plus the source span it came from. Control-flow anchors carry lines 0, 0.
# Produced by ``analysis.fingerprint.near_miss_statement_sequence``; consumed
# only by the near-miss clone tier (39Y Y8).
NearMissElement = tuple[str, int, int]


# Which clause of STATEMENT_REACHABILITY_POLICY_VERSION proved the region dead
# (39Y Y9). The reason is the CFG proof, not a label: a consumer can say why a
# statement cannot run without re-deriving anything.
UnreachableReason = Literal[
    "after_terminator",
    "literal_condition",
    "unreachable_block",
]

# Why the CFG builder created a block, carried for explanation only (39Y Y9).
# Reachability comes from traversal and complexity from the edge/node/component
# counts; neither may branch on this. It exists so a finding can name a cause a
# reader recognises instead of restating the bare graph fact, and it has exactly
# the standing of an edge kind tag: evidence, never a filter.
BlockOrigin = Literal[
    "normal",
    "after_terminator",
    "literal_condition",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class UnreachableStatementItem:
    """One maximal region of statements that cannot execute.

    A region, not a statement: reporting every statement of a long dead tail
    would multiply one defect into many findings. ``statement_count`` keeps the
    size honest without spending a finding per line.

    Spans are always real source positions. The CFG synthesizes ``ast.Expr``
    wrappers that carry no ``lineno``, so a region with no positioned statement
    is dropped rather than reported at line 0 (the Y8 precedent) — nothing here
    ever invents a position.
    """

    reason: UnreachableReason
    start_line: int
    end_line: int
    statement_count: int

    def __post_init__(self) -> None:
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError(
                "unreachable regions carry a real source span, never a fabricated one"
            )
        if self.statement_count < 1:
            raise ValueError("an unreachable region covers at least one statement")


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
    # Empty for units the clone floors reject: the near-miss tier is a clone
    # lane, so ineligible units neither carry nor cache a sequence.
    statement_sequence: tuple[NearMissElement, ...] = ()
    # Populated for EVERY unit, eligible or not: reachability is a fact about
    # the function, and letting a clone floor decide what it sees would repeat
    # the eligibility leak Y5 removed.
    unreachable_statements: tuple[UnreachableStatementItem, ...] = ()


@dataclass(frozen=True, slots=True)
class NearMissMember:
    """One side of a near-miss pair, with its own differing-statement span.

    A span of ``0, 0`` means "no source position", which arises two ways and is
    disambiguated by the pair's ``edit_kind``:

    - ``insert`` / ``delete``: this side has no differing statement at all —
      the counterpart carries a statement this side simply does not have;
    - ``replace``: the differing element is a control-flow condition the CFG
      builder synthesizes, and a synthesized node carries no ``lineno``. The
      difference is real and drives the match; only its position is unknown,
      and inventing one from a neighbouring line would be a fabricated
      location.
    """

    qualname: str
    filepath: str
    start_line: int
    end_line: int
    differing_start_line: int = 0
    differing_end_line: int = 0


@dataclass(frozen=True, slots=True)
class NearMissPair:
    """Two units within ``NEAR_MISS_MAX_EDIT_STATEMENTS`` of each other.

    Pairwise by construction, never a connected component: the tier's evidence
    is the statement that differs between exactly two functions, and edit
    distance is not transitive. Three functions each one statement apart from
    the next produce two pairs, not one group of three.
    """

    pair_key: str
    members: tuple[NearMissMember, NearMissMember]
    edit_statements: int
    edit_kind: Literal["insert", "delete", "replace"]


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
    # Names referenced in a type-collaboration position (annotation). The
    # imported-domain CBO lane counts only these; see the edge contract in
    # codeclone/metrics/coupling.py.
    typed_couplings: frozenset[str]
    # Imported call targets, each packed as `label|module:symbol`. A call
    # position does not entail a type, so these are candidates rather than
    # edges: only the project-level fold can tell whether the target is a
    # class.
    instantiation_candidates: frozenset[str]
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
    # Imported call targets seen in this class body, packed as
    # `label|module:symbol`. They are inputs to the project-level coupling
    # fold, never edges on their own: nothing at file scope can prove that an
    # imported callable is a class.
    instantiation_candidates: tuple[str, ...] = ()
    # Rule-3 liveness facts. They live here rather than in dedicated fact
    # types because the class is already the natural subject of both, and
    # ClassMetrics already travels every road they need (walk -> cache wire
    # -> MetricProjectContext). Primitive fields add no type edge, so the
    # carriers that hold ClassMetrics keep their coupling budget.
    base_names: tuple[str, ...] = ()
    # True when a declared base escapes the analysis root. The set of methods
    # such a base may dispatch to is unknowable, so an unevidenced public
    # method abstains (unresolved_external_override) instead of being claimed
    # dead.
    has_unresolved_external_base: bool = False
    # Fully-qualified methods of THIS class carrying an explicit dispatch
    # contract (@override, framework hooks) - row 2 of the decision table.
    decorator_evidenced_methods: tuple[str, ...] = ()
    # Fully-qualified methods of THIS class invoked as `self.<name>()` from
    # inside the class body - row 1 of the decision table. `self` can only
    # bind an instance of the declaring class or a subclass, so the receiver
    # type is proven and the call is method-specific evidence, never a
    # bare-name match.
    self_dispatched_methods: tuple[str, ...] = ()


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
    mechanism: DependencyMechanism = "static"


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportObservation:
    source: ResolvedSourceIdentity
    syntax_kind: ImportSyntaxKind
    level: int
    requested_module: str | None
    requested_names: tuple[str, ...]
    resolution: DependencyResolution
    candidate_targets: tuple[str, ...]
    resolved_target: str | None
    inventory_expansion: bool = False
    mechanism: DependencyMechanism = "static"

    def __post_init__(self) -> None:
        if self.candidate_targets != tuple(sorted(set(self.candidate_targets))):
            raise ValueError("import candidate targets must be sorted and unique")
        # Two resolutions legitimately name non-resolution: a relative import
        # that escapes its package, and a dynamic load whose argument is opaque.
        if self.resolution in {"unresolved_relative", "unresolved_dynamic"}:
            if self.resolved_target is not None:
                raise ValueError("unresolved imports cannot have a target")
            if self.candidate_targets:
                raise ValueError("unresolved imports cannot have candidate targets")
        elif not self.resolved_target:
            raise ValueError("resolved import observations require a target")
        if self.resolution == "unresolved_dynamic" and self.mechanism != "dynamic":
            raise ValueError("only a dynamic load can be unresolved_dynamic")


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
    reason: Literal["unreferenced", "test_only_reference"] = "unreferenced"
    test_reference_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.test_reference_sources != tuple(
            sorted(set(self.test_reference_sources))
        ):
            raise ValueError(
                "dead-code test reference sources must be sorted and unique"
            )
        if self.reason == "test_only_reference" and not self.test_reference_sources:
            raise ValueError("test-only dead code requires test reference sources")
        if self.reason == "unreferenced" and self.test_reference_sources:
            raise ValueError(
                "unreferenced dead code cannot have test reference sources"
            )


@dataclass(frozen=True, slots=True)
class DeadCandidate:
    qualname: str
    local_name: str
    filepath: str
    start_line: int
    end_line: int
    kind: Literal["function", "class", "method", "import"]
    suppressed_rules: tuple[str, ...] = field(default_factory=tuple)
    # Set when a root rule proved this symbol live during the module walk.
    # The candidate is the carrier because it is the one per-symbol fact that
    # already rides the cache wire, which keeps the reason warm-safe.
    live_root_reason: LiveRootReason | None = None


@dataclass(frozen=True, slots=True)
class UnresolvedOverrideItem:
    """A method the analysis refuses to call dead OR live.

    Its owning class inherits a base outside the analysis root, and no
    receiver-type-proven reference, decorator contract, or runtime edge names
    this method. Absence of evidence is not evidence of absence, so the
    verdict abstains. Excluded from default dead-code gates by contract.
    """

    qualname: str
    filepath: str
    start_line: int
    end_line: int
    kind: Literal["function", "class", "method", "import"]
    class_qualname: str
    base_names: tuple[str, ...]
    reason: Literal["unresolved_external_base"] = "unresolved_external_base"


@dataclass(frozen=True, slots=True)
class UnreachableStatementFinding:
    """One unreachable region, located in the repository (39Y Y9).

    The per-unit ``UnreachableStatementItem`` says what the CFG proved; this
    says where. Confidence is always high and never downgraded: the proof is
    graph reachability over the function's own control flow, so there is no
    uncertain case to express — a region either cannot be entered or is not
    reported at all.
    """

    qualname: str
    filepath: str
    reason: UnreachableReason
    start_line: int
    end_line: int
    statement_count: int


@dataclass(frozen=True, slots=True)
class LivenessClassification:
    """Both lanes of the rule-3 tri-state verdict.

    ``dead_items`` keeps exactly the pre-rule-3 meaning so every existing gate
    and report consumer is unaffected; abstentions live in their own lane.
    """

    dead_items: tuple[DeadItem, ...]
    unresolved_overrides: tuple[UnresolvedOverrideItem, ...] = ()


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


LivenessStatus = Literal["live", "dead", "unresolved_external_override"]

# Decorator markers that count as an explicit callback contract under the
# rule-3 decision table. Name-only call matching is forbidden as evidence;
# these are declarations on the method itself, not references to it.
#
# `abstractmethod` is deliberately absent: an abstract method never reaches
# rule 3, because the module walk already drops it as a non-runtime candidate
# (_NON_RUNTIME_DECORATOR_SYMBOLS). Listing it here was unreachable weight that
# made the row-2 branch read as if it were exercised.
METHOD_DECORATOR_EVIDENCE_MARKERS: Final = frozenset(
    {
        "override",
        "overrides",
    }
)


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

EventKind = Literal[
    "artifact_write",
    "assign",
    "compatibility_check",
    "compute_digest",
    "construct",
    "field_write",
    "publish_event",
    "resolve_identity",
    "return_value",
    "serialize_field",
    "security_observation",
]
FactRefKind = Literal["param", "event", "const", "unresolved"]
SemanticEventResolution = Literal["resolved", "unavailable"]


@dataclass(frozen=True, slots=True, kw_only=True)
class FactRef:
    kind: FactRefKind
    ref: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DynamicLoadArgument:
    """What the detector could read from a dynamic-load call argument.

    An AST constant string yields the requested module; anything else stays
    honestly opaque. There is nothing in between.
    """

    module: str | None

    def __post_init__(self) -> None:
        if self.module is not None and not self.module:
            raise ValueError("a resolved dynamic-load argument cannot be empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticEvent:
    event_id: str
    kind: EventKind
    subject: str
    inputs: tuple[FactRef, ...]
    output: FactRef | None
    guards: tuple[str, ...]
    location: tuple[str, int]
    resolution: SemanticEventResolution
    dynamic_load: DynamicLoadArgument | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FunctionContractSummary:
    function: str
    events: tuple[SemanticEvent, ...]
    param_flows: tuple[tuple[str, str], ...]
    returns: tuple[FactRef, ...]
    unresolved_flow: bool


ContractIROperationKind = Literal["canonical_operation", "pure_builtin"]
ContractIRTransformationRole = Literal[
    "call",
    "compatibility_check",
    "compute_digest",
    "construct",
    "resolve_identity",
]
ContractIRSideEffectKind = Literal[
    "artifact_write",
    "field_write",
    "publish_event",
    "security_observation",
    "serialize_field",
]
ContractIRFailureKind = Literal["unresolved_call", "unresolved_flow"]
PureBuiltinOperation = Literal[
    "abs",
    "all",
    "any",
    "bool",
    "bytes",
    "dict",
    "enumerate",
    "float",
    "frozenset",
    "int",
    "len",
    "list",
    "max",
    "min",
    "range",
    "reversed",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
]
PURE_BUILTIN_OPERATIONS: Final[tuple[PureBuiltinOperation, ...]] = (
    "abs",
    "all",
    "any",
    "bool",
    "bytes",
    "dict",
    "enumerate",
    "float",
    "frozenset",
    "int",
    "len",
    "list",
    "max",
    "min",
    "range",
    "reversed",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContractIRTransformation:
    role: ContractIRTransformationRole
    operation_kind: ContractIROperationKind
    operation: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    guards: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ContractIRSideEffect:
    kind: ContractIRSideEffectKind
    operation: str
    inputs: tuple[str, ...]
    guards: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ContractIRFailureState:
    kind: ContractIRFailureKind


@dataclass(frozen=True, slots=True, kw_only=True)
class ContractIRDocument:
    inputs: tuple[str, ...]
    guards: tuple[str, ...]
    transformations: tuple[ContractIRTransformation, ...]
    dependencies: tuple[str, ...]
    output_facts: tuple[str, ...]
    side_effects: tuple[ContractIRSideEffect, ...]
    failure_states: tuple[ContractIRFailureState, ...]
    unresolved: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class FunctionContractIR:
    function: str
    document: ContractIRDocument
    wire: str
    effect_signature: str
    provenance_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.effect_signature) != 64 or any(
            character not in "0123456789abcdef" for character in self.effect_signature
        ):
            raise ValueError(
                "contract IR effect signatures must be 64 lowercase hex characters"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ContractIRBuildResult:
    contracts: tuple[FunctionContractIR, ...]
    sccs: tuple[tuple[str, ...], ...]
    fixpoint_iterations: int


AuthorityStatus = Literal[
    "authoritative",
    "adapter",
    "shadow",
    "mixed",
    "unavailable",
]
AuthorityCandidateLevel = Literal[
    "exact_contract_ir",
    "same_effect_signature",
    "same_output_fact_and_input_family",
    "overlapping_transform_chain",
    "divergent_projection",
]
AuthorityResolutionState = Literal["resolved", "unavailable"]
AuthorityViolationKind = Literal[
    "multiple_independent_producers",
    "shadow_projection",
    "owner_bypass",
    "reconstructed_contract",
    "divergent_failure_semantics",
    "divergent_canonicalization",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityGraphNode:
    function: str
    effect_signature: str
    producer_root_ids: tuple[str, ...]
    output_facts: tuple[str, ...]
    resolution_state: AuthorityResolutionState


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityGraphEdge:
    source: str
    target: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityGraph:
    nodes: tuple[AuthorityGraphNode, ...]
    edges: tuple[AuthorityGraphEdge, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthoritySinkResult:
    sink_identity: str
    authority_status: AuthorityStatus
    producer_root_ids: tuple[str, ...]
    effect_signature: str
    resolution_state: AuthorityResolutionState


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityCandidate:
    candidate_id: str
    level: AuthorityCandidateLevel
    score: int
    producers: tuple[str, ...]
    shared_fact: str
    independence: bool
    semantic_divergence: bool
    sink_statuses: tuple[AuthorityStatus, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityRegistryEntry:
    contract_id: str
    canonical_owner: str
    allowed_adapters: tuple[str, ...]
    forbidden_raw_inputs: tuple[str, ...]
    required_provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityRegistry:
    version: str
    entries: tuple[AuthorityRegistryEntry, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityGovernedSink:
    contract_id: str
    sink_identity: str
    authority_status: AuthorityStatus
    producer_root_ids: tuple[str, ...]
    effect_signature: str
    resolution_state: AuthorityResolutionState


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityViolationLocation:
    relative_path: str
    start_line: int
    end_line: int
    qualname: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityViolation:
    violation_id: str
    contract_id: str
    kind: AuthorityViolationKind
    sink_identity: str
    canonical_owner: str
    authority_status: AuthorityStatus
    producer_root_ids: tuple[str, ...]
    effect_signature: str
    resolution_state: AuthorityResolutionState
    producers: tuple[str, ...]
    suppressed: bool
    locations: tuple[AuthorityViolationLocation, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticAuthorityResult:
    algorithm_revision: str
    contract_ir: ContractIRBuildResult
    graph: AuthorityGraph
    sinks: tuple[AuthoritySinkResult, ...]
    candidates: tuple[AuthorityCandidate, ...]
    registry: AuthorityRegistry | None = None
    governed_sinks: tuple[AuthorityGovernedSink, ...] = ()
    violations: tuple[AuthorityViolation, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticFileFacts:
    events: tuple[SemanticEvent, ...] = ()
    function_contract_summaries: tuple[FunctionContractSummary, ...] = ()


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
    semantic_facts: SemanticFileFacts = field(default_factory=SemanticFileFacts)
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
    # Rule-3 abstentions. A separate lane from dead_code by contract: they are
    # neither dead nor live, and default gates must never count them.
    unresolved_overrides: tuple[UnresolvedOverrideItem, ...] = ()
    # Statement-level unreachability (39Y Y9). Same family, different question:
    # dead_code asks whether a symbol is called, this asks whether a statement
    # inside a live symbol can run, so the two are never summed.
    unreachable_statements: tuple[UnreachableStatementFinding, ...] = ()
    live_root_reasons: tuple[tuple[str, LiveRootReason], ...] = ()
    api_surface: ApiSurfaceSnapshot | None = None
    semantic_authority: SemanticAuthorityResult | None = None


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


ObservationLaneName = Literal[
    "adoption_counts",
    "api_surface",
    "clones.blocks",
    "clones.functions",
    "coupling_cohesion_observations",
    "dead_code",
    "dependencies",
    "module_identity",
    "risk_observations",
    "semantic_authority",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservationLaneDescriptor:
    name: ObservationLaneName
    descriptor_version: str
    payload_schema: str
    algorithm_revision: str
    canonicalization_version: str
    required_contracts: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        keys = tuple(key for key, _value in self.required_contracts)
        if self.required_contracts != tuple(sorted(self.required_contracts)):
            raise ValueError("lane required contracts must be sorted")
        if len(keys) != len(set(keys)):
            raise ValueError("lane required contracts must be unique")
        versions = (
            self.descriptor_version,
            self.payload_schema,
            self.algorithm_revision,
            self.canonicalization_version,
        )
        if any(not value for value in versions):
            raise ValueError("lane descriptor versions must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservationContract:
    observation_digest_version: str
    enabled_lanes: tuple[ObservationLaneName, ...]
    descriptors: tuple[ObservationLaneDescriptor, ...]

    def __post_init__(self) -> None:
        if not self.observation_digest_version:
            raise ValueError("observation digest version must be non-empty")
        if self.enabled_lanes != tuple(sorted(set(self.enabled_lanes))):
            raise ValueError("enabled observation lanes must be sorted and unique")
        descriptor_names = tuple(descriptor.name for descriptor in self.descriptors)
        if descriptor_names != self.enabled_lanes:
            raise ValueError("lane descriptors must exactly match enabled lanes")
        if "module_identity" not in self.enabled_lanes:
            raise ValueError("module_identity is required for native observations")


@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationContract:
    health_algorithm_revision: str
    gate_algorithm_revision: str
    gate_thresholds_digest: str
    gate_lane_matrix_version: str
    health_input_manifest_version: str
    health_input_lanes: tuple[ObservationLaneName, ...]
    active_gate_lane_requirements: tuple[
        tuple[str, tuple[ObservationLaneName, ...]], ...
    ]

    def __post_init__(self) -> None:
        if not self.health_algorithm_revision or not self.gate_algorithm_revision:
            raise ValueError("evaluation algorithm revisions must be non-empty")
        if not self.gate_lane_matrix_version or not self.health_input_manifest_version:
            raise ValueError("evaluation matrix versions must be non-empty")
        if self.health_input_lanes != tuple(sorted(set(self.health_input_lanes))):
            raise ValueError("health input lanes must be sorted and unique")
        gate_names = tuple(name for name, _lanes in self.active_gate_lane_requirements)
        if gate_names != tuple(sorted(set(gate_names))):
            raise ValueError("active gate requirements must be sorted and unique")
        if any(
            lanes != tuple(sorted(set(lanes)))
            for _name, lanes in self.active_gate_lane_requirements
        ):
            raise ValueError("active gate lanes must be sorted and unique")
        if len(self.gate_thresholds_digest) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.gate_thresholds_digest
        ):
            raise ValueError(
                "gate threshold digests must be 64 lowercase hex characters"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ApiParameterObservation:
    name: str
    kind: ApiParameterKind
    has_default: bool
    annotation_digest: DigestObject | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ApiSymbolObservation:
    owner: ResolvedSourceIdentity
    symbol: str
    symbol_kind: ApiSymbolKind
    visibility: ApiVisibility
    parameters: tuple[ApiParameterObservation, ...]
    returns_digest: DigestObject | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadCodeObservation:
    entity: str
    candidate_kind: DeadCodeCandidateKind
    reference_count: int
    reachable: bool
    runtime_marker_count: int
    source_markers: tuple[tuple[str, str], ...] = ()
    observation_kind: DeadCodeObservationKind = "symbol"
    live_root_reason: LiveRootReason | None = None
    # Rule-3 tri-state: the owning class inherits an unresolved external base
    # and nothing proves this method is called, so the lane records the
    # abstention rather than claiming either verdict.
    abstained: bool = False

    def __post_init__(self) -> None:
        if self.reference_count < 0 or self.runtime_marker_count < 0:
            raise ValueError("dead-code observation counts must be non-negative")
        if self.source_markers != tuple(sorted(set(self.source_markers))):
            raise ValueError("dead-code source markers must be sorted and unique")
        if self.abstained and self.live_root_reason is not None:
            raise ValueError(
                "an abstained dead-code observation cannot also carry a live root"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class IntegerObservation:
    source: ResolvedSourceIdentity
    qualname: str
    dimension: str
    numerator: int

    def __post_init__(self) -> None:
        if self.numerator < 0:
            raise ValueError("observation numerators must be non-negative")
        path = self.source.file.path
        if not path or path.startswith("/"):
            raise ValueError("observation source paths must be repository-relative")
        if not self.qualname:
            raise ValueError("observation qualnames must be non-empty")
        if ":" in self.qualname:
            raise ValueError("observation qualnames must not be glued identities")


@dataclass(frozen=True, slots=True, kw_only=True)
class AdoptionCount:
    scope: str
    feature: str
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.numerator < 0 or self.denominator <= 0:
            raise ValueError("adoption counts require non-negative/positive values")
        if self.numerator > self.denominator:
            raise ValueError("adoption numerator cannot exceed denominator")


def _is_hex64(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_fp_v2_function_clone_id(value: str) -> bool:
    fingerprint, separator, loc_bucket = value.partition("|")
    if not separator or not _is_hex64(fingerprint):
        return False
    if loc_bucket.endswith("+"):
        return loc_bucket[:-1].isdecimal() and loc_bucket[:-1].isascii()
    start, separator, end = loc_bucket.partition("-")
    return bool(
        separator
        and start.isdecimal()
        and start.isascii()
        and end.isdecimal()
        and end.isascii()
    )


def _is_fp_v2_block_clone_id(value: str) -> bool:
    parts = value.split("|")
    return len(parts) == 4 and all(_is_hex64(part) for part in parts)


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuralObservationFacts:
    function_clone_keys: tuple[str, ...]
    block_clone_keys: tuple[str, ...]
    dependencies: tuple[ImportObservation, ...]
    api_surface: tuple[ApiSymbolObservation, ...]
    dead_code: tuple[DeadCodeObservation, ...]
    risk_observations: tuple[IntegerObservation, ...]
    risk_entity_population: int
    adoption_counts: tuple[AdoptionCount, ...]
    coupling_cohesion_observations: tuple[IntegerObservation, ...]
    coupling_cohesion_entity_population: int

    def __post_init__(self) -> None:
        if (
            self.risk_entity_population < 0
            or self.coupling_cohesion_entity_population < 0
        ):
            raise ValueError("observation entity populations must be non-negative")
        for keys in (self.function_clone_keys, self.block_clone_keys):
            if keys != tuple(sorted(set(keys))):
                raise ValueError("clone observation keys must be sorted and unique")
        if any(
            not _is_fp_v2_function_clone_id(value) for value in self.function_clone_keys
        ):
            raise ValueError(
                "function clone observation keys must be canonical fp-v2 IDs"
            )
        if any(not _is_fp_v2_block_clone_id(value) for value in self.block_clone_keys):
            raise ValueError("block clone observation keys must be canonical fp-v2 IDs")


@dataclass(frozen=True, slots=True, kw_only=True)
class CloneObservationPayload:
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleIdentityObservationPayload:
    manifest: ModuleIdentityManifest
    manifest_digest: DigestObject
    module_registry: tuple[ModuleInventoryEntry, ...]
    package_prefixes: tuple[PackagePrefix, ...]
    registry_digest: DigestObject
    entry_count: int
    null_module_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyObservationPayload:
    observations: tuple[ImportObservation, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ApiSurfaceObservationPayload:
    symbols: tuple[ApiSymbolObservation, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadCodeObservationPayload:
    candidates: tuple[DeadCodeObservation, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class IntegerObservationPayload:
    observations: tuple[IntegerObservation, ...]
    entity_population: int

    def __post_init__(self) -> None:
        if self.entity_population < 0:
            raise ValueError("observation entity population must be non-negative")
        rows_per_dimension: dict[str, int] = {}
        for item in self.observations:
            rows_per_dimension[item.dimension] = (
                rows_per_dimension.get(item.dimension, 0) + 1
            )
        if any(count > self.entity_population for count in rows_per_dimension.values()):
            raise ValueError(
                "observation rows per dimension cannot exceed the entity population"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AdoptionObservationPayload:
    counts: tuple[AdoptionCount, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticAuthorityObservation:
    contract_id: str
    sink_identity: str
    authority_status: AuthorityStatus
    producer_root_ids: tuple[str, ...]
    effect_signature: str
    resolution_state: AuthorityResolutionState
    algorithm_revision: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticAuthorityObservationPayload:
    observations: tuple[SemanticAuthorityObservation, ...]


_CLONE_OBSERVATION_PAYLOAD_ADAPTER = TypeAdapter(CloneObservationPayload)
_ADOPTIONCOLUMNARPAYLOAD_ADAPTER = TypeAdapter(AdoptionColumnarPayload)
_APISURFACECOLUMNARPAYLOAD_ADAPTER = TypeAdapter(ApiSurfaceColumnarPayload)
_DEADCODECOLUMNARPAYLOAD_ADAPTER = TypeAdapter(DeadCodeColumnarPayload)
_DEPENDENCYCOLUMNARPAYLOAD_ADAPTER = TypeAdapter(DependencyColumnarPayload)
_INTEGERCOLUMNARPAYLOAD_ADAPTER = TypeAdapter(IntegerColumnarPayload)
_MODULEIDENTITYCOLUMNARPAYLOAD_ADAPTER = TypeAdapter(ModuleIdentityColumnarPayload)
_SEMANTIC_AUTHORITY_OBSERVATION_PAYLOAD_ADAPTER = TypeAdapter(
    SemanticAuthorityObservationPayload
)


def parse_clone_observation_payload(value: object) -> CloneObservationPayload:
    return _CLONE_OBSERVATION_PAYLOAD_ADAPTER.validate_python(value)


def parse_adoption_columnar_payload(value: object) -> AdoptionColumnarPayload:
    return _ADOPTIONCOLUMNARPAYLOAD_ADAPTER.validate_python(value)


def parse_api_surface_columnar_payload(value: object) -> ApiSurfaceColumnarPayload:
    return _APISURFACECOLUMNARPAYLOAD_ADAPTER.validate_python(value)


def parse_dead_code_columnar_payload(value: object) -> DeadCodeColumnarPayload:
    return _DEADCODECOLUMNARPAYLOAD_ADAPTER.validate_python(value)


def parse_dependency_columnar_payload(value: object) -> DependencyColumnarPayload:
    return _DEPENDENCYCOLUMNARPAYLOAD_ADAPTER.validate_python(value)


def parse_integer_columnar_payload(value: object) -> IntegerColumnarPayload:
    return _INTEGERCOLUMNARPAYLOAD_ADAPTER.validate_python(value)


def parse_module_identity_columnar_payload(
    value: object,
) -> ModuleIdentityColumnarPayload:
    return _MODULEIDENTITYCOLUMNARPAYLOAD_ADAPTER.validate_python(value)


def parse_semantic_authority_observation_payload(
    value: object,
) -> SemanticAuthorityObservationPayload:
    return _SEMANTIC_AUTHORITY_OBSERVATION_PAYLOAD_ADAPTER.validate_python(value)


# The closed set a lane payload may take on the wire: seven columnar forms, the
# two record forms that stay, and the opaque form of an outdated lane.
LanePayload = (
    AdoptionColumnarPayload
    | ApiSurfaceColumnarPayload
    | CloneObservationPayload
    | DeadCodeColumnarPayload
    | DependencyColumnarPayload
    | IntegerColumnarPayload
    | ModuleIdentityColumnarPayload
    | SemanticAuthorityObservationPayload
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservationLane:
    descriptor: ObservationLaneDescriptor
    payload: LanePayload


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservationBundle:
    contract: ObservationContract
    analysis_scope: tuple[FileIdentity, ...]
    manifest: ModuleIdentityManifest
    registry: ModuleRegistryHandle
    semantic: SemanticAuthorityResult | None
    structural: StructuralObservationFacts
    observation_digest: DigestObject

    def __post_init__(self) -> None:
        paths = tuple(identity.path for identity in self.analysis_scope)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("observation analysis scope must be sorted and unique")
        if self.observation_digest.domain != "codeclone.source-observations.v1":
            raise ValueError("observation bundle has the wrong digest domain")
        semantic_enabled = "semantic_authority" in self.contract.enabled_lanes
        if semantic_enabled != (self.semantic is not None):
            raise ValueError("semantic lane presence must match the semantic fact")

    def digest(self) -> DigestObject:
        return self.observation_digest


BaselineReadFailureKind = Literal[
    "inconsistent_container",
    "invalid_container",
    "invalid_json",
    "lane_digest_mismatch",
    "root_digest_mismatch",
    "too_large",
    "unknown_required_lane",
    "unsupported_format",
    "unreadable",
]
LaneTrustStatus = Literal["trusted", "unavailable"]
BaselinePublishOutcome = Literal["noop", "published", "recovered"]
BaselineTargetKind = Literal["absent", "legacy", "v3"]
BaselinePublishFailureReason = Literal[
    "active_lock",
    "cas_conflict",
    "foreign_lock",
    "invalid_lock",
    "invalid_target",
    "oversize",
    "scope_mismatch",
]
LaneTrustReason = Literal[
    "algorithm_revision",
    "baseline_scope_id",
    "canonicalization_version",
    "compatible",
    "descriptor_version",
    "lane_digest_mismatch",
    "payload_schema",
    "payload_schema_outdated",
    "python_tag",
    "required_contract",
    "root_digest_mismatch",
    "runtime_lane_unknown",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineGenerator:
    name: Literal["codeclone"]
    version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineMeta:
    container_version: Literal["3.0"]
    generator: BaselineGenerator
    python_tag: str
    created_at: str
    project_label: str | None
    root_digest: DigestObject

    def __post_init__(self) -> None:
        if not self.python_tag:
            raise ValueError("baseline python tag must be non-empty")
        if not self.created_at.endswith("Z"):
            raise ValueError("baseline created_at must be a UTC Z timestamp")
        if self.root_digest.domain != "codeclone.baseline.root.v1":
            raise ValueError("baseline meta has the wrong root digest domain")


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeSourceBinding:
    module_identity_manifest_digest: DigestObject
    module_registry_digest: DigestObject
    analysis_scope_digest: DigestObject
    observation_digest: DigestObject

    def __post_init__(self) -> None:
        expected = (
            (self.module_identity_manifest_digest, "ccmi2:manifest"),
            (self.module_registry_digest, "codeclone.module-registry.v1"),
            (self.analysis_scope_digest, "codeclone.analysis-scope.v1"),
            (self.observation_digest, "codeclone.source-observations.v1"),
        )
        if any(digest.domain != domain for digest, domain in expected):
            raise ValueError("native source binding digest domains are inconsistent")


@dataclass(frozen=True, slots=True, kw_only=True)
class EpochTransitionEvidence:
    kind: Literal["baseline_epoch_transition"]
    from_schema: str | None
    from_fingerprint: str | None
    to_schema: Literal["3.0"]
    to_fingerprint: Literal["2"]
    imported_lanes: tuple[str, ...]
    regenerated_lanes: tuple[ObservationLaneName, ...]
    source_legacy_digest: DigestObject | None

    def __post_init__(self) -> None:
        source_fields = (
            self.from_schema,
            self.from_fingerprint,
            self.source_legacy_digest,
        )
        if any(value is None for value in source_fields) and not all(
            value is None for value in source_fields
        ):
            raise ValueError("transition legacy source fields are all-or-none")
        if self.from_schema is not None and not self.from_schema:
            raise ValueError("transition source schema must be non-empty")
        if self.from_fingerprint is not None and not self.from_fingerprint:
            raise ValueError("transition source fingerprint must be non-empty")
        if self.source_legacy_digest is not None and (
            self.source_legacy_digest.domain != "codeclone.baseline.legacy-evidence.v1"
        ):
            raise ValueError("transition has the wrong legacy digest domain")
        if self.imported_lanes:
            raise ValueError("native v3 transitions cannot import legacy lanes")
        if self.regenerated_lanes != tuple(sorted(set(self.regenerated_lanes))):
            raise ValueError("transition regenerated lanes must be sorted and unique")


@dataclass(frozen=True, slots=True, kw_only=True)
class ContractIndex(Mapping[str, str]):
    rows: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        keys = tuple(key for key, _value in self.rows)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("container contracts must be sorted and unique")
        if any(not key or not value for key, value in self.rows):
            raise ValueError("container contracts must be non-empty")

    def __getitem__(self, key: str) -> str:
        for row_key, value in self.rows:
            if row_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self.rows)

    def __len__(self) -> int:
        return len(self.rows)


# A lane whose recorded payload schema is not the current one stays opaque: the
# bytes remain authenticated by the lane digest, but they are never parsed into
# a model that no longer describes them.
OpaqueLanePayload = dict[str, JsonValue]


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineLane:
    name: ObservationLaneName
    required: bool
    descriptor: ObservationLaneDescriptor
    observation_digest: DigestObject
    digest: DigestObject
    # Only a lane read back from disk may be opaque: an outdated schema keeps
    # its authenticated bytes instead of being parsed into a stale model.
    payload: LanePayload | OpaqueLanePayload

    def __post_init__(self) -> None:
        if self.name != self.descriptor.name:
            raise ValueError("baseline lane name must match its descriptor")
        if self.observation_digest.domain != "codeclone.source-observations.v1":
            raise ValueError("baseline lane has the wrong observation digest domain")
        if self.digest.domain != "codeclone.baseline.lane.v1":
            raise ValueError("baseline lane has the wrong digest domain")


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineLaneIndex(Mapping[ObservationLaneName, BaselineLane]):
    rows: tuple[tuple[ObservationLaneName, BaselineLane], ...]

    def __post_init__(self) -> None:
        keys = tuple(key for key, _lane in self.rows)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("baseline lane keys must be sorted and unique")
        if any(key != lane.name for key, lane in self.rows):
            raise ValueError("baseline lane index keys must match lane names")

    def __getitem__(self, key: ObservationLaneName) -> BaselineLane:
        for row_key, lane in self.rows:
            if row_key == key:
                return lane
        raise KeyError(key)

    def __iter__(self) -> Iterator[ObservationLaneName]:
        return (key for key, _lane in self.rows)

    def __len__(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineContainerV3:
    format_name: Literal["codeclone-baseline"]
    meta: BaselineMeta
    contracts: ContractIndex
    baseline_scope_id: UUID
    observation_contract: ObservationContract
    source: NativeSourceBinding
    transition: EpochTransitionEvidence | None
    lanes: BaselineLaneIndex

    def __post_init__(self) -> None:
        lane_names = tuple(self.lanes)
        if lane_names != self.observation_contract.enabled_lanes:
            raise ValueError("container lanes must exactly match enabled lanes")
        if "module_identity" not in self.lanes:
            raise ValueError("native baseline containers require module_identity")


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeContracts:
    python_tag: str
    baseline_scope_id: UUID
    lane_descriptors: tuple[ObservationLaneDescriptor, ...]

    def __post_init__(self) -> None:
        names = tuple(item.name for item in self.lane_descriptors)
        if names != tuple(sorted(set(names))):
            raise ValueError("runtime lane descriptors must be sorted and unique")


@dataclass(frozen=True, slots=True, kw_only=True)
class LaneTrust:
    name: ObservationLaneName
    status: LaneTrustStatus
    reason: LaneTrustReason


@dataclass(frozen=True, slots=True, kw_only=True)
class TrustVector:
    root_verified: bool
    lanes: tuple[LaneTrust, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainerReadSuccess:
    container: BaselineContainerV3


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainerReadFailure:
    reason: BaselineReadFailureKind
    detail: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainerInspectionResult:
    root_digest: DigestObject
    unknown_optional_lanes: tuple[str, ...]
    rewrite_allowed: Literal[False] = False


ContainerReadResult = (
    ContainerReadSuccess | ContainerReadFailure | ContainerInspectionResult
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselinePublicationReceipt:
    outcome: BaselinePublishOutcome
    observed_kind: BaselineTargetKind
    observed_identity: str
    published_root_digest: DigestObject | None
    backup_created: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselinePublishLock:
    token: str
    pid: int
    hostname: str
    process_start: str
    created_at: str

    def __post_init__(self) -> None:
        if (
            not self.token
            or self.pid <= 0
            or not self.hostname
            or not self.process_start
            or not self.created_at.endswith("Z")
        ):
            raise ValueError("baseline publication lock fields must be non-empty")


class DigestObjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    domain: DigestDomain
    algorithm: Literal["sha256"]
    value: str


class ReportDigestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: ReportDigestKind
    algorithm: Literal["sha256"]
    digest_version: Literal["1"]
    value: str


class ReportIntegrityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    canonicalization: dict[str, JsonValue]
    digests: dict[str, ReportDigestInput]


class ReportDocumentV3Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    report_schema_version: str
    meta: dict[str, JsonValue]
    contracts: dict[str, JsonValue]
    source_facts: dict[str, JsonValue]
    baseline: dict[str, JsonValue]
    evaluation: dict[str, JsonValue]
    inventory: dict[str, JsonValue]
    findings: dict[str, JsonValue]
    metrics: dict[str, JsonValue]
    derived: dict[str, JsonValue]
    integrity: ReportIntegrityInput


class BaselinePublishLockInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    token: str
    pid: int
    hostname: str
    process_start: str
    created_at: str


class ObservationLaneDescriptorInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str
    descriptor_version: str
    payload_schema: str
    algorithm_revision: str
    canonicalization_version: str
    required_contracts: tuple[tuple[str, str], ...]


class ObservationContractInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    observation_digest_version: str
    enabled_lanes: tuple[str, ...]
    descriptors: tuple[ObservationLaneDescriptorInput, ...]


class BaselineGeneratorInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str
    version: str


class LegacyBaselineMetaInput(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, strict=True)

    generator: BaselineGeneratorInput
    schema_version: str
    fingerprint_version: str
    python_tag: str
    payload_sha256: str


class LegacyClonePayloadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    functions: tuple[str, ...]
    blocks: tuple[str, ...]


class LegacyBaselineEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, strict=True)

    meta: LegacyBaselineMetaInput
    clones: LegacyClonePayloadInput


class BaselineMetaInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    container_version: str
    generator: BaselineGeneratorInput
    python_tag: str
    created_at: str
    project_label: str | None
    root_digest: DigestObjectInput


class NativeSourceBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    module_identity_manifest_digest: DigestObjectInput
    module_registry_digest: DigestObjectInput
    analysis_scope_digest: DigestObjectInput
    observation_digest: DigestObjectInput


class EpochTransitionEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["baseline_epoch_transition"]
    from_schema: str | None
    from_fingerprint: str | None
    to_schema: Literal["3.0"]
    to_fingerprint: Literal["2"]
    imported_lanes: tuple[str, ...]
    regenerated_lanes: tuple[str, ...]
    source_legacy_digest: DigestObjectInput | None


class BaselineLaneInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    required: bool
    descriptor: ObservationLaneDescriptorInput
    observation_digest: DigestObjectInput
    digest: DigestObjectInput
    payload: JsonValue


class BaselineContainerV3Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    format: str
    meta: BaselineMetaInput
    contracts: dict[str, str]
    baseline_scope_id: UUID
    observation_contract: ObservationContractInput
    source: NativeSourceBindingInput
    transition: EpochTransitionEvidenceInput | None
    lanes: dict[str, BaselineLaneInput]


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
    test_reference_sources: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    runtime_reachability: tuple[RuntimeReachabilityFact, ...] = ()
    security_surfaces: tuple[SecuritySurface, ...] = ()
    typing_modules: tuple[ModuleTypingCoverage, ...] = ()
    docstring_modules: tuple[ModuleDocstringCoverage, ...] = ()
    api_modules: tuple[ModuleApiSurface, ...] = ()
    semantic_authority: SemanticAuthorityResult | None = None
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
    statement_sequence: tuple[NearMissElement, ...]
    unreachable_statements: tuple[UnreachableStatementItem, ...]


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


class CacheFactsDictBase(TypedDict):
    source_stats: SourceStatsDict
    units: list[FunctionGroupItem]
    blocks: list[BlockGroupItem]
    segments: list[SegmentGroupItem]
    class_metrics: list[ClassMetricsDict]
    module_deps: list[ModuleDepDict]
    dead_candidates: list[DeadCandidateDict]
    referenced_names: list[str]
    referenced_qualnames: list[str]
    import_names: list[str]
    class_names: list[str]
    runtime_reachability: list[RuntimeReachabilityFactDict]
    security_surfaces: list[SecuritySurfaceDict]
    function_relationship_facts: list[FunctionRelationshipFactsDict]


class CacheFactsDict(CacheFactsDictBase, total=False):
    typing_coverage: ModuleTypingCoverageDict
    docstring_coverage: ModuleDocstringCoverageDict
    api_surface: ModuleApiSurfaceDict
    structural_findings: list[StructuralFindingGroupDict]


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
