# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from argparse import Namespace
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

import orjson

from ..analysis.normalizer import NormalizationConfig
from ..cache.projection import SegmentReportProjection
from ..contracts import DEFAULT_PROCESSES
from ..models import (
    BlockUnit,
    ClassMetrics,
    CoverageJoinResult,
    DeadCandidate,
    DigestObject,
    FileMetrics,
    FileStat,
    FunctionContractSummary,
    FunctionRelationshipFacts,
    GroupItem,
    GroupItemLike,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleRegistryHandle,
    ModuleTypingCoverage,
    NearMissPair,
    ObservationBundle,
    ProjectMetrics,
    RehydratedCacheNeutral,
    RenamedStructureGroup,
    RunSnapshotLink,
    RuntimeReachabilityFact,
    SecuritySurface,
    SegmentGroupItem,
    SegmentUnit,
    SemanticAuthorityResult,
    SemanticEvent,
    StructuralFindingGroup,
    Suggestion,
    SuppressedCloneGroup,
    Unit,
    UnsupportedConstructSkip,
)
from ..utils.coerce import as_int, as_mapping, as_str

if TYPE_CHECKING:
    from ..analysis.phase_ledger import PhaseSnapshot

MAX_FILE_SIZE = 10 * 1024 * 1024

#: Display prefix for a wire-refused file's error string. The machine-readable
#: discriminator is ``FileProcessResult.error_kind == "unsupported_construct"``;
#: this prefix only keeps the human-facing failure lines self-explanatory.
UNSUPPORTED_CONSTRUCT_ERROR_PREFIX = "Unsupported construct: "
DEFAULT_BATCH_SIZE = 100
PARALLEL_MIN_FILES_PER_WORKER = 8
PARALLEL_MIN_FILES_FLOOR = 16
DEFAULT_RUNTIME_PROCESSES = DEFAULT_PROCESSES


@dataclass(frozen=True, slots=True)
class OutputPaths:
    html: Path | None = None
    json: Path | None = None
    text: Path | None = None
    md: Path | None = None
    sarif: Path | None = None


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    root: Path
    config: NormalizationConfig
    args: Namespace
    output_paths: OutputPaths
    cache_path: Path


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    files_found: int
    cache_hits: int
    files_skipped: int
    all_file_paths: tuple[str, ...]
    cached_units: tuple[GroupItem, ...]
    cached_blocks: tuple[GroupItem, ...]
    cached_segments: tuple[GroupItem, ...]
    cached_class_metrics: tuple[ClassMetrics, ...]
    cached_module_deps: tuple[ModuleDep, ...]
    cached_dead_candidates: tuple[DeadCandidate, ...]
    cached_referenced_names: frozenset[str]
    files_to_process: tuple[str, ...]
    skipped_warnings: tuple[str, ...]
    module_registry: ModuleRegistryHandle
    cached_runtime_reachability: tuple[RuntimeReachabilityFact, ...] = ()
    cached_security_surfaces: tuple[SecuritySurface, ...] = ()
    cached_referenced_qualnames: frozenset[str] = frozenset()
    cached_typing_modules: tuple[ModuleTypingCoverage, ...] = ()
    cached_docstring_modules: tuple[ModuleDocstringCoverage, ...] = ()
    cached_api_modules: tuple[ModuleApiSurface, ...] = ()
    cached_structural_findings: tuple[StructuralFindingGroup, ...] = ()
    cached_function_relationship_facts: tuple[FunctionRelationshipFacts, ...] = ()
    cached_semantic_events: tuple[SemanticEvent, ...] = ()
    cached_function_contract_summaries: tuple[FunctionContractSummary, ...] = ()
    neutral_reuse_by_file: tuple[tuple[str, RehydratedCacheNeutral], ...] = ()
    cached_segment_report_projection: SegmentReportProjection | None = None
    cached_lines: int = 0
    cached_functions: int = 0
    cached_methods: int = 0
    cached_classes: int = 0
    cached_source_stats_by_file: tuple[tuple[str, int, int, int, int], ...] = ()
    # Content identity of every cache hit, as (runtime path, sha256 hex). A hit
    # is granted only once its bytes are proven, so this is the digest the
    # reused facts describe.
    cached_source_digest_by_file: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class FileProcessResult:
    filepath: str
    success: bool
    source_content_digest: DigestObject | None
    error: str | None = None
    units: list[Unit] | None = None
    blocks: list[BlockUnit] | None = None
    segments: list[SegmentUnit] | None = None
    lines: int = 0
    functions: int = 0
    methods: int = 0
    classes: int = 0
    stat: FileStat | None = None
    error_kind: str | None = None
    file_metrics: FileMetrics | None = None
    structural_findings: list[StructuralFindingGroup] | None = None
    phase_snapshot: PhaseSnapshot | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.success and self.source_content_digest is None:
            raise ValueError("successful file processing requires a source digest")


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    units: tuple[GroupItem, ...]
    blocks: tuple[GroupItem, ...]
    segments: tuple[GroupItem, ...]
    class_metrics: tuple[ClassMetrics, ...]
    module_deps: tuple[ModuleDep, ...]
    dead_candidates: tuple[DeadCandidate, ...]
    referenced_names: frozenset[str]
    files_analyzed: int
    files_skipped: int
    analyzed_lines: int
    analyzed_functions: int
    analyzed_methods: int
    analyzed_classes: int
    failed_files: tuple[str, ...]
    source_read_failures: tuple[str, ...]
    unsupported_construct_skips: tuple[UnsupportedConstructSkip, ...] = ()
    runtime_reachability: tuple[RuntimeReachabilityFact, ...] = ()
    security_surfaces: tuple[SecuritySurface, ...] = ()
    semantic_events: tuple[SemanticEvent, ...] = ()
    function_contract_summaries: tuple[FunctionContractSummary, ...] = ()
    semantic_authority: SemanticAuthorityResult | None = None
    referenced_qualnames: frozenset[str] = frozenset()
    typing_modules: tuple[ModuleTypingCoverage, ...] = ()
    docstring_modules: tuple[ModuleDocstringCoverage, ...] = ()
    api_modules: tuple[ModuleApiSurface, ...] = ()
    structural_findings: tuple[StructuralFindingGroup, ...] = ()
    function_relationship_facts: tuple[FunctionRelationshipFacts, ...] = ()
    source_stats_by_file: tuple[tuple[str, int, int, int, int], ...] = ()
    # The bytes this run's facts rest on, per file: worker digests for what was
    # parsed, proven cache digests for what was reused. A consumer that must
    # know whether the run observed an edit compares against this, never a stat.
    source_digest_by_file: tuple[tuple[str, str], ...] = ()
    phase_snapshot: PhaseSnapshot | None = field(
        default=None,
        compare=False,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    func_groups: Mapping[str, list[GroupItem]]
    block_groups: Mapping[str, list[GroupItem]]
    block_groups_report: Mapping[str, list[GroupItem]]
    segment_groups: Mapping[str, list[GroupItem]]
    #: Segment groups the report's low-value filter removed from the
    #: active lane. A detector precision signal, not a suppression rule:
    #: it carries no provenance and no configuration, and it is a
    #: different population from ``suppressed_clone_groups``.
    low_value_segment_groups: int
    block_group_facts: dict[str, dict[str, str]]
    func_clones_count: int
    block_clones_count: int
    segment_clones_count: int
    files_analyzed_or_cached: int
    project_metrics: ProjectMetrics | None
    metrics_payload: dict[str, object] | None
    suggestions: tuple[Suggestion, ...]
    segment_groups_raw_digest: str
    observation_bundle: ObservationBundle
    suppressed_clone_groups: tuple[SuppressedCloneGroup, ...] = ()
    coverage_join: CoverageJoinResult | None = None
    suppressed_dead_code_items: int = 0
    structural_findings: tuple[StructuralFindingGroup, ...] = ()
    # Report-only advisory channel: near-miss pairs never enter func_groups,
    # so they reach no observation lane, no baseline novelty and no gate.
    # ``None`` is the execution witness "the producer was never invoked"
    # (opt-in off) and serializes as a ``state: "disabled"`` container; an
    # empty tuple means the producer ran and measured nothing and serializes
    # as ``state: "complete"`` with ``count: 0``. Collapsing the two would
    # re-open the empty-root-is-not-unmeasured hole (T1, 2026-08-24).
    near_miss_pairs: tuple[NearMissPair, ...] | None = None
    # Same confinement and the same execution witness, Wave C:
    # renamed-structure groups are a sibling of the clone lane, never a
    # member of it; ``None`` means not produced, ``()`` means produced empty.
    renamed_structure_groups: tuple[RenamedStructureGroup, ...] | None = None


@dataclass(frozen=True, slots=True)
class ReportArtifacts:
    # Rendered artifacts are the exact bytes destined for disk. Carrying them
    # as `str` cost a second full copy of the JSON report -- the largest thing
    # the process holds -- for the encode at write time.
    html: bytes | None = None
    json: bytes | None = None
    text: bytes | None = None
    md: bytes | None = None
    sarif: bytes | None = None
    report_document: dict[str, object] | None = None
    #: The identity bridge for this run (RULING-2026-08-24 §7): the typed
    #: relation between the analysis snapshot the store holds and the
    #: evaluated identity this document carries.  Always present -- a run
    #: that stored nothing says so through the link's state, because an
    #: absent link and "there is no backend" would be the same silence.
    run_snapshot_link: RunSnapshotLink | None = None


def _as_sorted_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(sorted({item for item in value if isinstance(item, str) and item}))


def _group_item_sort_key(item: GroupItemLike) -> tuple[str, int, int, str]:
    return (
        as_str(item.get("filepath")),
        as_int(item.get("start_line")),
        as_int(item.get("end_line")),
        as_str(item.get("qualname")),
    )


def _segment_projection_item_sort_key(
    item: GroupItemLike,
) -> tuple[str, str, int, int]:
    return (
        as_str(item.get("filepath")),
        as_str(item.get("qualname")),
        as_int(item.get("start_line")),
        as_int(item.get("end_line")),
    )


def _segment_groups_digest(segment_groups: Mapping[str, list[GroupItem]]) -> str:
    normalized_rows: list[
        tuple[str, tuple[tuple[str, str, int, int, int, str, str], ...]]
    ] = []
    for group_key in sorted(segment_groups):
        items = sorted(segment_groups[group_key], key=_segment_projection_item_sort_key)
        normalized_items = [
            (
                as_str(item.get("filepath")),
                as_str(item.get("qualname")),
                as_int(item.get("start_line")),
                as_int(item.get("end_line")),
                as_int(item.get("size")),
                as_str(item.get("segment_hash")),
                as_str(item.get("segment_sig")),
            )
            for item in items
        ]
        normalized_rows.append((group_key, tuple(normalized_items)))
    payload = orjson.dumps(tuple(normalized_rows), option=orjson.OPT_SORT_KEYS)
    return sha256(payload).hexdigest()


def _coerce_segment_report_projection(
    value: object,
) -> SegmentReportProjection | None:
    row = as_mapping(value)
    if not row:
        return None
    match row.get("digest"), row.get("suppressed"), row.get("groups"):
        case str() as digest, int() as suppressed, dict() as groups:
            pass
        case _:
            return None
    if not all(
        isinstance(group_key, str) and isinstance(items, list)
        for group_key, items in groups.items()
    ):
        return None
    normalized_groups: dict[str, list[SegmentGroupItem]] = {}
    for group_key, items in groups.items():
        if not isinstance(group_key, str) or not isinstance(items, list):
            return None
        normalized_items: list[SegmentGroupItem] = []
        for item in items:
            if not isinstance(item, dict):
                return None
            segment_hash = item.get("segment_hash")
            segment_sig = item.get("segment_sig")
            filepath = item.get("filepath")
            qualname = item.get("qualname")
            start_line = item.get("start_line")
            end_line = item.get("end_line")
            size = item.get("size")
            if not (
                isinstance(segment_hash, str)
                and isinstance(segment_sig, str)
                and isinstance(filepath, str)
                and isinstance(qualname, str)
                and isinstance(start_line, int)
                and isinstance(end_line, int)
                and isinstance(size, int)
            ):
                return None
            normalized_items.append(
                SegmentGroupItem(
                    segment_hash=segment_hash,
                    segment_sig=segment_sig,
                    filepath=filepath,
                    qualname=qualname,
                    start_line=start_line,
                    end_line=end_line,
                    size=size,
                )
            )
        normalized_groups[group_key] = normalized_items
    return {
        "digest": digest,
        "suppressed": suppressed,
        "groups": normalized_groups,
    }


def _module_dep_sort_key(dep: ModuleDep) -> tuple[str, str, str, int]:
    return dep.source, dep.target, dep.import_type, dep.line


def _class_metric_sort_key(metric: ClassMetrics) -> tuple[str, int, int, str]:
    return metric.filepath, metric.start_line, metric.end_line, metric.qualname


def _dead_candidate_sort_key(item: DeadCandidate) -> tuple[str, int, int, str]:
    return item.filepath, item.start_line, item.end_line, item.qualname


def _unit_to_group_item(unit: Unit) -> GroupItem:
    return {
        "qualname": unit.qualname,
        "filepath": unit.filepath,
        "start_line": unit.start_line,
        "end_line": unit.end_line,
        "loc": unit.loc,
        "stmt_count": unit.stmt_count,
        "fingerprint": unit.fingerprint,
        "loc_bucket": unit.loc_bucket,
        "cyclomatic_complexity": unit.cyclomatic_complexity,
        "cfg_cyclomatic_complexity": unit.cfg_cyclomatic_complexity,
        "nesting_depth": unit.nesting_depth,
        "risk": unit.risk,
        "raw_hash": unit.raw_hash,
        "entry_guard_count": unit.entry_guard_count,
        "entry_guard_terminal_profile": unit.entry_guard_terminal_profile,
        "entry_guard_has_side_effect_before": unit.entry_guard_has_side_effect_before,
        "terminal_kind": unit.terminal_kind,
        "try_finally_profile": unit.try_finally_profile,
        "side_effect_order_profile": unit.side_effect_order_profile,
        # Read only by the near-miss tier. Every other consumer projects unit
        # facts by explicit key, so carrying it here reaches no lane, no
        # baseline and no report payload (39Y Y8 confinement).
        "statement_sequence": unit.statement_sequence,
        # Read only by the renamed-structure tier, on the same confinement.
        "renamed_fingerprint": unit.renamed_fingerprint,
        # Read only by the near-miss tier's renamed token domain, on the same
        # confinement.
        "renamed_statement_sequence": unit.renamed_statement_sequence,
        # Read by the dead_code family, which projects it by explicit key.
        "unreachable_statements": unit.unreachable_statements,
    }


def _block_to_group_item(block: BlockUnit) -> GroupItem:
    return {
        "block_hash": block.block_hash,
        "filepath": block.filepath,
        "qualname": block.qualname,
        "start_line": block.start_line,
        "end_line": block.end_line,
        "size": block.size,
    }


def _segment_to_group_item(segment: SegmentUnit) -> GroupItem:
    return {
        "filepath": segment.filepath,
        "qualname": segment.qualname,
        "start_line": segment.start_line,
        "end_line": segment.end_line,
        "size": segment.size,
        "segment_hash": segment.segment_hash,
        "segment_sig": segment.segment_sig,
    }


def structural_findings_required() -> bool:
    """Sole owner of "must this analysis materialise structural findings".

    Structural findings are an analysis fact, not a report artifact. Which
    facts a run produces is a property of the analysis; which of them a run
    renders is a different question with a different owner
    (``report_document_required``). Conflating the two is what this function
    replaces: the requirement used to be read off ``OutputPaths``, so the CLI
    answered it from ``--json``/``--html`` (absent by default) and MCP from a
    hardcoded dummy report path (present always). The two answers were not in
    conflict, they were a subset and a superset -- and a row written under the
    subset is refused by every run under the superset.

    Measured 2026-09-02 on this repository (1148 files): after a CLI run with
    no report flags populated the store, the next MCP analysis reused 0 of
    1148 rows and rewrote every one, with both cache lanes hitting and content
    identity unchanged. Converging the two surfaces cost 2296 row writes
    instead of 1148.

    One value for every run, so a stored row's fact population cannot vary
    with the output files an operator happened to ask for. It is a function
    rather than a literal at three call sites because the three sites must
    never be able to disagree -- the defect one lane over (``api_surface``,
    keyed at construction and materialised from a different expression in
    ``parallelism``) is exactly what separate literals produce.

    Cost of the requirement, measured on the same 1148 files with only this
    value changed: dependent-lane payload 20 915 256 -> 20 934 304 bytes
    (+0.09%), cache file 55 881 728 -> 55 894 016 bytes (+0.02%), and no CPU
    difference outside run-to-run noise (median 30.2s vs 29.9s over four
    alternating cold runs) -- the traversal that finds them runs either way;
    only the accumulation of what it saw is new.
    """

    return True
