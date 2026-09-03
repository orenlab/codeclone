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
from typing import TYPE_CHECKING, Final, Literal, TypeVar
from uuid import uuid4

import orjson

from ... import __version__
from ...api.config_delivery import (
    DeliverySurface,
    apply_repository_config,
    delivered_config_values,
    load_repository_config,
)
from ...api.execution_event import ExecutionEvent
from ...api.served_projection import (
    WITHHELD_PROOF_SECTIONS,
    ServedProjectionError,
    ServedReportProjection,
    ServingAnalysisContract,
    build_served_projection,
)
from ...baseline import Baseline
from ...cache.store import Cache
from ...cache.versioning import CacheStatus
from ...config.pyproject_loader import ConfigValidationError
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
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    DEFAULT_COVERAGE_MIN,
    DEFAULT_JSON_REPORT_PATH,
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    FAMILY_CLONES,
    REPORT_SCHEMA_VERSION,
)
from ...core._types import OutputPaths
from ...core.bootstrap import bootstrap
from ...core.discovery import discover
from ...core.parallelism import process
from ...core.pipeline import analyze
from ...core.reporting import report
from ...domain.findings import (
    ADVISORY_TIER_NAMES,
    ADVISORY_TIER_RECORD_KEYS,
    BASELINE_TRACKED_FAMILIES,
    CATEGORY_CLONE,
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CATEGORY_STRUCTURAL,
    FAMILY_CLONE,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_STRUCTURAL,
)
from ...domain.findings import (
    FAMILY_AUTHORITY as FAMILY_AUTHORITY,
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
from ...models import (
    CoverageJoinResult,
    FunctionRelationshipFacts,
    MetricsDiff,
    ModuleDep,
    Suggestion,
)
from ...observability import record_counter, span
from ...report.gates.evaluator import GateResult as GatingResult
from ...report.gates.evaluator import MetricGateConfig
from ...report.gates.evaluator import evaluate_gates as _evaluate_report_gates
from ...report.gates.evaluator import summarize_metrics_diff as _summarize_metrics_diff
from ...utils.coerce import as_float as _as_float
from ...utils.coerce import as_int as _as_int
from ...utils.git_diff import validate_git_diff_ref
from .messages.help_topics import HELP_TOPIC_SPECS as _HELP_TOPIC_SPECS
from .payloads import paginate, resolve_finding_id, short_id

if TYPE_CHECKING:
    pass

AnalysisMode = Literal["full", "clones_only"]
FreshnessKind = Literal["fresh", "mixed", "reused"]
HotlistKind = Literal[
    "most_actionable",
    "highest_spread",
    "highest_priority",
    "production_hotspots",
    "test_fixture_hotspots",
]
#: ``list_findings`` family vocabulary. The first six are the baseline-tracked
#: universe ``all`` sums; the last two are the advisory detection tiers, which
#: are reachable only by naming them and are deliberately absent from ``all``
#: (widening a published total onto records no baseline lane holds would be a
#: separate contract decision).
FindingFamilyFilter = Literal[
    "all",
    "clone",
    "structural",
    "dead_code",
    "design",
    "authority",
    "near_miss",
    "renamed_structure",
]
FindingNoveltyFilter = Literal["all", "new", "known", "unavailable"]
FindingSort = Literal["default", "priority", "severity", "spread"]
DetailLevel = Literal["summary", "normal", "full"]
ComparisonFocus = Literal["all", "clones", "structural", "metrics"]
PRSummaryFormat = Literal["markdown", "json"]
HelpTopic = Literal[
    "overview",
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
    "implementation_context",
    "verification_profiles",
    "observability",
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
    "semantic_authority",
    "god_modules",
    "overloaded_modules",
    "health",
]
ReportSection = Literal[
    "meta",
    "inventory",
    "findings",
    "metrics",
    "metrics_detail",
    "derived",
    "module_map",
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
# Which configuration this surface consumes is declared by the R3 door
# ``api.config_delivery``, which also applies it through the canonical resolver.
# The hand-maintained key allowlists that used to live here were a second
# delivery path: they bypassed the resolver, so autodetection, normalization and
# precedence never ran on MCP, and a key was absent either by policy or because
# nobody had added its name.
#
# A ``_RESOURCE_SECTION_MAP`` used to sit here, translating resource suffixes
# into report sections. Nothing ever read it — ``_render_resource`` dispatches
# on the suffix directly — so it was a second, silent record of the resource
# vocabulary, and its ``report.json -> all`` entry outlived the section it
# named. Resource routing has exactly one owner, and it is ``_render_resource``.
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
_VALID_FINDING_FAMILIES = frozenset(
    {
        "all",
        *BASELINE_TRACKED_FAMILIES,
        *ADVISORY_TIER_NAMES,
    }
)
_VALID_FINDING_NOVELTY = frozenset({"all", "new", "known", "unavailable"})
_VALID_FINDING_SORT = frozenset({"default", "priority", "severity", "spread"})
_VALID_DETAIL_LEVELS = frozenset({"summary", "normal", "full"})
#: check_authority sections. "violations" keeps the original contract;
#: "candidates" serves the discovery population as bounded pages only.
_VALID_AUTHORITY_SECTIONS = frozenset({"violations", "candidates"})
_VALID_COMPARISON_FOCUS = frozenset({"all", "clones", "structural", "metrics"})
_VALID_PR_SUMMARY_FORMATS = frozenset({"markdown", "json"})
_VALID_HELP_TOPICS = frozenset(
    {
        "overview",
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
        "implementation_context",
        "verification_profiles",
    }
)
_VALID_HELP_DETAILS = frozenset({"compact", "normal"})
DEFAULT_MCP_HISTORY_LIMIT = 4
MAX_MCP_HISTORY_LIMIT = 10
# Pinned runs are exempt from the history LRU, so without a ceiling an intent
# left behind on a failure path retains its whole run for the life of the
# session. The bound is deliberately well above plausible concurrent-intent
# counts: releasing a pin that a live intent still needs would break that
# intent, so this is a backstop against abandonment, not a working limit.
MAX_PINNED_MCP_RUNS = 10
DEFAULT_REPORT_SECTION: Final[ReportSection] = "meta"
# ``all`` is withdrawn, not forgotten. The whole document reached 37M tokens on
# this repository, so the tool stopped serving it — but the value stays a
# recognised input so that asking for it meets a typed in-band refusal naming
# the bounded sections and the on-disk projection, instead of a raised contract
# error that reads like a typo.
REMOVED_REPORT_SECTIONS: Final[frozenset[str]] = frozenset({"all"})
# The resource half of the same withdrawal. ``report.json`` served
# ``record.report_document`` verbatim, so it was the withdrawn ``all`` section
# wearing a URI, and it outlived that section by sitting on a different
# dispatch. It is unregistered on the server, and the suffix stays recognised
# here so that a client holding the old URI meets the same typed refusal rather
# than a path-shaped contract error.
REMOVED_RESOURCE_SUFFIXES: Final[frozenset[str]] = frozenset({"report.json"})
_VALID_REPORT_SECTIONS = frozenset(
    {
        "meta",
        "inventory",
        "findings",
        "metrics",
        "metrics_detail",
        "derived",
        "module_map",
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
        "semantic_authority",
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
    if clone_kind == CLONE_KIND_FUNCTION:
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
    alias = {CLONE_KIND_BLOCK: "blk", CLONE_KIND_SEGMENT: "seg"}.get(
        clone_kind, "clone"
    )
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


class MCPRunRootMismatchError(MCPServiceError):
    """Raised when a run exists, but under a root other than the required one.

    Distinct from :class:`MCPRunNotFoundError` on purpose: "this evidence
    belongs to another checkout" and "there is no such evidence" call for
    different answers, and collapsing them is how foreign evidence gets
    substituted silently.
    """


class MCPRunRootAmbiguityError(MCPServiceError):
    """Raised when a run id exists under several roots and none was named.

    Run ids are content-addressed, so two worktrees at the same commit share
    one. Choosing between them without being told which root is meant is a
    coin flip over whose evidence gets reported.
    """


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
    max_baseline_size_mb: int | None = None
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
    # Appended, never inserted: the field order of a public frozen dataclass is
    # a positional contract, and this selector arrived after the rest.
    # Optional, and only a selector: gate evaluation reads the resolved run
    # record, never this string.
    root: str | None = None


@dataclass(frozen=True, slots=True)
class MCPUnitLocation:
    qualname: str
    path: str
    start_line: int
    end_line: int


def mint_execution_event_id() -> str:
    """Mint the identity of one execution.

    An execution is an event, not a content address: two executions of one
    byte-identical tree are two events and must never share a name, across
    processes and across restarts (RFC 2026-09-02 §III.1: a random UUID, not a
    session ordinal -- accepted by the maintainer, 2026-09-03).  The value
    never enters ``run_id``, which names the report the execution produced.
    """

    return uuid4().hex


@dataclass(frozen=True, slots=True, kw_only=True)
class MCPRunRecord:
    """One served run: the index of a sealed report, and the execution behind it.

    ``run_id`` is the report's semantic identity; ``execution`` is the event
    and carries every per-execution fact.  This is step 4 of RFC 2026-09-02
    §III.8: the record no longer holds the report itself.  ``served_report``
    is the projection -- the sections this surface answers from, plus the
    typed analysis contract lifted out of the observation lanes -- and the
    proof it indexes lives on disk, whole, where its identity still matches
    its payload.  Keyword-only, because the field set changed shape and no
    positional caller exists.

    ``reachable_qualnames`` is the one fact the claim guard reads out of the
    run's project metrics, already in the shape it is read in; the metrics
    object itself, and above all the authority IR inside it, has no reader
    here and is not retained.
    """

    run_id: str
    root: Path
    request: MCPAnalysisRequest
    comparison_settings: tuple[object, ...]
    served_report: ServedReportProjection
    summary: dict[str, object]
    changed_paths: tuple[str, ...]
    changed_projection: dict[str, object] | None
    func_clones_count: int
    block_clones_count: int
    reachable_qualnames: frozenset[str]
    coverage_join: CoverageJoinResult | None
    suggestions: tuple[Suggestion, ...]
    new_func: frozenset[str]
    new_block: frozenset[str]
    metrics_diff: MetricsDiff | None
    execution: ExecutionEvent
    unit_inventory: tuple[MCPUnitLocation, ...] = ()
    relationship_facts: tuple[FunctionRelationshipFacts, ...] = ()
    module_imports: tuple[ModuleDep, ...] = ()


# The index of one semantic report under one checkout.  Content-addressed
# run ids collide between same-commit worktrees; the root is what tells those
# apart, and it belongs in the index -- never in the id itself.
MCPRunKey = tuple[Path, str]


def run_store_key(root: Path, run_id: str) -> MCPRunKey:
    """Build the index under which a report's executions are found."""

    return (root.resolve(), run_id)


class CodeCloneMCPRunStore:
    """Session-local executions, identified by ``execution_event_id``.

    The store holds EXECUTIONS.  ``(root, run_id)`` is an index onto the
    newest execution that produced that report under that checkout -- what a
    caller holding only a semantic id can name -- and never the address of an
    execution.  One report may have been produced by several executions, and
    an intent declared against one of them keeps resolving to that one after
    a later execution shares its name (RULING-2026-09-02).  Before this, the
    store held one record per key and replaced it on re-registration, so the
    before-run an intent pinned was silently overwritten by the after-run that
    shared its id -- measured live on 2026-09-03.

    There is deliberately no ``get(run_id)``.  Every resolution either names
    the root it requires (:meth:`get_for_root`), states that it genuinely does
    not constrain one (:meth:`resolve_any_root`, which fails closed when the
    id spans roots), or names the execution itself (:meth:`get_execution`).

    Bound: pinned executions (an intent's before-run) and the newest execution
    per report.  An unpinned execution that a newer execution of the same
    report supersedes is released at once -- nothing can name it any more --
    and the rest are pruned oldest-first past ``history_limit``.
    """

    def __init__(self, *, history_limit: int = DEFAULT_MCP_HISTORY_LIMIT) -> None:
        self._history_limit = _validated_history_limit(history_limit)
        self._lock = RLock()
        # Registration order, oldest first.
        self._executions: OrderedDict[str, MCPRunRecord] = OrderedDict()
        self._key_of: dict[str, MCPRunKey] = {}
        # The newest execution per (root, run_id): the index, not the address.
        self._latest_by_key: dict[MCPRunKey, str] = {}
        self._latest_execution_id: str | None = None
        # Monotonic registration ordinals, one per execution.  An execution is
        # registered once, so its ordinal never moves; the order between two
        # executions is the store's own evidence of which came later.
        self._registrations: dict[str, int] = {}
        self._registration_seq: int = 0
        # Insertion-ordered so the oldest pin is identifiable: the record
        # carries no timestamp, and pin order is the only evidence of which
        # pin has been held longest.  The value is a reference count -- several
        # live intents may hold one execution.
        self._pinned: OrderedDict[str, int] = OrderedDict()

    def register(self, record: MCPRunRecord) -> MCPRunRecord:
        event_id = record.execution.execution_event_id
        key = run_store_key(record.root, record.run_id)
        # This is where one agent's run silently disappears while another
        # agent is still holding its id. The span makes that a measured number
        # instead of an inference from a later "no run available" error.
        with span(name="mcp.run_store.register") as register_span, self._lock:
            held_before = frozenset(self._executions)
            if event_id in self._executions:
                # The same event again is the same event: the record it
                # carries is refreshed; its place, ordinal and pins are kept.
                # A record that moved to another report name releases the old
                # index entry, so no key keeps pointing at a record that no
                # longer answers to it.
                previous_key = self._key_of[event_id]
                if (
                    previous_key != key
                    and self._latest_by_key.get(previous_key) == event_id
                ):
                    self._latest_by_key.pop(previous_key, None)
                self._executions[event_id] = record
                self._key_of[event_id] = key
            else:
                self._executions[event_id] = record
                self._key_of[event_id] = key
                self._registration_seq += 1
                self._registrations[event_id] = self._registration_seq
            self._latest_by_key[key] = event_id
            self._latest_execution_id = event_id
            self._prune_unpinned_locked()
            retained = len(self._executions)
            register_span.set_counter("run_store_runs_retained", retained)
            register_span.set_counter(
                "run_store_runs_evicted",
                len(held_before - frozenset(self._executions)),
            )
        return record

    def is_latest_registration(self, run_id: str, *, root: Path) -> bool:
        """Is this report's newest execution the newest one held for ``root``?

        A run that a later analysis superseded is stale evidence even when it
        was itself registered fresh, so invariance never rests on one.
        """

        resolved_root = root.resolve()
        with self._lock:
            key = self._resolve_key_locked(run_id, root=resolved_root)
            if key is None:
                return False
            return key == self._resolve_key_locked(None, root=resolved_root)

    def registration_ordinal(
        self,
        run_id: str | None = None,
        *,
        root: Path,
    ) -> int | None:
        """The ordinal of the NEWEST execution of ``(root, run_id)``.

        Transitional, key-addressed: the execution-addressed answer is
        :meth:`execution_ordinal`.  This one stays until the durable event
        witness has passed its reboot test (RULING-2026-08-31 §I2b), for
        intents that carry no execution binding.  ``None`` means the report
        is not held under *root* at all, which is a refusal to answer rather
        than a claim about freshness.
        """

        resolved_root = root.resolve()
        with self._lock:
            key = self._resolve_key_locked(run_id, root=resolved_root)
            if key is None:
                return None
            return self._registrations.get(self._latest_by_key[key])

    def execution_ordinal(self, execution_event_id: str) -> int | None:
        """When this execution was registered; ``None`` when it is not held."""

        with self._lock:
            return self._registrations.get(execution_event_id)

    def is_latest_execution(self, execution_event_id: str, *, root: Path) -> bool:
        """Is this execution the newest one registered under ``root``?"""

        resolved_root = root.resolve()
        with self._lock:
            if execution_event_id not in self._executions:
                return False
            newest: str | None = None
            for event_id, key in self._key_of.items():
                if key[0] == resolved_root:
                    newest = event_id
            return newest == execution_event_id

    def holds_execution(self, execution_event_id: str | None) -> bool:
        with self._lock:
            return (
                execution_event_id is not None
                and execution_event_id in self._executions
            )

    def get_execution(self, execution_event_id: str) -> MCPRunRecord:
        """Resolve one execution by its own identity.

        This is the resolution an intent uses: the event it was declared
        against, whatever executions of the same report registered since.
        """

        with self._lock:
            record = self._executions.get(execution_event_id)
            if record is None:
                record_counter("run_store_selector_misses")
                raise MCPRunNotFoundError(
                    "No MCP analysis execution "
                    f"{execution_event_id!r} is available in this session."
                )
            record_counter("run_store_selector_hits")
            return record

    def get_for_root(
        self,
        run_id: str | None = None,
        *,
        root: Path,
    ) -> MCPRunRecord:
        """Resolve a report's newest execution, which must belong to ``root``.

        Raises :class:`MCPRunRootMismatchError` when the id is only known under
        a different root, so callers can tell "wrong checkout" from "no run".
        """

        resolved_root = root.resolve()
        with self._lock:
            key = self._resolve_key_locked(run_id, root=resolved_root)
            if key is not None:
                return self._executions[self._latest_by_key[key]]
            if run_id is not None and self._roots_holding_locked(run_id):
                raise MCPRunRootMismatchError(
                    f"Run id '{run_id}' belongs to a different repository root "
                    f"than {resolved_root}. Run ids are content-addressed and "
                    f"collide between checkouts at the same commit. Call "
                    f"analyze_repository(root='{resolved_root}') and use the "
                    f"run_id it returns."
                )
            raise MCPRunNotFoundError(
                f"No MCP analysis run is available for {resolved_root}. Call "
                f"analyze_repository(root='{resolved_root}') first."
            )

    def resolve_any_root(self, run_id: str | None = None) -> MCPRunRecord:
        """Resolve a run whose root the caller genuinely does not constrain.

        Fails closed when the id is held under more than one root: picking one
        would be exactly the silent substitution this store exists to prevent.
        """

        with self._lock:
            # These two exits answer without reaching _resolve_key_locked, so
            # they have to report their own outcome — an unconstrained lookup
            # that quietly finds nothing is precisely the case worth counting.
            if run_id is None:
                if self._latest_execution_id is None:
                    record_counter("run_store_selector_misses")
                    raise MCPRunNotFoundError(
                        "No matching MCP analysis run is available."
                    )
                record_counter("run_store_selector_hits")
                return self._executions[self._latest_execution_id]
            roots = self._roots_holding_locked(run_id)
            if len(roots) > 1:
                rendered = ", ".join(str(item) for item in sorted(roots))
                raise MCPRunRootAmbiguityError(
                    f"Run id '{run_id}' exists under several repository roots "
                    f"({rendered}); pass root to select one."
                )
            if not roots:
                record_counter("run_store_selector_misses")
                raise MCPRunNotFoundError("No matching MCP analysis run is available.")
            key = self._resolve_key_locked(run_id, root=next(iter(roots)))
            if key is None:
                raise MCPRunNotFoundError("No matching MCP analysis run is available.")
            return self._executions[self._latest_by_key[key]]

    def _resolve_key_locked(
        self,
        run_id: str | None,
        *,
        root: Path,
    ) -> MCPRunKey | None:
        # The single funnel every key lookup goes through, so hit/miss
        # telemetry is counted once per resolution and cannot drift between
        # call sites. The counters land on the enclosing tool span; outside
        # one they are inert.
        key = self._resolve_key_uncounted_locked(run_id, root=root)
        record_counter(
            "run_store_selector_hits"
            if key is not None
            else "run_store_selector_misses"
        )
        return key

    def _resolve_key_uncounted_locked(
        self,
        run_id: str | None,
        *,
        root: Path,
    ) -> MCPRunKey | None:
        if run_id is None:
            latest: MCPRunKey | None = None
            for key in self._key_of.values():
                if key[0] == root:
                    latest = key
            return latest
        exact = (root, run_id)
        if exact in self._latest_by_key:
            return exact
        matches = [
            key
            for key in self._latest_by_key
            if key[0] == root and key[1].startswith(run_id)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise MCPServiceContractError(
                f"Run id '{run_id}' is ambiguous in this MCP session."
            )
        return None

    def _roots_holding_locked(self, run_id: str) -> set[Path]:
        return {
            key[0]
            for key in self._latest_by_key
            if key[1] == run_id or key[1].startswith(run_id)
        }

    def records(self) -> tuple[MCPRunRecord, ...]:
        with self._lock:
            return tuple(self._executions.values())

    def pin_execution(self, execution_event_id: str) -> str:
        """Take a reference on one execution so pruning cannot drop it."""

        with self._lock:
            if execution_event_id not in self._executions:
                raise MCPRunNotFoundError("No matching MCP analysis run is available.")
            held = self._pinned.pop(execution_event_id, 0)
            self._pinned[execution_event_id] = held + 1
            self._release_pins_over_cap_locked()
            return execution_event_id

    def unpin_execution(self, execution_event_id: str) -> None:
        """Release one reference; the execution stays pinned while others hold it."""

        with self._lock:
            held = self._pinned.get(execution_event_id, 0) - 1
            if held > 0:
                self._pinned[execution_event_id] = held
            else:
                self._pinned.pop(execution_event_id, None)
            self._prune_unpinned_locked()

    def unpin(self, run_id: str, *, root: Path) -> None:
        """Release one reference on the newest execution of ``(root, run_id)``.

        Transitional, key-addressed: only an intent without an execution
        binding releases through here (one rebuilt from a persisted registry
        row, once that lane exists); every intent this session declares
        releases the execution it pinned, by :meth:`unpin_execution`.
        """

        resolved_root = root.resolve()
        with self._lock:
            key = self._resolve_key_locked(run_id, root=resolved_root)
            if key is not None:
                self.unpin_execution(self._latest_by_key[key])
            else:
                self._prune_unpinned_locked()

    def clear(self) -> tuple[str, ...]:
        with self._lock:
            removed_run_ids = tuple(
                record.run_id for record in self._executions.values()
            )
            self._executions.clear()
            self._key_of.clear()
            self._latest_by_key.clear()
            self._pinned.clear()
            self._registrations.clear()
            self._latest_execution_id = None
            return removed_run_ids

    def _forget_locked(self, execution_event_id: str) -> None:
        self._executions.pop(execution_event_id, None)
        self._registrations.pop(execution_event_id, None)
        self._pinned.pop(execution_event_id, None)
        key = self._key_of.pop(execution_event_id, None)
        if key is not None and self._latest_by_key.get(key) == execution_event_id:
            remaining = [
                event_id for event_id, held in self._key_of.items() if held == key
            ]
            if remaining:
                self._latest_by_key[key] = remaining[-1]
            else:
                self._latest_by_key.pop(key, None)
        if self._latest_execution_id == execution_event_id:
            self._latest_execution_id = next(reversed(self._executions), None)

    def _prune_unpinned_locked(self) -> None:
        # An unpinned execution that is no longer the newest of its report is
        # unreachable by name: nothing resolves to it, so it holds memory for
        # nobody.  Released first, before the history bound is applied.
        for event_id in tuple(self._executions):
            if event_id in self._pinned:
                continue
            if self._latest_by_key.get(self._key_of[event_id]) != event_id:
                self._forget_locked(event_id)
        while self._unpinned_count_locked() > self._history_limit:
            for event_id in tuple(self._executions):
                if event_id in self._pinned:
                    continue
                self._forget_locked(event_id)
                break
            else:
                break
        for event_id in tuple(self._pinned):
            if event_id not in self._executions:
                self._pinned.pop(event_id, None)

    def _release_pins_over_cap_locked(self) -> None:
        """Release the longest-held pins once the ceiling is exceeded.

        Oldest-first: a pin held across many later intents is the one most
        likely to belong to an abandoned intent. Released executions become
        ordinary history and the existing bound decides whether they survive.
        """

        while len(self._pinned) > MAX_PINNED_MCP_RUNS:
            self._pinned.popitem(last=False)
        self._prune_unpinned_locked()

    def _unpinned_count_locked(self) -> int:
        return sum(1 for event_id in self._executions if event_id not in self._pinned)


__all__ = [
    "ADVISORY_TIER_NAMES",
    "ADVISORY_TIER_RECORD_KEYS",
    "BASELINE_TRACKED_FAMILIES",
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
    "DEFAULT_REPORT_SECTION",
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
    "REMOVED_REPORT_SECTIONS",
    "REMOVED_RESOURCE_SUFFIXES",
    "REPORT_SCHEMA_VERSION",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "SOURCE_KIND_ORDER",
    "SOURCE_KIND_OTHER",
    "SOURCE_KIND_PRODUCTION",
    "WITHHELD_PROOF_SECTIONS",
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
    "_METRICS_DETAIL_FAMILY_ALIASES",
    "_NOVELTY_WEIGHT",
    "_REPORT_DUMMY_PATH",
    "_RUNTIME_WEIGHT",
    "_SEVERITY_WEIGHT",
    "_SHORT_RUN_ID_LENGTH",
    "_SOURCE_KIND_BREAKDOWN_ORDER",
    "_VALID_ANALYSIS_MODES",
    "_VALID_AUTHORITY_SECTIONS",
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
    "CacheStatus",
    "ChoiceT",
    "CodeCloneMCPRunStore",
    "ComparisonFocus",
    "ConfigValidationError",
    "DeliverySurface",
    "DetailLevel",
    "ExecutionEvent",
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
    "MCPRunKey",
    "MCPRunNotFoundError",
    "MCPRunRecord",
    "MCPRunRootAmbiguityError",
    "MCPRunRootMismatchError",
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
    "ServedProjectionError",
    "ServedReportProjection",
    "ServingAnalysisContract",
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
    "apply_repository_config",
    "bootstrap",
    "build_served_projection",
    "delivered_config_values",
    "discover",
    "load_repository_config",
    "mint_execution_event_id",
    "paginate",
    "process",
    "report",
    "resolve_finding_id",
    "short_id",
]
