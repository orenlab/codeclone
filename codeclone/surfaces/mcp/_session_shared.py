# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import subprocess
from argparse import Namespace
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from threading import RLock
from typing import Final, Literal, TypeVar

import orjson

from ... import __version__
from ...baseline import Baseline
from ...cache.store import Cache
from ...cache.versioning import CacheStatus
from ...config.pyproject_loader import (
    ConfigValidationError,
    load_pyproject_config,
)
from ...config.spec import (
    DEFAULT_BASELINE_PATH,
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_MAX_BASELINE_SIZE_MB,
    DEFAULT_MAX_CACHE_SIZE_MB,
    DEFAULT_MIN_LOC,
    DEFAULT_MIN_STMT,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
)
from ...contracts import (
    DEFAULT_COVERAGE_MIN,
    DEFAULT_JSON_REPORT_PATH,
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    REPORT_SCHEMA_VERSION,
)
from ...core._types import OutputPaths
from ...core.bootstrap import bootstrap
from ...core.discovery import discover
from ...core.parallelism import process
from ...core.pipeline import analyze
from ...core.reporting import report
from ...domain.findings import (
    CATEGORY_CLONE,
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CATEGORY_STRUCTURAL,
    CLONE_KIND_SEGMENT,
    FAMILY_CLONE,
    FAMILY_CLONES,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_STRUCTURAL,
)
from ...domain.quality import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    EFFORT_EASY,
    EFFORT_HARD,
    EFFORT_MODERATE,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from ...domain.source_scope import (
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_MIXED,
    SOURCE_KIND_ORDER,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)
from ...findings.ids import (
    clone_group_id,
    dead_code_group_id,
    design_group_id,
    structural_group_id,
)
from ...models import CoverageJoinResult, MetricsDiff, ProjectMetrics, Suggestion
from ...report.gates.evaluator import GateResult as GatingResult
from ...report.gates.evaluator import MetricGateConfig
from ...report.gates.evaluator import evaluate_gates as _evaluate_report_gates
from ...report.gates.evaluator import summarize_metrics_diff as _summarize_metrics_diff
from ...utils.coerce import as_float as _as_float
from ...utils.coerce import as_int as _as_int
from ...utils.git_diff import validate_git_diff_ref
from .messages.help_topics import HELP_TOPIC_SPECS as _HELP_TOPIC_SPECS
from .payloads import paginate, resolve_finding_id, short_id

AnalysisMode = Literal["full", "clones_only"]
CachePolicy = Literal["reuse", "off"]
FreshnessKind = Literal["fresh", "mixed", "reused"]
HotlistKind = Literal[
    "most_actionable",
    "highest_spread",
    "highest_priority",
    "production_hotspots",
    "test_fixture_hotspots",
]
FindingFamilyFilter = Literal["all", "clone", "structural", "dead_code", "design"]
FindingNoveltyFilter = Literal["all", "new", "known"]
FindingSort = Literal["default", "priority", "severity", "spread"]
DetailLevel = Literal["summary", "normal", "full"]
ComparisonFocus = Literal["all", "clones", "structural", "metrics"]
PRSummaryFormat = Literal["markdown", "json"]
HelpTopic = Literal[
    "workflow",
    "analysis_profile",
    "suppressions",
    "baseline",
    "coverage",
    "latest_runs",
    "review_state",
    "changed_scope",
    "change_control",
    "trust_boundaries",
    "engineering_memory",
    "verification_profiles",
]
HelpDetail = Literal["compact", "normal"]
MetricsDetailFamily = Literal[
    "complexity",
    "coupling",
    "cohesion",
    "coverage_adoption",
    "coverage_join",
    "dependencies",
    "dead_code",
    "api_surface",
    "security_surfaces",
    "god_modules",
    "overloaded_modules",
    "health",
]
ReportSection = Literal[
    "all",
    "meta",
    "inventory",
    "findings",
    "metrics",
    "metrics_detail",
    "derived",
    "changed",
    "integrity",
]
HealthScope = Literal["repository"]
SummaryFocus = Literal["repository", "production", "changed_paths"]

_REPORT_DUMMY_PATH = Path(DEFAULT_JSON_REPORT_PATH)
_HEALTH_SCOPE_REPOSITORY: Final[HealthScope] = "repository"
_FOCUS_REPOSITORY: Final[SummaryFocus] = "repository"
_FOCUS_PRODUCTION: Final[SummaryFocus] = "production"
_FOCUS_CHANGED_PATHS: Final[SummaryFocus] = "changed_paths"
_MCP_GOVERNANCE_CONFIG_KEYS = frozenset(
    {
        "golden_fixture_paths",
    }
)
_MCP_CONFIG_KEYS = frozenset(
    {
        "min_loc",
        "min_stmt",
        "block_min_loc",
        "block_min_stmt",
        "segment_min_loc",
        "segment_min_stmt",
        "processes",
        "cache_path",
        "max_cache_size_mb",
        "baseline",
        "max_baseline_size_mb",
        "metrics_baseline",
        "api_surface",
        "coverage_xml",
        "coverage_min",
        "golden_fixture_paths",
    }
)
_RESOURCE_SECTION_MAP: Final[dict[str, ReportSection]] = {
    "report.json": "all",
    "summary": "meta",
    "health": "metrics",
    "changed": "changed",
    "overview": "derived",
}
_SEVERITY_WEIGHT: Final[dict[str, float]] = {
    SEVERITY_CRITICAL: 1.0,
    SEVERITY_WARNING: 0.6,
    SEVERITY_INFO: 0.2,
}
_EFFORT_WEIGHT: Final[dict[str, float]] = {
    EFFORT_EASY: 1.0,
    EFFORT_MODERATE: 0.6,
    EFFORT_HARD: 0.3,
}
_NOVELTY_WEIGHT: Final[dict[str, float]] = {"new": 1.0, "known": 0.5}
_RUNTIME_WEIGHT: Final[dict[str, float]] = {
    "production": 1.0,
    "mixed": 0.8,
    "tests": 0.4,
    "fixtures": 0.2,
    "other": 0.5,
}
_CONFIDENCE_WEIGHT: Final[dict[str, float]] = {
    CONFIDENCE_HIGH: 1.0,
    CONFIDENCE_MEDIUM: 0.7,
    CONFIDENCE_LOW: 0.3,
}
# Canonical report groups use FAMILY_CLONES ("clones"), while individual finding
# payloads use FAMILY_CLONE ("clone").
_VALID_ANALYSIS_MODES = frozenset({"full", "clones_only"})
_VALID_CACHE_POLICIES = frozenset({"reuse", "off"})
_VALID_FINDING_FAMILIES = frozenset(
    {"all", "clone", "structural", "dead_code", "design"}
)
_VALID_FINDING_NOVELTY = frozenset({"all", "new", "known"})
_VALID_FINDING_SORT = frozenset({"default", "priority", "severity", "spread"})
_VALID_DETAIL_LEVELS = frozenset({"summary", "normal", "full"})
_VALID_COMPARISON_FOCUS = frozenset({"all", "clones", "structural", "metrics"})
_VALID_PR_SUMMARY_FORMATS = frozenset({"markdown", "json"})
_VALID_HELP_TOPICS = frozenset(
    {
        "workflow",
        "analysis_profile",
        "suppressions",
        "baseline",
        "coverage",
        "latest_runs",
        "review_state",
        "changed_scope",
        "change_control",
        "trust_boundaries",
        "observability",
        "engineering_memory",
        "verification_profiles",
    }
)
_VALID_HELP_DETAILS = frozenset({"compact", "normal"})
DEFAULT_MCP_HISTORY_LIMIT = 4
MAX_MCP_HISTORY_LIMIT = 10
_VALID_REPORT_SECTIONS = frozenset(
    {
        "all",
        "meta",
        "inventory",
        "findings",
        "metrics",
        "metrics_detail",
        "derived",
        "changed",
        "integrity",
    }
)
_VALID_HOTLIST_KINDS = frozenset(
    {
        "most_actionable",
        "highest_spread",
        "highest_priority",
        "production_hotspots",
        "test_fixture_hotspots",
    }
)
_VALID_SEVERITIES = frozenset({SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO})
_SOURCE_KIND_BREAKDOWN_ORDER: Final[tuple[str, ...]] = (
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_MIXED,
    SOURCE_KIND_OTHER,
)
_COMPACT_ITEM_PATH_KEYS: Final[frozenset[str]] = frozenset(
    {"relative_path", "path", "filepath", "file"}
)
_COMPACT_ITEM_EMPTY_VALUES: Final[tuple[object, ...]] = ("", None, [], {}, ())
_HOTLIST_REPORT_KEYS: Final[dict[str, str]] = {
    "most_actionable": "most_actionable_ids",
    "highest_spread": "highest_spread_ids",
    "production_hotspots": "production_hotspot_ids",
    "test_fixture_hotspots": "test_fixture_hotspot_ids",
}
_CHECK_TO_DIMENSION: Final[dict[str, str]] = {
    "cohesion": "cohesion",
    "coupling": "coupling",
    "dead_code": "dead_code",
    "complexity": "complexity",
    "clones": "clones",
}
_DESIGN_CHECK_CONTEXT: Final[dict[str, dict[str, object]]] = {
    "complexity": {
        "category": CATEGORY_COMPLEXITY,
        "metric": "cyclomatic_complexity",
        "operator": ">",
        "default_threshold": DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    },
    "coupling": {
        "category": CATEGORY_COUPLING,
        "metric": "cbo",
        "operator": ">",
        "default_threshold": DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    },
    "cohesion": {
        "category": CATEGORY_COHESION,
        "metric": "lcom4",
        "operator": ">=",
        "default_threshold": DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    },
}
_VALID_METRICS_DETAIL_FAMILIES = frozenset(
    {
        "complexity",
        "coupling",
        "cohesion",
        "coverage_adoption",
        "coverage_join",
        "dependencies",
        "dead_code",
        "api_surface",
        "security_surfaces",
        "god_modules",
        "overloaded_modules",
        "health",
    }
)
_METRICS_DETAIL_FAMILY_ALIASES: Final[dict[str, str]] = {
    "god_modules": "overloaded_modules",
}
_SHORT_RUN_ID_LENGTH = 8
_SHORT_HASH_ID_LENGTH = 6
ChoiceT = TypeVar("ChoiceT", bound=str)


def _suggestion_finding_id_payload(suggestion: object) -> str:
    if not hasattr(suggestion, "finding_family"):
        return ""
    family = str(getattr(suggestion, "finding_family", "")).strip()
    if family == FAMILY_CLONES:
        kind = str(getattr(suggestion, "finding_kind", "")).strip()
        subject_key = str(getattr(suggestion, "subject_key", "")).strip()
        return clone_group_id(kind or CLONE_KIND_SEGMENT, subject_key)
    if family == FAMILY_STRUCTURAL:
        return structural_group_id(
            str(getattr(suggestion, "finding_kind", "")).strip() or CATEGORY_STRUCTURAL,
            str(getattr(suggestion, "subject_key", "")).strip(),
        )
    category = str(getattr(suggestion, "category", "")).strip()
    subject_key = str(getattr(suggestion, "subject_key", "")).strip()
    if category == CATEGORY_DEAD_CODE:
        return dead_code_group_id(subject_key)
    return design_group_id(
        category,
        subject_key or str(getattr(suggestion, "title", "")),
    )


@dataclass(frozen=True, slots=True)
class _CloneShortIdEntry:
    canonical_id: str
    alias: str
    token: str
    suffix: str

    def render(self, prefix_length: int) -> str:
        if prefix_length <= 0:
            prefix_length = len(self.token)
        return f"{self.alias}:{self.token[:prefix_length]}{self.suffix}"


def _partitioned_short_id(alias: str, remainder: str) -> str:
    first, _, rest = remainder.partition(":")
    return f"{alias}:{first}:{rest}" if rest else f"{alias}:{first}"


def _clone_short_id_entry_payload(canonical_id: str) -> _CloneShortIdEntry:
    _prefix, _, remainder = canonical_id.partition(":")
    clone_kind, _, group_key = remainder.partition(":")
    hashes = [part for part in group_key.split("|") if part]
    if clone_kind == "function":
        fingerprint = hashes[0] if hashes else group_key
        bucket = ""
        if "|" in group_key:
            bucket = "|" + group_key.split("|")[-1]
        return _CloneShortIdEntry(
            canonical_id=canonical_id,
            alias="fn",
            token=fingerprint,
            suffix=bucket,
        )
    alias = {"block": "blk", "segment": "seg"}.get(clone_kind, "clone")
    combined = "|".join(hashes) if hashes else group_key
    token = hashlib.sha256(combined.encode()).hexdigest()
    return _CloneShortIdEntry(
        canonical_id=canonical_id,
        alias=alias,
        token=token,
        suffix=f"|x{len(hashes) or 1}",
    )


def _disambiguated_clone_short_ids_payload(
    canonical_ids: Sequence[str],
) -> dict[str, str]:
    clone_entries = [
        _clone_short_id_entry_payload(canonical_id) for canonical_id in canonical_ids
    ]
    max_token_length = max((len(entry.token) for entry in clone_entries), default=0)
    for prefix_length in range(_SHORT_HASH_ID_LENGTH + 2, max_token_length + 1, 2):
        candidates = {
            entry.canonical_id: entry.render(prefix_length) for entry in clone_entries
        }
        if len(set(candidates.values())) == len(candidates):
            return candidates
    return {
        entry.canonical_id: entry.render(max_token_length) for entry in clone_entries
    }


def _leaf_symbol_name_payload(value: object) -> str:
    text = str(value).strip()
    if not text:
        return ""
    if ":" in text:
        text = text.rsplit(":", maxsplit=1)[-1]
    if "." in text:
        text = text.rsplit(".", maxsplit=1)[-1]
    return text


def _base_short_finding_id_payload(canonical_id: str) -> str:
    prefix, _, remainder = canonical_id.partition(":")
    if prefix == "clone":
        return _clone_short_id_entry_payload(canonical_id).render(_SHORT_HASH_ID_LENGTH)
    if prefix == "structural":
        finding_kind, _, finding_key = remainder.partition(":")
        return f"struct:{finding_kind}:{finding_key[:_SHORT_HASH_ID_LENGTH]}"
    if prefix == "dead_code":
        return f"dead:{_leaf_symbol_name_payload(remainder)}"
    if prefix == "design":
        category, _, subject_key = remainder.partition(":")
        return f"design:{category}:{_leaf_symbol_name_payload(subject_key)}"
    return canonical_id


def _disambiguated_short_finding_id_payload(canonical_id: str) -> str:
    prefix, _, remainder = canonical_id.partition(":")
    if prefix == "clone":
        return _clone_short_id_entry_payload(canonical_id).render(0)
    if prefix == "structural":
        return _partitioned_short_id("struct", remainder)
    if prefix == "dead_code":
        return f"dead:{remainder}"
    if prefix == "design":
        return _partitioned_short_id("design", remainder)
    return canonical_id


def _json_text_payload(
    payload: object,
    *,
    sort_keys: bool = True,
) -> str:
    options = orjson.OPT_INDENT_2
    if sort_keys:
        options |= orjson.OPT_SORT_KEYS
    return orjson.dumps(payload, option=options).decode("utf-8")


def _git_diff_lines_payload(
    *,
    root_path: Path,
    git_diff_ref: str,
) -> tuple[str, ...]:
    try:
        validated_ref = validate_git_diff_ref(git_diff_ref)
    except ValueError as exc:
        raise MCPGitDiffError(str(exc)) from exc
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", validated_ref, "--"],
            cwd=root_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise MCPGitDiffError(
            f"Unable to resolve changed paths from git diff ref '{validated_ref}'."
        ) from exc
    return tuple(
        sorted({line.strip() for line in completed.stdout.splitlines() if line.strip()})
    )


def _load_report_document_payload(report_json: str) -> dict[str, object]:
    try:
        payload = orjson.loads(report_json)
    except JSONDecodeError as exc:
        raise MCPServiceError(
            f"Generated canonical report is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise MCPServiceError("Generated canonical report must be a JSON object.")
    return dict(payload)


def _validated_history_limit(history_limit: int) -> int:
    if not 1 <= history_limit <= MAX_MCP_HISTORY_LIMIT:
        raise ValueError(
            f"history_limit must be between 1 and {MAX_MCP_HISTORY_LIMIT}."
        )
    return history_limit


class MCPServiceError(RuntimeError):
    """Base class for CodeClone MCP service errors."""


class MCPServiceContractError(MCPServiceError):
    """Raised when an MCP request violates the CodeClone service contract."""


class MCPRunNotFoundError(MCPServiceError):
    """Raised when a requested MCP run is not available in the in-memory registry."""


class MCPFindingNotFoundError(MCPServiceError):
    """Raised when a requested finding id is not present in the selected run."""


class MCPGitDiffError(MCPServiceError):
    """Raised when changed paths cannot be resolved from a git ref."""


class _BufferConsole:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, *objects: object, **_kwargs: object) -> None:
        text = " ".join(str(obj) for obj in objects).strip()
        if text:
            self.messages.append(text)


@dataclass(frozen=True, slots=True)
class MCPAnalysisRequest:
    root: str | None = None
    analysis_mode: AnalysisMode = "full"
    respect_pyproject: bool = True
    changed_paths: tuple[str, ...] = ()
    git_diff_ref: str | None = None
    processes: int | None = None
    min_loc: int | None = None
    min_stmt: int | None = None
    block_min_loc: int | None = None
    block_min_stmt: int | None = None
    segment_min_loc: int | None = None
    segment_min_stmt: int | None = None
    api_surface: bool | None = None
    coverage_xml: str | None = None
    coverage_min: int | None = None
    complexity_threshold: int | None = None
    coupling_threshold: int | None = None
    cohesion_threshold: int | None = None
    baseline_path: str | None = None
    metrics_baseline_path: str | None = None
    max_baseline_size_mb: int | None = None
    cache_policy: CachePolicy = "reuse"
    cache_path: str | None = None
    max_cache_size_mb: int | None = None
    allow_external_artifacts: bool = False


@dataclass(frozen=True, slots=True)
class MCPGateRequest:
    run_id: str | None = None
    fail_on_new: bool = False
    fail_threshold: int = -1
    fail_complexity: int = -1
    fail_coupling: int = -1
    fail_cohesion: int = -1
    fail_cycles: bool = False
    fail_dead_code: bool = False
    fail_health: int = -1
    fail_on_new_metrics: bool = False
    fail_on_typing_regression: bool = False
    fail_on_docstring_regression: bool = False
    fail_on_api_break: bool = False
    fail_on_untested_hotspots: bool = False
    min_typing_coverage: int = -1
    min_docstring_coverage: int = -1
    coverage_min: int = DEFAULT_COVERAGE_MIN


@dataclass(frozen=True, slots=True)
class MCPRunRecord:
    run_id: str
    root: Path
    request: MCPAnalysisRequest
    comparison_settings: tuple[object, ...]
    report_document: dict[str, object]
    summary: dict[str, object]
    changed_paths: tuple[str, ...]
    changed_projection: dict[str, object] | None
    warnings: tuple[str, ...]
    failures: tuple[str, ...]
    func_clones_count: int
    block_clones_count: int
    project_metrics: ProjectMetrics | None
    coverage_join: CoverageJoinResult | None
    suggestions: tuple[Suggestion, ...]
    new_func: frozenset[str]
    new_block: frozenset[str]
    metrics_diff: MetricsDiff | None


class CodeCloneMCPRunStore:
    def __init__(self, *, history_limit: int = DEFAULT_MCP_HISTORY_LIMIT) -> None:
        self._history_limit = _validated_history_limit(history_limit)
        self._lock = RLock()
        self._records: OrderedDict[str, MCPRunRecord] = OrderedDict()
        self._latest_run_id: str | None = None
        self._pinned_run_ids: set[str] = set()

    def register(self, record: MCPRunRecord) -> MCPRunRecord:
        with self._lock:
            self._records.pop(record.run_id, None)
            self._records[record.run_id] = record
            self._records.move_to_end(record.run_id)
            self._latest_run_id = record.run_id
            self._prune_unpinned_locked()
        return record

    def get(self, run_id: str | None = None) -> MCPRunRecord:
        with self._lock:
            resolved_run_id = self._resolve_run_id(run_id)
            if resolved_run_id is None:
                raise MCPRunNotFoundError("No matching MCP analysis run is available.")
            return self._records[resolved_run_id]

    def _resolve_run_id(self, run_id: str | None) -> str | None:
        if run_id is None:
            return self._latest_run_id
        if run_id in self._records:
            return run_id
        matches = [
            candidate for candidate in self._records if candidate.startswith(run_id)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise MCPServiceContractError(
                f"Run id '{run_id}' is ambiguous in this MCP session."
            )
        return None

    def records(self) -> tuple[MCPRunRecord, ...]:
        with self._lock:
            return tuple(self._records.values())

    def pin(self, run_id: str) -> str:
        with self._lock:
            resolved_run_id = self._resolve_run_id(run_id)
            if resolved_run_id is None:
                raise MCPRunNotFoundError("No matching MCP analysis run is available.")
            self._pinned_run_ids.add(resolved_run_id)
            return resolved_run_id

    def unpin(self, run_id: str) -> None:
        with self._lock:
            resolved_run_id = self._resolve_run_id(run_id) or run_id
            self._pinned_run_ids.discard(resolved_run_id)
            self._prune_unpinned_locked()

    def clear(self) -> tuple[str, ...]:
        with self._lock:
            removed_run_ids = tuple(self._records.keys())
            self._records.clear()
            self._pinned_run_ids.clear()
            self._latest_run_id = None
            return removed_run_ids

    def _prune_unpinned_locked(self) -> None:
        while self._unpinned_count_locked() > self._history_limit:
            for run_id in tuple(self._records):
                if run_id in self._pinned_run_ids:
                    continue
                self._records.pop(run_id, None)
                if self._latest_run_id == run_id:
                    self._latest_run_id = next(reversed(self._records), None)
                break
            else:
                break
        self._pinned_run_ids.intersection_update(self._records)

    def _unpinned_count_locked(self) -> int:
        return sum(1 for run_id in self._records if run_id not in self._pinned_run_ids)


__all__ = [
    "CATEGORY_CLONE",
    "CATEGORY_COHESION",
    "CATEGORY_COMPLEXITY",
    "CATEGORY_COUPLING",
    "CATEGORY_DEAD_CODE",
    "CATEGORY_DEPENDENCY",
    "CATEGORY_STRUCTURAL",
    "CONFIDENCE_MEDIUM",
    "DEFAULT_BASELINE_PATH",
    "DEFAULT_BLOCK_MIN_LOC",
    "DEFAULT_BLOCK_MIN_STMT",
    "DEFAULT_COVERAGE_MIN",
    "DEFAULT_MAX_BASELINE_SIZE_MB",
    "DEFAULT_MAX_CACHE_SIZE_MB",
    "DEFAULT_MCP_HISTORY_LIMIT",
    "DEFAULT_MIN_LOC",
    "DEFAULT_MIN_STMT",
    "DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD",
    "DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD",
    "DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD",
    "DEFAULT_SEGMENT_MIN_LOC",
    "DEFAULT_SEGMENT_MIN_STMT",
    "EFFORT_EASY",
    "EFFORT_HARD",
    "EFFORT_MODERATE",
    "FAMILY_CLONE",
    "FAMILY_CLONES",
    "FAMILY_DEAD_CODE",
    "FAMILY_DESIGN",
    "FAMILY_STRUCTURAL",
    "REPORT_SCHEMA_VERSION",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "SOURCE_KIND_ORDER",
    "SOURCE_KIND_OTHER",
    "SOURCE_KIND_PRODUCTION",
    "_CHECK_TO_DIMENSION",
    "_COMPACT_ITEM_EMPTY_VALUES",
    "_COMPACT_ITEM_PATH_KEYS",
    "_CONFIDENCE_WEIGHT",
    "_DESIGN_CHECK_CONTEXT",
    "_EFFORT_WEIGHT",
    "_FOCUS_CHANGED_PATHS",
    "_FOCUS_PRODUCTION",
    "_FOCUS_REPOSITORY",
    "_HEALTH_SCOPE_REPOSITORY",
    "_HELP_TOPIC_SPECS",
    "_HOTLIST_REPORT_KEYS",
    "_MCP_CONFIG_KEYS",
    "_MCP_GOVERNANCE_CONFIG_KEYS",
    "_METRICS_DETAIL_FAMILY_ALIASES",
    "_NOVELTY_WEIGHT",
    "_REPORT_DUMMY_PATH",
    "_RUNTIME_WEIGHT",
    "_SEVERITY_WEIGHT",
    "_SHORT_RUN_ID_LENGTH",
    "_SOURCE_KIND_BREAKDOWN_ORDER",
    "_VALID_ANALYSIS_MODES",
    "_VALID_CACHE_POLICIES",
    "_VALID_COMPARISON_FOCUS",
    "_VALID_DETAIL_LEVELS",
    "_VALID_FINDING_FAMILIES",
    "_VALID_FINDING_NOVELTY",
    "_VALID_FINDING_SORT",
    "_VALID_HELP_DETAILS",
    "_VALID_HELP_TOPICS",
    "_VALID_HOTLIST_KINDS",
    "_VALID_METRICS_DETAIL_FAMILIES",
    "_VALID_PR_SUMMARY_FORMATS",
    "_VALID_REPORT_SECTIONS",
    "_VALID_SEVERITIES",
    "AnalysisMode",
    "Baseline",
    "Cache",
    "CachePolicy",
    "CacheStatus",
    "ChoiceT",
    "CodeCloneMCPRunStore",
    "ComparisonFocus",
    "ConfigValidationError",
    "DetailLevel",
    "FindingFamilyFilter",
    "FindingNoveltyFilter",
    "FindingSort",
    "FreshnessKind",
    "GatingResult",
    "HelpDetail",
    "HelpTopic",
    "HotlistKind",
    "Iterable",
    "MCPAnalysisRequest",
    "MCPFindingNotFoundError",
    "MCPGateRequest",
    "MCPRunNotFoundError",
    "MCPRunRecord",
    "MCPServiceContractError",
    "MCPServiceError",
    "Mapping",
    "MetricGateConfig",
    "MetricsDetailFamily",
    "MetricsDiff",
    "Namespace",
    "OrderedDict",
    "OutputPaths",
    "PRSummaryFormat",
    "Path",
    "RLock",
    "ReportSection",
    "Sequence",
    "_BufferConsole",
    "__version__",
    "_as_float",
    "_as_int",
    "_base_short_finding_id_payload",
    "_disambiguated_clone_short_ids_payload",
    "_disambiguated_short_finding_id_payload",
    "_evaluate_report_gates",
    "_git_diff_lines_payload",
    "_json_text_payload",
    "_leaf_symbol_name_payload",
    "_load_report_document_payload",
    "_suggestion_finding_id_payload",
    "_summarize_metrics_diff",
    "analyze",
    "bootstrap",
    "discover",
    "load_pyproject_config",
    "paginate",
    "process",
    "report",
    "resolve_finding_id",
    "short_id",
]
