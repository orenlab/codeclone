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
from typing import Final, Literal, cast

import orjson

from . import __version__
from ._cli_args import (
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
from ._cli_baselines import (
    CloneBaselineState,
    MetricsBaselineState,
    probe_metrics_baseline_section,
    resolve_clone_baseline_state,
    resolve_metrics_baseline_state,
)
from ._cli_config import ConfigValidationError, load_pyproject_config
from ._cli_meta import _build_report_meta, _current_report_timestamp_utc
from ._cli_runtime import (
    resolve_cache_path,
    resolve_cache_status,
    validate_numeric_args,
)
from ._coerce import as_float as _as_float
from ._coerce import as_int as _as_int
from .baseline import Baseline
from .cache import Cache, CacheStatus
from .contracts import (
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    DOCS_URL,
    REPORT_SCHEMA_VERSION,
    ExitCode,
)
from .domain.findings import (
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
from .domain.quality import (
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
from .domain.source_scope import (
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_MIXED,
    SOURCE_KIND_ORDER,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)
from .models import MetricsDiff, ProjectMetrics, Suggestion
from .pipeline import (
    GatingResult,
    MetricGateConfig,
    OutputPaths,
    analyze,
    bootstrap,
    discover,
    metric_gate_reasons,
    process,
    report,
)
from .report.json_contract import (
    clone_group_id,
    dead_code_group_id,
    design_group_id,
    structural_group_id,
)

AnalysisMode = Literal["full", "clones_only"]
CachePolicy = Literal["reuse", "refresh", "off"]
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
    "latest_runs",
    "review_state",
    "changed_scope",
]
HelpDetail = Literal["compact", "normal"]
MetricsDetailFamily = Literal[
    "complexity",
    "coupling",
    "cohesion",
    "dependencies",
    "dead_code",
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

_LEGACY_CACHE_PATH = Path("~/.cache/codeclone/cache.json").expanduser()
_REPORT_DUMMY_PATH = Path(".cache/codeclone/report.json")
_HEALTH_SCOPE_REPOSITORY: Final[HealthScope] = "repository"
_FOCUS_REPOSITORY: Final[SummaryFocus] = "repository"
_FOCUS_PRODUCTION: Final[SummaryFocus] = "production"
_FOCUS_CHANGED_PATHS: Final[SummaryFocus] = "changed_paths"
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
_VALID_CACHE_POLICIES = frozenset({"reuse", "refresh", "off"})
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
        "latest_runs",
        "review_state",
        "changed_scope",
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
_VALID_METRICS_DETAIL_FAMILIES = frozenset(
    {
        "complexity",
        "coupling",
        "cohesion",
        "dependencies",
        "dead_code",
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


@dataclass(frozen=True)
class MCPHelpTopicSpec:
    summary: str
    key_points: tuple[str, ...]
    recommended_tools: tuple[str, ...]
    doc_links: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...] = ()
    anti_patterns: tuple[str, ...] = ()


_MCP_BOOK_URL: Final = f"{DOCS_URL}book/"
_MCP_GUIDE_URL: Final = f"{DOCS_URL}mcp/"
_MCP_INTERFACE_DOC_LINK: Final[tuple[str, str]] = (
    "MCP interface contract",
    f"{_MCP_BOOK_URL}20-mcp-interface/",
)
_BASELINE_DOC_LINK: Final[tuple[str, str]] = (
    "Baseline contract",
    f"{_MCP_BOOK_URL}06-baseline/",
)
_CONFIG_DOC_LINK: Final[tuple[str, str]] = (
    "Config and defaults",
    f"{_MCP_BOOK_URL}04-config-and-defaults/",
)
_PIPELINE_DOC_LINK: Final[tuple[str, str]] = (
    "Core pipeline",
    f"{_MCP_BOOK_URL}05-core-pipeline/",
)
_SUPPRESSIONS_DOC_LINK: Final[tuple[str, str]] = (
    "Inline suppressions contract",
    f"{_MCP_BOOK_URL}19-inline-suppressions/",
)
_MCP_GUIDE_DOC_LINK: Final[tuple[str, str]] = ("MCP usage guide", _MCP_GUIDE_URL)
_HELP_TOPIC_SPECS: Final[dict[str, MCPHelpTopicSpec]] = {
    "workflow": MCPHelpTopicSpec(
        summary=(
            "CodeClone MCP is triage-first and budget-aware. Start with a "
            "summary or production triage, then narrow through hotspots or "
            "focused checks before opening one finding in detail."
        ),
        key_points=(
            "Recommended first pass: analyze_repository or analyze_changed_paths.",
            (
                "Start with default or pyproject-resolved thresholds; lower them "
                "only for an explicit higher-sensitivity follow-up pass."
            ),
            (
                "Use get_run_summary or get_production_triage before broad "
                "finding listing."
            ),
            (
                "Prefer list_hotspots or focused check_* tools over "
                "list_findings on noisy repositories."
            ),
            ("Use get_finding and get_remediation only after selecting an issue."),
            (
                "get_report_section(section='all') is an exception path, not "
                "a default first step."
            ),
        ),
        recommended_tools=(
            "analyze_repository",
            "analyze_changed_paths",
            "get_run_summary",
            "get_production_triage",
            "list_hotspots",
            "check_clones",
            "check_dead_code",
            "get_finding",
            "get_remediation",
        ),
        doc_links=(_MCP_INTERFACE_DOC_LINK, _MCP_GUIDE_DOC_LINK),
        warnings=(
            (
                "Broad list_findings calls burn context quickly on large or "
                "noisy repositories."
            ),
            (
                "Prefer generate_pr_summary(format='markdown') unless machine "
                "JSON is explicitly required."
            ),
        ),
        anti_patterns=(
            "Starting exploration with list_findings on a noisy repository.",
            "Using get_report_section(section='all') as the default first step.",
            (
                "Escalating detail on larger lists instead of opening one "
                "finding with get_finding."
            ),
        ),
    ),
    "analysis_profile": MCPHelpTopicSpec(
        summary=(
            "CodeClone default analysis is intentionally conservative: stable "
            "first-pass review, baseline-aware governance, and CI-friendly "
            "signal over maximum local sensitivity."
        ),
        key_points=(
            (
                "Default thresholds are intentionally conservative and "
                "production-friendly."
            ),
            (
                "A clean default run does not rule out smaller local "
                "duplication or repetition."
            ),
            (
                "Lowering thresholds increases sensitivity and can surface "
                "smaller functions, tighter windows, and finer local signals."
            ),
            (
                "Lower-threshold runs are best for exploratory local review, "
                "not as a silent replacement for the default governance profile."
            ),
            "Interpret results in the context of the active threshold profile.",
        ),
        recommended_tools=(
            "analyze_repository",
            "analyze_changed_paths",
            "get_run_summary",
            "compare_runs",
        ),
        doc_links=(
            _CONFIG_DOC_LINK,
            _PIPELINE_DOC_LINK,
            _MCP_INTERFACE_DOC_LINK,
        ),
        warnings=(
            (
                "Do not treat a default-threshold run as proof that no smaller "
                "local clone or repetition exists."
            ),
            (
                "Lower-threshold runs usually increase noise and should be read "
                "as higher-sensitivity exploratory passes."
            ),
            "Run comparisons are most meaningful when profiles are aligned.",
        ),
        anti_patterns=(
            (
                "Assuming a clean default pass means no finer-grained "
                "duplication exists anywhere in the repository."
            ),
            (
                "Lowering thresholds for exploration and then interpreting the "
                "result as if it had the same meaning as the conservative "
                "default pass."
            ),
            (
                "Mixing low-threshold exploratory output into baseline or CI "
                "reasoning without acknowledging the profile change."
            ),
        ),
    ),
    "suppressions": MCPHelpTopicSpec(
        summary=(
            "CodeClone supports explicit inline suppressions for selected "
            "findings. They are local policy, not analysis truth, and should "
            "stay narrow and declaration-scoped."
        ),
        key_points=(
            "Current syntax uses codeclone: ignore[rule-id,...].",
            "Binding is declaration-scoped: def, async def, or class.",
            (
                "Supported placement is the previous line or inline on the "
                "declaration or header line."
            ),
            (
                "Suppressions are target-specific and do not imply file-wide "
                "or cascading scope."
            ),
            (
                "Use suppressions for accepted dynamic or runtime false "
                "positives, not to hide broad classes of debt."
            ),
        ),
        recommended_tools=("get_finding", "get_remediation"),
        doc_links=(_SUPPRESSIONS_DOC_LINK, _MCP_INTERFACE_DOC_LINK),
        warnings=(
            (
                "MCP explains suppression semantics but never creates or "
                "updates suppressions."
            ),
        ),
        anti_patterns=(
            "Treating suppressions as file-wide or inherited state.",
            (
                "Using suppressions to hide broad structural debt instead of "
                "accepted false positives."
            ),
        ),
    ),
    "baseline": MCPHelpTopicSpec(
        summary=(
            "A baseline is CodeClone's accepted comparison snapshot for clones "
            "and optional metrics. It separates known debt from new regressions "
            "and is trust-checked before use."
        ),
        key_points=(
            (
                "Canonical baseline schema is v2.0 with meta and clone keys; "
                "metrics may be embedded for unified flows."
            ),
            (
                "Compatibility depends on generator identity, supported "
                "schema version, fingerprint version, python tag, and payload "
                "integrity."
            ),
            (
                "Known means already present in the trusted baseline; new "
                "means not accepted by baseline."
            ),
            (
                "In CI and gating contexts, untrusted baseline states are "
                "contract errors rather than soft warnings."
            ),
            "MCP is read-only and does not update or rewrite baselines.",
        ),
        recommended_tools=("get_run_summary", "evaluate_gates", "compare_runs"),
        doc_links=(_BASELINE_DOC_LINK,),
        warnings=(
            "Baseline trust semantics directly affect new-vs-known classification.",
        ),
        anti_patterns=(
            "Treating baseline as mutable MCP session state.",
            "Assuming an untrusted baseline is only cosmetic in CI contexts.",
        ),
    ),
    "latest_runs": MCPHelpTopicSpec(
        summary=(
            "latest/* resources point to the most recent analysis run in the "
            "current MCP session. They are convenience handles, not persistent "
            "truth anchors."
        ),
        key_points=(
            "Run history is in-memory only and bounded by history-limit.",
            "The latest pointer moves when a newer analyze_* call registers a run.",
            "A fresh repository state requires a fresh analyze run.",
            (
                "Short run ids are convenience handles derived from canonical "
                "run identity."
            ),
            (
                "Do not assume latest/* is globally current outside the "
                "active MCP session."
            ),
        ),
        recommended_tools=(
            "analyze_repository",
            "analyze_changed_paths",
            "get_run_summary",
            "compare_runs",
        ),
        doc_links=(_MCP_INTERFACE_DOC_LINK, _MCP_GUIDE_DOC_LINK),
        warnings=(
            (
                "latest/* can point at a different repository after a later "
                "analyze call in the same session."
            ),
        ),
        anti_patterns=(
            (
                "Assuming latest/* remains tied to one repository across the "
                "whole client session."
            ),
            (
                "Using latest/* as a substitute for starting a fresh run when "
                "freshness matters."
            ),
        ),
    ),
    "review_state": MCPHelpTopicSpec(
        summary=(
            "Reviewed state in MCP is session-local workflow state. It helps "
            "long sessions track review progress without modifying canonical "
            "findings, baseline, or persisted artifacts."
        ),
        key_points=(
            "Review markers are in-memory only.",
            "They do not change report truth, finding identity, or CI semantics.",
            "They are useful for triage workflows across long sessions.",
            (
                "They should not be interpreted as acceptance, suppression, "
                "or baseline update."
            ),
        ),
        recommended_tools=(
            "list_hotspots",
            "get_finding",
            "mark_finding_reviewed",
            "list_reviewed_findings",
        ),
        doc_links=(_MCP_INTERFACE_DOC_LINK, _MCP_GUIDE_DOC_LINK),
        warnings=(
            "Reviewed markers disappear when the MCP session is cleared or restarted.",
        ),
        anti_patterns=(
            "Treating reviewed state as a persistent acceptance signal.",
            "Assuming reviewed findings are removed from canonical report truth.",
        ),
    ),
    "changed_scope": MCPHelpTopicSpec(
        summary=(
            "Changed-scope analysis narrows review to findings that touch a "
            "selected change set. It is for PR and patch review, not a "
            "replacement for full canonical analysis."
        ),
        key_points=(
            (
                "Use analyze_changed_paths with explicit changed_paths or "
                "git_diff_ref for review-focused runs."
            ),
            (
                "Start with the same conservative profile as the default "
                "review, then lower thresholds only when you explicitly want "
                "a higher-sensitivity changed-files pass."
            ),
            (
                "Changed-scope is best for asking what new issues touch "
                "modified files and whether anything should block CI."
            ),
            "Prefer production triage and hotspot views before broad listing.",
            "If repository-wide truth is needed, run full analysis first.",
        ),
        recommended_tools=(
            "analyze_changed_paths",
            "get_run_summary",
            "get_production_triage",
            "evaluate_gates",
            "generate_pr_summary",
        ),
        doc_links=(_MCP_INTERFACE_DOC_LINK, _MCP_GUIDE_DOC_LINK),
        warnings=(
            (
                "Changed-scope narrows review focus; it does not replace the "
                "full canonical report for repository-wide truth."
            ),
        ),
        anti_patterns=(
            "Using changed-scope as if it were the only source of repository truth.",
            (
                "Starting changed-files review with broad listing instead of "
                "compact triage."
            ),
        ),
    ),
}


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
    if git_diff_ref.startswith("-"):
        raise MCPGitDiffError(
            f"Invalid git diff ref '{git_diff_ref}': must not start with '-'."
        )
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", git_diff_ref, "--"],
            cwd=root_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise MCPGitDiffError(
            f"Unable to resolve changed paths from git diff ref '{git_diff_ref}'."
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
    complexity_threshold: int | None = None
    coupling_threshold: int | None = None
    cohesion_threshold: int | None = None
    baseline_path: str | None = None
    metrics_baseline_path: str | None = None
    max_baseline_size_mb: int | None = None
    cache_policy: CachePolicy = "reuse"
    cache_path: str | None = None
    max_cache_size_mb: int | None = None


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

    def register(self, record: MCPRunRecord) -> MCPRunRecord:
        with self._lock:
            self._records.pop(record.run_id, None)
            self._records[record.run_id] = record
            self._records.move_to_end(record.run_id)
            self._latest_run_id = record.run_id
            while len(self._records) > self._history_limit:
                self._records.popitem(last=False)
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

    def clear(self) -> tuple[str, ...]:
        with self._lock:
            removed_run_ids = tuple(self._records.keys())
            self._records.clear()
            self._latest_run_id = None
            return removed_run_ids


class CodeCloneMCPService:
    def __init__(self, *, history_limit: int = DEFAULT_MCP_HISTORY_LIMIT) -> None:
        self._runs = CodeCloneMCPRunStore(history_limit=history_limit)
        self._state_lock = RLock()
        self._review_state: dict[str, OrderedDict[str, str | None]] = {}
        self._last_gate_results: dict[str, dict[str, object]] = {}
        self._spread_max_cache: dict[str, int] = {}

    def analyze_repository(self, request: MCPAnalysisRequest) -> dict[str, object]:
        self._validate_analysis_request(request)
        root_path = self._resolve_root(request.root)
        analysis_started_at_utc = _current_report_timestamp_utc()
        changed_paths = self._resolve_request_changed_paths(
            root_path=root_path,
            changed_paths=request.changed_paths,
            git_diff_ref=request.git_diff_ref,
        )
        args = self._build_args(root_path=root_path, request=request)
        (
            baseline_path,
            baseline_exists,
            metrics_baseline_path,
            metrics_baseline_exists,
            shared_baseline_payload,
        ) = self._resolve_baseline_inputs(root_path=root_path, args=args)
        cache_path = self._resolve_cache_path(root_path=root_path, args=args)
        cache = self._build_cache(
            root_path=root_path,
            args=args,
            cache_path=cache_path,
            policy=request.cache_policy,
        )
        console = _BufferConsole()

        boot = bootstrap(
            args=args,
            root=root_path,
            output_paths=OutputPaths(json=_REPORT_DUMMY_PATH),
            cache_path=cache_path,
        )
        discovery_result = discover(boot=boot, cache=cache)
        processing_result = process(boot=boot, discovery=discovery_result, cache=cache)
        analysis_result = analyze(
            boot=boot,
            discovery=discovery_result,
            processing=processing_result,
        )

        clone_baseline_state = resolve_clone_baseline_state(
            args=args,
            baseline_path=baseline_path,
            baseline_exists=baseline_exists,
            func_groups=analysis_result.func_groups,
            block_groups=analysis_result.block_groups,
            codeclone_version=__version__,
            console=console,
            shared_baseline_payload=(
                shared_baseline_payload
                if metrics_baseline_path == baseline_path
                else None
            ),
        )
        metrics_baseline_state = resolve_metrics_baseline_state(
            args=args,
            metrics_baseline_path=metrics_baseline_path,
            metrics_baseline_exists=metrics_baseline_exists,
            baseline_updated_path=clone_baseline_state.updated_path,
            project_metrics=analysis_result.project_metrics,
            console=console,
            shared_baseline_payload=(
                shared_baseline_payload
                if metrics_baseline_path == baseline_path
                else None
            ),
        )

        cache_status, cache_schema_version = resolve_cache_status(cache)
        report_meta = _build_report_meta(
            codeclone_version=__version__,
            scan_root=root_path,
            baseline_path=baseline_path,
            baseline=clone_baseline_state.baseline,
            baseline_loaded=clone_baseline_state.loaded,
            baseline_status=clone_baseline_state.status.value,
            cache_path=cache_path,
            cache_used=cache_status == CacheStatus.OK,
            cache_status=cache_status.value,
            cache_schema_version=cache_schema_version,
            files_skipped_source_io=len(processing_result.source_read_failures),
            metrics_baseline_path=metrics_baseline_path,
            metrics_baseline=metrics_baseline_state.baseline,
            metrics_baseline_loaded=metrics_baseline_state.loaded,
            metrics_baseline_status=metrics_baseline_state.status.value,
            health_score=(
                analysis_result.project_metrics.health.total
                if analysis_result.project_metrics is not None
                else None
            ),
            health_grade=(
                analysis_result.project_metrics.health.grade
                if analysis_result.project_metrics is not None
                else None
            ),
            analysis_mode=request.analysis_mode,
            metrics_computed=self._metrics_computed(request.analysis_mode),
            min_loc=_as_int(args.min_loc, DEFAULT_MIN_LOC),
            min_stmt=_as_int(args.min_stmt, DEFAULT_MIN_STMT),
            block_min_loc=_as_int(args.block_min_loc, DEFAULT_BLOCK_MIN_LOC),
            block_min_stmt=_as_int(args.block_min_stmt, DEFAULT_BLOCK_MIN_STMT),
            segment_min_loc=_as_int(args.segment_min_loc, DEFAULT_SEGMENT_MIN_LOC),
            segment_min_stmt=_as_int(args.segment_min_stmt, DEFAULT_SEGMENT_MIN_STMT),
            design_complexity_threshold=_as_int(
                getattr(
                    args,
                    "design_complexity_threshold",
                    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
                ),
                DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
            ),
            design_coupling_threshold=_as_int(
                getattr(
                    args,
                    "design_coupling_threshold",
                    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
                ),
                DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
            ),
            design_cohesion_threshold=_as_int(
                getattr(
                    args,
                    "design_cohesion_threshold",
                    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
                ),
                DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
            ),
            analysis_started_at_utc=analysis_started_at_utc,
            report_generated_at_utc=_current_report_timestamp_utc(),
        )

        baseline_for_diff = (
            clone_baseline_state.baseline
            if clone_baseline_state.trusted_for_diff
            else Baseline(baseline_path)
        )
        new_func, new_block = baseline_for_diff.diff(
            analysis_result.func_groups,
            analysis_result.block_groups,
        )
        metrics_diff = None
        if (
            analysis_result.project_metrics is not None
            and metrics_baseline_state.trusted_for_diff
        ):
            metrics_diff = metrics_baseline_state.baseline.diff(
                analysis_result.project_metrics
            )

        report_artifacts = report(
            boot=boot,
            discovery=discovery_result,
            processing=processing_result,
            analysis=analysis_result,
            report_meta=report_meta,
            new_func=new_func,
            new_block=new_block,
            metrics_diff=metrics_diff,
        )
        report_json = report_artifacts.json
        if report_json is None:
            raise MCPServiceError("CodeClone MCP expected a canonical JSON report.")
        report_document = self._load_report_document(report_json)
        run_id = self._report_digest(report_document)

        warning_items = set(console.messages)
        if cache.load_warning:
            warning_items.add(cache.load_warning)
        warning_items.update(discovery_result.skipped_warnings)
        warnings = tuple(sorted(warning_items))
        failures = tuple(
            sorted(
                {
                    *processing_result.failed_files,
                    *processing_result.source_read_failures,
                }
            )
        )

        base_summary = self._build_run_summary_payload(
            run_id=run_id,
            root_path=root_path,
            request=request,
            report_document=report_document,
            baseline_state=clone_baseline_state,
            metrics_baseline_state=metrics_baseline_state,
            cache_status=cache_status,
            new_func=new_func,
            new_block=new_block,
            metrics_diff=metrics_diff,
            warnings=warnings,
            failures=failures,
        )
        provisional_record = MCPRunRecord(
            run_id=run_id,
            root=root_path,
            request=request,
            comparison_settings=self._comparison_settings(args=args, request=request),
            report_document=report_document,
            summary=base_summary,
            changed_paths=changed_paths,
            changed_projection=None,
            warnings=warnings,
            failures=failures,
            func_clones_count=analysis_result.func_clones_count,
            block_clones_count=analysis_result.block_clones_count,
            project_metrics=analysis_result.project_metrics,
            suggestions=analysis_result.suggestions,
            new_func=frozenset(new_func),
            new_block=frozenset(new_block),
            metrics_diff=metrics_diff,
        )
        changed_projection = self._build_changed_projection(provisional_record)
        summary = self._augment_summary_with_changed(
            summary=base_summary,
            changed_paths=changed_paths,
            changed_projection=changed_projection,
        )
        record = MCPRunRecord(
            run_id=run_id,
            root=root_path,
            request=request,
            comparison_settings=self._comparison_settings(args=args, request=request),
            report_document=report_document,
            summary=summary,
            changed_paths=changed_paths,
            changed_projection=changed_projection,
            warnings=warnings,
            failures=failures,
            func_clones_count=analysis_result.func_clones_count,
            block_clones_count=analysis_result.block_clones_count,
            project_metrics=analysis_result.project_metrics,
            suggestions=analysis_result.suggestions,
            new_func=frozenset(new_func),
            new_block=frozenset(new_block),
            metrics_diff=metrics_diff,
        )
        self._runs.register(record)
        self._prune_session_state()
        return self._summary_payload(record.summary, record=record)

    def analyze_changed_paths(self, request: MCPAnalysisRequest) -> dict[str, object]:
        if not request.changed_paths and request.git_diff_ref is None:
            raise MCPServiceContractError(
                "analyze_changed_paths requires changed_paths or git_diff_ref."
            )
        analysis_summary = self.analyze_repository(request)
        record = self._runs.get(str(analysis_summary.get("run_id", "")) or None)
        return self._changed_analysis_payload(record)

    def get_run_summary(self, run_id: str | None = None) -> dict[str, object]:
        record = self._runs.get(run_id)
        return self._summary_payload(record.summary, record=record)

    def compare_runs(
        self,
        *,
        run_id_before: str,
        run_id_after: str | None = None,
        focus: ComparisonFocus = "all",
    ) -> dict[str, object]:
        validated_focus = cast(
            "ComparisonFocus",
            self._validate_choice("focus", focus, _VALID_COMPARISON_FOCUS),
        )
        before = self._runs.get(run_id_before)
        after = self._runs.get(run_id_after)
        before_findings = self._comparison_index(before, focus=validated_focus)
        after_findings = self._comparison_index(after, focus=validated_focus)
        before_ids = set(before_findings)
        after_ids = set(after_findings)
        regressions = sorted(after_ids - before_ids)
        improvements = sorted(before_ids - after_ids)
        common = before_ids & after_ids
        health_before = self._summary_health_score(before.summary)
        health_after = self._summary_health_score(after.summary)
        comparability = self._comparison_scope(before=before, after=after)
        comparable = bool(comparability["comparable"])
        health_delta = (
            health_after - health_before
            if comparable and health_before is not None and health_after is not None
            else None
        )
        verdict = (
            self._comparison_verdict(
                regressions=len(regressions),
                improvements=len(improvements),
                health_delta=health_delta,
            )
            if comparable
            else "incomparable"
        )
        regressions_payload = (
            [
                self._comparison_finding_card(
                    after,
                    after_findings[finding_id],
                )
                for finding_id in regressions
            ]
            if comparable
            else []
        )
        improvements_payload = (
            [
                self._comparison_finding_card(
                    before,
                    before_findings[finding_id],
                )
                for finding_id in improvements
            ]
            if comparable
            else []
        )
        payload: dict[str, object] = {
            "before": {
                "run_id": self._short_run_id(before.run_id),
                "health": health_before,
            },
            "after": {
                "run_id": self._short_run_id(after.run_id),
                "health": health_after,
            },
            "comparable": comparable,
            "health_delta": health_delta,
            "verdict": verdict,
            "regressions": regressions_payload,
            "improvements": improvements_payload,
            "unchanged": len(common) if comparable else None,
            "summary": self._comparison_summary_text(
                comparable=comparable,
                comparability_reason=str(comparability["reason"]),
                regressions=len(regressions),
                improvements=len(improvements),
                health_delta=health_delta,
            ),
        }
        if not comparable:
            payload["reason"] = comparability["reason"]
        return payload

    def evaluate_gates(self, request: MCPGateRequest) -> dict[str, object]:
        record = self._runs.get(request.run_id)
        gate_result = self._evaluate_gate_snapshot(record=record, request=request)
        result = {
            "run_id": self._short_run_id(record.run_id),
            "would_fail": gate_result.exit_code != 0,
            "exit_code": gate_result.exit_code,
            "reasons": list(gate_result.reasons),
            "config": {
                "fail_on_new": request.fail_on_new,
                "fail_threshold": request.fail_threshold,
                "fail_complexity": request.fail_complexity,
                "fail_coupling": request.fail_coupling,
                "fail_cohesion": request.fail_cohesion,
                "fail_cycles": request.fail_cycles,
                "fail_dead_code": request.fail_dead_code,
                "fail_health": request.fail_health,
                "fail_on_new_metrics": request.fail_on_new_metrics,
            },
        }
        with self._state_lock:
            self._last_gate_results[record.run_id] = dict(result)
        return result

    def _evaluate_gate_snapshot(
        self,
        *,
        record: MCPRunRecord,
        request: MCPGateRequest,
    ) -> GatingResult:
        reasons: list[str] = []
        if record.project_metrics is not None:
            metric_reasons = metric_gate_reasons(
                project_metrics=record.project_metrics,
                metrics_diff=record.metrics_diff,
                config=MetricGateConfig(
                    fail_complexity=request.fail_complexity,
                    fail_coupling=request.fail_coupling,
                    fail_cohesion=request.fail_cohesion,
                    fail_cycles=request.fail_cycles,
                    fail_dead_code=request.fail_dead_code,
                    fail_health=request.fail_health,
                    fail_on_new_metrics=request.fail_on_new_metrics,
                ),
            )
            reasons.extend(f"metric:{reason}" for reason in metric_reasons)

        if request.fail_on_new and (record.new_func or record.new_block):
            reasons.append("clone:new")

        total_clone_groups = record.func_clones_count + record.block_clones_count
        if 0 <= request.fail_threshold < total_clone_groups:
            reasons.append(
                f"clone:threshold:{total_clone_groups}:{request.fail_threshold}"
            )

        if reasons:
            return GatingResult(
                exit_code=int(ExitCode.GATING_FAILURE),
                reasons=tuple(reasons),
            )
        return GatingResult(exit_code=int(ExitCode.SUCCESS), reasons=())

    def get_report_section(
        self,
        *,
        run_id: str | None = None,
        section: ReportSection = "all",
        family: MetricsDetailFamily | None = None,
        path: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, object]:
        validated_section = cast(
            "ReportSection",
            self._validate_choice("section", section, _VALID_REPORT_SECTIONS),
        )
        record = self._runs.get(run_id)
        report_document = record.report_document
        if validated_section == "all":
            return dict(report_document)
        if validated_section == "changed":
            if record.changed_projection is None:
                raise MCPServiceContractError(
                    "Report section 'changed' is not available in this run."
                )
            return dict(record.changed_projection)
        if validated_section == "metrics":
            metrics = self._as_mapping(report_document.get("metrics"))
            return {"summary": dict(self._as_mapping(metrics.get("summary")))}
        if validated_section == "metrics_detail":
            metrics = self._as_mapping(report_document.get("metrics"))
            if not metrics:
                raise MCPServiceContractError(
                    "Report section 'metrics_detail' is not available in this run."
                )
            validated_family_input = self._validate_optional_choice(
                "family",
                family,
                _VALID_METRICS_DETAIL_FAMILIES,
            )
            normalized_family = (
                _METRICS_DETAIL_FAMILY_ALIASES.get(
                    str(validated_family_input),
                    str(validated_family_input),
                )
                if validated_family_input is not None
                else None
            )
            validated_family = cast("MetricsDetailFamily | None", normalized_family)
            return self._metrics_detail_payload(
                metrics=metrics,
                family=validated_family,
                path=path,
                offset=offset,
                limit=limit,
            )
        if validated_section == "derived":
            return self._derived_section_payload(record)
        payload = report_document.get(validated_section)
        if not isinstance(payload, Mapping):
            raise MCPServiceContractError(
                f"Report section '{validated_section}' is not available in this run."
            )
        return dict(payload)

    def list_findings(
        self,
        *,
        run_id: str | None = None,
        family: FindingFamilyFilter = "all",
        category: str | None = None,
        severity: str | None = None,
        source_kind: str | None = None,
        novelty: FindingNoveltyFilter = "all",
        sort_by: FindingSort = "default",
        detail_level: DetailLevel = "summary",
        changed_paths: Sequence[str] = (),
        git_diff_ref: str | None = None,
        exclude_reviewed: bool = False,
        offset: int = 0,
        limit: int = 50,
        max_results: int | None = None,
    ) -> dict[str, object]:
        validated_family = cast(
            "FindingFamilyFilter",
            self._validate_choice("family", family, _VALID_FINDING_FAMILIES),
        )
        validated_novelty = cast(
            "FindingNoveltyFilter",
            self._validate_choice("novelty", novelty, _VALID_FINDING_NOVELTY),
        )
        validated_sort = cast(
            "FindingSort",
            self._validate_choice("sort_by", sort_by, _VALID_FINDING_SORT),
        )
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        validated_severity = self._validate_optional_choice(
            "severity",
            severity,
            _VALID_SEVERITIES,
        )
        record = self._runs.get(run_id)
        paths_filter = self._resolve_query_changed_paths(
            record=record,
            changed_paths=changed_paths,
            git_diff_ref=git_diff_ref,
        )
        normalized_limit = max(
            1,
            min(max_results if max_results is not None else limit, 200),
        )
        filtered = self._query_findings(
            record=record,
            family=validated_family,
            category=category,
            severity=validated_severity,
            source_kind=source_kind,
            novelty=validated_novelty,
            sort_by=validated_sort,
            detail_level=validated_detail,
            changed_paths=paths_filter,
            exclude_reviewed=exclude_reviewed,
        )
        total = len(filtered)
        normalized_offset = max(0, offset)
        items = filtered[normalized_offset : normalized_offset + normalized_limit]
        next_offset = normalized_offset + len(items)
        return {
            "run_id": self._short_run_id(record.run_id),
            "detail_level": validated_detail,
            "sort_by": validated_sort,
            "changed_paths": list(paths_filter),
            "offset": normalized_offset,
            "limit": normalized_limit,
            "returned": len(items),
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
            "items": items,
        }

    def get_finding(
        self,
        *,
        finding_id: str,
        run_id: str | None = None,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        canonical_id = self._resolve_canonical_finding_id(record, finding_id)
        for finding in self._base_findings(record):
            if str(finding.get("id")) == canonical_id:
                return self._decorate_finding(
                    record,
                    finding,
                    detail_level=validated_detail,
                )
        raise MCPFindingNotFoundError(
            f"Finding id '{finding_id}' was not found in run "
            f"'{self._short_run_id(record.run_id)}'."
        )

    def get_remediation(
        self,
        *,
        finding_id: str,
        run_id: str | None = None,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._runs.get(run_id)
        canonical_id = self._resolve_canonical_finding_id(record, finding_id)
        finding = self.get_finding(
            finding_id=canonical_id,
            run_id=record.run_id,
            detail_level="full",
        )
        remediation = self._as_mapping(finding.get("remediation"))
        if not remediation:
            raise MCPFindingNotFoundError(
                f"Finding id '{finding_id}' does not expose remediation guidance."
            )
        return {
            "run_id": self._short_run_id(record.run_id),
            "finding_id": self._short_finding_id(record, canonical_id),
            "detail_level": validated_detail,
            "remediation": self._project_remediation(
                remediation,
                detail_level=validated_detail,
            ),
        }

    def list_hotspots(
        self,
        *,
        kind: HotlistKind,
        run_id: str | None = None,
        detail_level: DetailLevel = "summary",
        changed_paths: Sequence[str] = (),
        git_diff_ref: str | None = None,
        exclude_reviewed: bool = False,
        limit: int = 10,
        max_results: int | None = None,
    ) -> dict[str, object]:
        validated_kind = cast(
            "HotlistKind",
            self._validate_choice("kind", kind, _VALID_HOTLIST_KINDS),
        )
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._runs.get(run_id)
        paths_filter = self._resolve_query_changed_paths(
            record=record,
            changed_paths=changed_paths,
            git_diff_ref=git_diff_ref,
        )
        rows = self._hotspot_rows(
            record=record,
            kind=validated_kind,
            detail_level=validated_detail,
            changed_paths=paths_filter,
            exclude_reviewed=exclude_reviewed,
        )
        normalized_limit = max(
            1,
            min(max_results if max_results is not None else limit, 50),
        )
        return {
            "run_id": self._short_run_id(record.run_id),
            "kind": validated_kind,
            "detail_level": validated_detail,
            "changed_paths": list(paths_filter),
            "returned": min(len(rows), normalized_limit),
            "total": len(rows),
            "items": [dict(self._as_mapping(item)) for item in rows[:normalized_limit]],
        }

    def get_production_triage(
        self,
        *,
        run_id: str | None = None,
        max_hotspots: int = 3,
        max_suggestions: int = 3,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        summary = self._summary_payload(record.summary, record=record)
        findings = self._base_findings(record)
        findings_breakdown = self._source_kind_breakdown(
            self._finding_source_kind(finding) for finding in findings
        )
        suggestion_rows = self._triage_suggestion_rows(record)
        suggestion_breakdown = self._source_kind_breakdown(
            row.get("source_kind") for row in suggestion_rows
        )
        hotspot_limit = max(1, min(max_hotspots, 10))
        suggestion_limit = max(1, min(max_suggestions, 10))
        production_hotspots = self._hotspot_rows(
            record=record,
            kind="production_hotspots",
            detail_level="summary",
            changed_paths=(),
            exclude_reviewed=False,
        )
        production_suggestions = [
            dict(row)
            for row in suggestion_rows
            if str(row.get("source_kind", "")) == SOURCE_KIND_PRODUCTION
        ]
        payload: dict[str, object] = {
            "run_id": self._short_run_id(record.run_id),
            "focus": _FOCUS_PRODUCTION,
            "health_scope": _HEALTH_SCOPE_REPOSITORY,
            "health": dict(self._summary_health_payload(summary)),
            "cache": dict(self._as_mapping(summary.get("cache"))),
            "findings": {
                "total": len(findings),
                "by_source_kind": findings_breakdown,
                "new_by_source_kind": dict(
                    self._as_mapping(
                        self._as_mapping(summary.get("findings")).get(
                            "new_by_source_kind"
                        )
                    )
                ),
                "outside_focus": len(findings)
                - findings_breakdown[SOURCE_KIND_PRODUCTION],
            },
            "top_hotspots": {
                "kind": "production_hotspots",
                "available": len(production_hotspots),
                "returned": min(len(production_hotspots), hotspot_limit),
                "items": [
                    dict(self._as_mapping(item))
                    for item in production_hotspots[:hotspot_limit]
                ],
            },
            "suggestions": {
                "total": len(suggestion_rows),
                "by_source_kind": suggestion_breakdown,
                "outside_focus": len(suggestion_rows)
                - suggestion_breakdown[SOURCE_KIND_PRODUCTION],
            },
            "top_suggestions": {
                "available": len(production_suggestions),
                "returned": min(len(production_suggestions), suggestion_limit),
                "items": production_suggestions[:suggestion_limit],
            },
        }
        analysis_profile = self._summary_analysis_profile_payload(summary)
        if analysis_profile:
            payload["analysis_profile"] = analysis_profile
        return payload

    def get_help(
        self,
        *,
        topic: HelpTopic,
        detail: HelpDetail = "compact",
    ) -> dict[str, object]:
        validated_topic = cast(
            "HelpTopic",
            self._validate_choice("topic", topic, _VALID_HELP_TOPICS),
        )
        validated_detail = cast(
            "HelpDetail",
            self._validate_choice("detail", detail, _VALID_HELP_DETAILS),
        )
        spec = _HELP_TOPIC_SPECS[validated_topic]
        payload: dict[str, object] = {
            "topic": validated_topic,
            "detail": validated_detail,
            "summary": spec.summary,
            "key_points": list(spec.key_points),
            "recommended_tools": list(spec.recommended_tools),
            "doc_links": [
                {"title": title, "url": url} for title, url in spec.doc_links
            ],
        }
        if validated_detail == "normal":
            if spec.warnings:
                payload["warnings"] = list(spec.warnings)
            if spec.anti_patterns:
                payload["anti_patterns"] = list(spec.anti_patterns)
        return payload

    def generate_pr_summary(
        self,
        *,
        run_id: str | None = None,
        changed_paths: Sequence[str] = (),
        git_diff_ref: str | None = None,
        format: PRSummaryFormat = "markdown",
    ) -> dict[str, object]:
        output_format = cast(
            "PRSummaryFormat",
            self._validate_choice("format", format, _VALID_PR_SUMMARY_FORMATS),
        )
        record = self._runs.get(run_id)
        paths_filter = self._resolve_query_changed_paths(
            record=record,
            changed_paths=changed_paths,
            git_diff_ref=git_diff_ref,
            prefer_record_paths=True,
        )
        changed_items = self._query_findings(
            record=record,
            detail_level="summary",
            changed_paths=paths_filter,
        )
        previous = self._previous_run_for_root(record)
        resolved: list[dict[str, object]] = []
        if previous is not None:
            compare_payload = self.compare_runs(
                run_id_before=previous.run_id,
                run_id_after=record.run_id,
                focus="all",
            )
            resolved = cast("list[dict[str, object]]", compare_payload["improvements"])
        with self._state_lock:
            gate_result = dict(
                self._last_gate_results.get(
                    record.run_id,
                    {"would_fail": False, "reasons": []},
                )
            )
        verdict = self._changed_verdict(
            changed_projection={
                "total": len(changed_items),
                "new": sum(
                    1 for item in changed_items if str(item.get("novelty", "")) == "new"
                ),
            },
            health_delta=self._summary_health_delta(record.summary),
        )
        payload: dict[str, object] = {
            "run_id": self._short_run_id(record.run_id),
            "changed_files": len(paths_filter),
            "health": self._summary_health_payload(record.summary),
            "health_delta": self._summary_health_delta(record.summary),
            "verdict": verdict,
            "new_findings_in_changed_files": changed_items,
            "resolved": resolved,
            "blocking_gates": list(cast(Sequence[str], gate_result.get("reasons", []))),
        }
        if output_format == "json":
            return payload
        return {
            "run_id": self._short_run_id(record.run_id),
            "format": output_format,
            "content": self._render_pr_summary_markdown(payload),
        }

    def mark_finding_reviewed(
        self,
        *,
        finding_id: str,
        run_id: str | None = None,
        note: str | None = None,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        canonical_id = self._resolve_canonical_finding_id(record, finding_id)
        self.get_finding(
            finding_id=canonical_id,
            run_id=record.run_id,
            detail_level="normal",
        )
        with self._state_lock:
            review_map = self._review_state.setdefault(record.run_id, OrderedDict())
            review_map[canonical_id] = (
                note.strip() if isinstance(note, str) and note.strip() else None
            )
            review_map.move_to_end(canonical_id)
        return {
            "run_id": self._short_run_id(record.run_id),
            "finding_id": self._short_finding_id(record, canonical_id),
            "reviewed": True,
            "note": review_map[canonical_id],
            "reviewed_count": len(review_map),
        }

    def list_reviewed_findings(
        self,
        *,
        run_id: str | None = None,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        with self._state_lock:
            review_items = tuple(
                self._review_state.get(record.run_id, OrderedDict()).items()
            )
        items = []
        for finding_id, note in review_items:
            try:
                finding = self.get_finding(finding_id=finding_id, run_id=record.run_id)
            except MCPFindingNotFoundError:
                continue
            items.append(
                {
                    "finding_id": self._short_finding_id(record, finding_id),
                    "note": note,
                    "finding": self._project_finding_detail(
                        record,
                        finding,
                        detail_level="summary",
                    ),
                }
            )
        return {
            "run_id": self._short_run_id(record.run_id),
            "reviewed_count": len(items),
            "items": items,
        }

    def clear_session_runs(self) -> dict[str, object]:
        removed_run_ids = self._runs.clear()
        with self._state_lock:
            cleared_review_entries = sum(
                len(entries) for entries in self._review_state.values()
            )
            cleared_gate_results = len(self._last_gate_results)
            cleared_spread_cache_entries = len(self._spread_max_cache)
            self._review_state.clear()
            self._last_gate_results.clear()
            self._spread_max_cache.clear()
        return {
            "cleared_runs": len(removed_run_ids),
            "cleared_run_ids": [
                self._short_run_id(run_id) for run_id in removed_run_ids
            ],
            "cleared_review_entries": cleared_review_entries,
            "cleared_gate_results": cleared_gate_results,
            "cleared_spread_cache_entries": cleared_spread_cache_entries,
        }

    def check_complexity(
        self,
        *,
        run_id: str | None = None,
        root: str | None = None,
        path: str | None = None,
        min_complexity: int | None = None,
        max_results: int = 10,
        detail_level: DetailLevel = "summary",
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._resolve_granular_record(
            run_id=run_id,
            root=root,
            analysis_mode="full",
        )
        findings = self._query_findings(
            record=record,
            family="design",
            category=CATEGORY_COMPLEXITY,
            detail_level=validated_detail,
            changed_paths=self._path_filter_tuple(path),
            sort_by="priority",
        )
        if min_complexity is not None:
            findings = [
                finding
                for finding in findings
                if _as_int(
                    self._as_mapping(finding.get("facts")).get(
                        "cyclomatic_complexity",
                        0,
                    )
                )
                >= min_complexity
            ]
        return self._granular_payload(
            record=record,
            check="complexity",
            items=findings,
            detail_level=validated_detail,
            max_results=max_results,
            path=path,
        )

    def check_clones(
        self,
        *,
        run_id: str | None = None,
        root: str | None = None,
        path: str | None = None,
        clone_type: str | None = None,
        source_kind: str | None = None,
        max_results: int = 10,
        detail_level: DetailLevel = "summary",
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._resolve_granular_record(
            run_id=run_id,
            root=root,
            analysis_mode="clones_only",
        )
        findings = self._query_findings(
            record=record,
            family="clone",
            source_kind=source_kind,
            detail_level=validated_detail,
            changed_paths=self._path_filter_tuple(path),
            sort_by="priority",
        )
        if clone_type is not None:
            findings = [
                finding
                for finding in findings
                if str(finding.get("clone_type", "")).strip() == clone_type
            ]
        return self._granular_payload(
            record=record,
            check="clones",
            items=findings,
            detail_level=validated_detail,
            max_results=max_results,
            path=path,
        )

    def check_coupling(
        self,
        *,
        run_id: str | None = None,
        root: str | None = None,
        path: str | None = None,
        max_results: int = 10,
        detail_level: DetailLevel = "summary",
    ) -> dict[str, object]:
        return self._check_design_metric(
            run_id=run_id,
            root=root,
            path=path,
            max_results=max_results,
            detail_level=detail_level,
            category=CATEGORY_COUPLING,
            check="coupling",
        )

    def check_cohesion(
        self,
        *,
        run_id: str | None = None,
        root: str | None = None,
        path: str | None = None,
        max_results: int = 10,
        detail_level: DetailLevel = "summary",
    ) -> dict[str, object]:
        return self._check_design_metric(
            run_id=run_id,
            root=root,
            path=path,
            max_results=max_results,
            detail_level=detail_level,
            category=CATEGORY_COHESION,
            check="cohesion",
        )

    def _check_design_metric(
        self,
        *,
        run_id: str | None,
        root: str | None,
        path: str | None,
        max_results: int,
        detail_level: DetailLevel,
        category: str,
        check: str,
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        record = self._resolve_granular_record(
            run_id=run_id,
            root=root,
            analysis_mode="full",
        )
        findings = self._query_findings(
            record=record,
            family="design",
            category=category,
            detail_level=validated_detail,
            changed_paths=self._path_filter_tuple(path),
            sort_by="priority",
        )
        return self._granular_payload(
            record=record,
            check=check,
            items=findings,
            detail_level=validated_detail,
            max_results=max_results,
            path=path,
        )

    def check_dead_code(
        self,
        *,
        run_id: str | None = None,
        root: str | None = None,
        path: str | None = None,
        min_severity: str | None = None,
        max_results: int = 10,
        detail_level: DetailLevel = "summary",
    ) -> dict[str, object]:
        validated_detail = cast(
            "DetailLevel",
            self._validate_choice("detail_level", detail_level, _VALID_DETAIL_LEVELS),
        )
        validated_min_severity = self._validate_optional_choice(
            "min_severity",
            min_severity,
            _VALID_SEVERITIES,
        )
        record = self._resolve_granular_record(
            run_id=run_id,
            root=root,
            analysis_mode="full",
        )
        findings = self._query_findings(
            record=record,
            family="dead_code",
            detail_level=validated_detail,
            changed_paths=self._path_filter_tuple(path),
            sort_by="priority",
        )
        if validated_min_severity is not None:
            findings = [
                finding
                for finding in findings
                if self._severity_rank(str(finding.get("severity", "")))
                >= self._severity_rank(validated_min_severity)
            ]
        return self._granular_payload(
            record=record,
            check="dead_code",
            items=findings,
            detail_level=validated_detail,
            max_results=max_results,
            path=path,
        )

    def read_resource(self, uri: str) -> str:
        if uri == "codeclone://schema":
            return _json_text_payload(self._schema_resource_payload())
        if uri == "codeclone://latest/triage":
            latest = self._runs.get()
            return _json_text_payload(self.get_production_triage(run_id=latest.run_id))
        latest_prefix = "codeclone://latest/"
        run_prefix = "codeclone://runs/"
        if uri.startswith(latest_prefix):
            latest = self._runs.get()
            suffix = uri[len(latest_prefix) :]
            return self._render_resource(latest, suffix)
        if not uri.startswith(run_prefix):
            raise MCPServiceContractError(f"Unsupported CodeClone resource URI: {uri}")
        remainder = uri[len(run_prefix) :]
        run_id, sep, suffix = remainder.partition("/")
        if not sep:
            raise MCPServiceContractError(f"Unsupported CodeClone resource URI: {uri}")
        record = self._runs.get(run_id)
        return self._render_resource(record, suffix)

    def _render_resource(self, record: MCPRunRecord, suffix: str) -> str:
        if suffix == "summary":
            return _json_text_payload(
                self._summary_payload(record.summary, record=record)
            )
        if suffix == "triage":
            raise MCPServiceContractError(
                "Production triage is exposed only as codeclone://latest/triage."
            )
        if suffix == "health":
            return _json_text_payload(self._summary_health_payload(record.summary))
        if suffix == "gates":
            with self._state_lock:
                gate_result = self._last_gate_results.get(record.run_id)
            if gate_result is None:
                raise MCPServiceContractError(
                    "No gate evaluation result is available in this MCP session."
                )
            return _json_text_payload(gate_result)
        if suffix == "changed":
            if record.changed_projection is None:
                raise MCPServiceContractError(
                    "Changed-findings projection is not available in this run."
                )
            return _json_text_payload(record.changed_projection)
        if suffix == "schema":
            return _json_text_payload(self._schema_resource_payload())
        if suffix == "report.json":
            return _json_text_payload(record.report_document, sort_keys=False)
        if suffix == "overview":
            return _json_text_payload(
                self.list_hotspots(kind="highest_spread", run_id=record.run_id)
            )
        finding_prefix = "findings/"
        if suffix.startswith(finding_prefix):
            finding_id = suffix[len(finding_prefix) :]
            return _json_text_payload(
                self.get_finding(run_id=record.run_id, finding_id=finding_id)
            )
        raise MCPServiceContractError(
            f"Unsupported CodeClone resource suffix '{suffix}'."
        )

    def _resolve_request_changed_paths(
        self,
        *,
        root_path: Path,
        changed_paths: Sequence[str],
        git_diff_ref: str | None,
    ) -> tuple[str, ...]:
        if changed_paths and git_diff_ref is not None:
            raise MCPServiceContractError(
                "Provide changed_paths or git_diff_ref, not both."
            )
        if git_diff_ref is not None:
            return self._git_diff_paths(root_path=root_path, git_diff_ref=git_diff_ref)
        if not changed_paths:
            return ()
        return self._normalize_changed_paths(root_path=root_path, paths=changed_paths)

    def _resolve_query_changed_paths(
        self,
        *,
        record: MCPRunRecord,
        changed_paths: Sequence[str],
        git_diff_ref: str | None,
        prefer_record_paths: bool = False,
    ) -> tuple[str, ...]:
        if changed_paths or git_diff_ref is not None:
            return self._resolve_request_changed_paths(
                root_path=record.root,
                changed_paths=changed_paths,
                git_diff_ref=git_diff_ref,
            )
        if prefer_record_paths:
            return record.changed_paths
        return ()

    def _normalize_changed_paths(
        self,
        *,
        root_path: Path,
        paths: Sequence[str],
    ) -> tuple[str, ...]:
        normalized: set[str] = set()
        for raw_path in paths:
            candidate = Path(str(raw_path)).expanduser()
            if candidate.is_absolute():
                try:
                    relative = candidate.resolve().relative_to(root_path)
                except (OSError, ValueError) as exc:
                    raise MCPServiceContractError(
                        f"Changed path '{raw_path}' is outside root '{root_path}'."
                    ) from exc
                normalized.add(relative.as_posix())
                continue
            cleaned = self._normalize_relative_path(candidate.as_posix())
            if cleaned:
                normalized.add(cleaned)
        return tuple(sorted(normalized))

    def _git_diff_paths(
        self,
        *,
        root_path: Path,
        git_diff_ref: str,
    ) -> tuple[str, ...]:
        lines = _git_diff_lines_payload(
            root_path=root_path,
            git_diff_ref=git_diff_ref,
        )
        return self._normalize_changed_paths(root_path=root_path, paths=lines)

    def _prune_session_state(self) -> None:
        active_run_ids = {record.run_id for record in self._runs.records()}
        with self._state_lock:
            for state_map in (
                self._review_state,
                self._last_gate_results,
                self._spread_max_cache,
            ):
                stale_run_ids = [
                    run_id for run_id in state_map if run_id not in active_run_ids
                ]
                for run_id in stale_run_ids:
                    state_map.pop(run_id, None)

    def _summary_health_score(self, summary: Mapping[str, object]) -> int | None:
        health = self._summary_health_payload(summary)
        if health.get("available") is False:
            return None
        score = health.get("score", 0)
        return _as_int(score, 0)

    def _summary_health_delta(self, summary: Mapping[str, object]) -> int | None:
        if self._summary_health_payload(summary).get("available") is False:
            return None
        metrics_diff = self._as_mapping(summary.get("metrics_diff"))
        value = metrics_diff.get("health_delta", 0)
        return _as_int(value, 0)

    def _summary_health_payload(
        self,
        summary: Mapping[str, object],
    ) -> dict[str, object]:
        if str(summary.get("analysis_mode", "")) == "clones_only":
            return {"available": False, "reason": "metrics_skipped"}
        health = dict(self._as_mapping(summary.get("health")))
        if health:
            return health
        return {"available": False, "reason": "unavailable"}

    @staticmethod
    def _short_run_id(run_id: str) -> str:
        return run_id[:_SHORT_RUN_ID_LENGTH]

    def _finding_id_maps(
        self,
        record: MCPRunRecord,
    ) -> tuple[dict[str, str], dict[str, str]]:
        canonical_ids = sorted(
            str(finding.get("id", ""))
            for finding in self._base_findings(record)
            if str(finding.get("id", ""))
        )
        base_ids = {
            canonical_id: self._base_short_finding_id(canonical_id)
            for canonical_id in canonical_ids
        }
        grouped: dict[str, list[str]] = {}
        for canonical_id, short_id in base_ids.items():
            grouped.setdefault(short_id, []).append(canonical_id)
        canonical_to_short: dict[str, str] = {}
        short_to_canonical: dict[str, str] = {}
        for short_id, group in grouped.items():
            if len(group) == 1:
                canonical_id = group[0]
                canonical_to_short[canonical_id] = short_id
                short_to_canonical[short_id] = canonical_id
                continue
            disambiguated_ids = self._disambiguated_short_finding_ids(group)
            for canonical_id, disambiguated in disambiguated_ids.items():
                canonical_to_short[canonical_id] = disambiguated
                short_to_canonical[disambiguated] = canonical_id
        return canonical_to_short, short_to_canonical

    @staticmethod
    def _base_short_finding_id(canonical_id: str) -> str:
        return _base_short_finding_id_payload(canonical_id)

    @staticmethod
    def _disambiguated_short_finding_id(canonical_id: str) -> str:
        return _disambiguated_short_finding_id_payload(canonical_id)

    def _disambiguated_short_finding_ids(
        self,
        canonical_ids: Sequence[str],
    ) -> dict[str, str]:
        clone_ids = [
            canonical_id
            for canonical_id in canonical_ids
            if canonical_id.startswith("clone:")
        ]
        if len(clone_ids) == len(canonical_ids):
            clone_short_ids = _disambiguated_clone_short_ids_payload(clone_ids)
            if len(set(clone_short_ids.values())) == len(clone_short_ids):
                return clone_short_ids
        return {
            canonical_id: self._disambiguated_short_finding_id(canonical_id)
            for canonical_id in canonical_ids
        }

    def _short_finding_id(
        self,
        record: MCPRunRecord,
        canonical_id: str,
    ) -> str:
        canonical_to_short, _short_to_canonical = self._finding_id_maps(record)
        return canonical_to_short.get(canonical_id, canonical_id)

    def _resolve_canonical_finding_id(
        self,
        record: MCPRunRecord,
        finding_id: str,
    ) -> str:
        canonical_to_short, short_to_canonical = self._finding_id_maps(record)
        if finding_id in canonical_to_short:
            return finding_id
        canonical = short_to_canonical.get(finding_id)
        if canonical is not None:
            return canonical
        raise MCPFindingNotFoundError(
            f"Finding id '{finding_id}' was not found in run "
            f"'{self._short_run_id(record.run_id)}'."
        )

    def _leaf_symbol_name(self, value: object) -> str:
        return _leaf_symbol_name_payload(value)

    @staticmethod
    def _comparison_settings(
        *,
        args: Namespace,
        request: MCPAnalysisRequest,
    ) -> tuple[object, ...]:
        return (
            request.analysis_mode,
            _as_int(args.min_loc, DEFAULT_MIN_LOC),
            _as_int(args.min_stmt, DEFAULT_MIN_STMT),
            _as_int(args.block_min_loc, DEFAULT_BLOCK_MIN_LOC),
            _as_int(args.block_min_stmt, DEFAULT_BLOCK_MIN_STMT),
            _as_int(args.segment_min_loc, DEFAULT_SEGMENT_MIN_LOC),
            _as_int(args.segment_min_stmt, DEFAULT_SEGMENT_MIN_STMT),
            _as_int(
                args.design_complexity_threshold,
                DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
            ),
            _as_int(
                args.design_coupling_threshold,
                DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
            ),
            _as_int(
                args.design_cohesion_threshold,
                DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
            ),
        )

    @staticmethod
    def _comparison_scope(
        *,
        before: MCPRunRecord,
        after: MCPRunRecord,
    ) -> dict[str, object]:
        same_root = before.root == after.root
        same_analysis_settings = before.comparison_settings == after.comparison_settings
        if same_root and same_analysis_settings:
            reason = "comparable"
        elif not same_root and not same_analysis_settings:
            reason = "different_root_and_analysis_settings"
        elif not same_root:
            reason = "different_root"
        else:
            reason = "different_analysis_settings"
        return {
            "comparable": same_root and same_analysis_settings,
            "same_root": same_root,
            "same_analysis_settings": same_analysis_settings,
            "reason": reason,
        }

    @staticmethod
    def _severity_rank(severity: str) -> int:
        return {
            SEVERITY_CRITICAL: 3,
            SEVERITY_WARNING: 2,
            SEVERITY_INFO: 1,
        }.get(severity, 0)

    def _path_filter_tuple(self, path: str | None) -> tuple[str, ...]:
        if not path:
            return ()
        cleaned = self._normalize_relative_path(Path(path).as_posix())
        return (cleaned,) if cleaned else ()

    def _normalize_relative_path(self, path: str) -> str:
        cleaned = path.strip()
        if cleaned == ".":
            return ""
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        cleaned = cleaned.rstrip("/")
        if ".." in Path(cleaned).parts:
            raise MCPServiceContractError(f"path traversal not allowed: {path}")
        return cleaned

    def _previous_run_for_root(self, record: MCPRunRecord) -> MCPRunRecord | None:
        previous: MCPRunRecord | None = None
        for item in self._runs.records():
            if item.run_id == record.run_id:
                return previous
            if item.root == record.root:
                previous = item
        return None

    @staticmethod
    def _record_supports_analysis_mode(
        record: MCPRunRecord,
        *,
        analysis_mode: AnalysisMode,
    ) -> bool:
        record_mode = record.request.analysis_mode
        if analysis_mode == "clones_only":
            return record_mode in {"clones_only", "full"}
        return record_mode == "full"

    def _latest_compatible_record(
        self,
        *,
        analysis_mode: AnalysisMode,
        root_path: Path | None = None,
    ) -> MCPRunRecord | None:
        for item in reversed(self._runs.records()):
            if root_path is not None and item.root != root_path:
                continue
            if self._record_supports_analysis_mode(
                item,
                analysis_mode=analysis_mode,
            ):
                return item
        return None

    def _resolve_granular_record(
        self,
        *,
        run_id: str | None,
        root: str | None,
        analysis_mode: AnalysisMode,
    ) -> MCPRunRecord:
        if run_id is not None:
            record = self._runs.get(run_id)
            if self._record_supports_analysis_mode(record, analysis_mode=analysis_mode):
                return record
            raise MCPServiceContractError(
                "Selected MCP run is not compatible with this check. "
                f"Call analyze_repository(root='{record.root}', "
                "analysis_mode='full') first."
            )
        root_path = self._resolve_optional_root(root)
        latest_record = self._latest_compatible_record(
            analysis_mode=analysis_mode,
            root_path=root_path,
        )
        if latest_record is not None:
            return latest_record
        if root_path is not None:
            raise MCPRunNotFoundError(
                f"No compatible MCP analysis run is available for root: {root_path}. "
                f"Call analyze_repository(root='{root_path}') or "
                f"analyze_changed_paths(root='{root_path}', changed_paths=[...]) first."
            )
        raise MCPRunNotFoundError(
            "No compatible MCP analysis run is available. "
            "Call analyze_repository(root='/path/to/repo') or "
            "analyze_changed_paths(root='/path/to/repo', changed_paths=[...]) first."
        )

    def _base_findings(self, record: MCPRunRecord) -> list[dict[str, object]]:
        report_document = record.report_document
        findings = self._as_mapping(report_document.get("findings"))
        groups = self._as_mapping(findings.get("groups"))
        clone_groups = self._as_mapping(groups.get(FAMILY_CLONES))
        return [
            *self._dict_list(clone_groups.get("functions")),
            *self._dict_list(clone_groups.get("blocks")),
            *self._dict_list(clone_groups.get("segments")),
            *self._dict_list(
                self._as_mapping(groups.get(FAMILY_STRUCTURAL)).get("groups")
            ),
            *self._dict_list(
                self._as_mapping(groups.get(FAMILY_DEAD_CODE)).get("groups")
            ),
            *self._dict_list(self._as_mapping(groups.get(FAMILY_DESIGN)).get("groups")),
        ]

    def _query_findings(
        self,
        *,
        record: MCPRunRecord,
        family: FindingFamilyFilter = "all",
        category: str | None = None,
        severity: str | None = None,
        source_kind: str | None = None,
        novelty: FindingNoveltyFilter = "all",
        sort_by: FindingSort = "default",
        detail_level: DetailLevel = "normal",
        changed_paths: Sequence[str] = (),
        exclude_reviewed: bool = False,
    ) -> list[dict[str, object]]:
        findings = self._base_findings(record)
        max_spread_value = max(
            (self._spread_value(finding) for finding in findings),
            default=0,
        )
        with self._state_lock:
            self._spread_max_cache[record.run_id] = max_spread_value
        filtered = [
            finding
            for finding in findings
            if self._matches_finding_filters(
                finding=finding,
                family=family,
                category=category,
                severity=severity,
                source_kind=source_kind,
                novelty=novelty,
            )
            and (
                not changed_paths
                or self._finding_touches_paths(
                    finding=finding,
                    changed_paths=changed_paths,
                )
            )
            and (not exclude_reviewed or not self._finding_is_reviewed(record, finding))
        ]
        remediation_map = {
            str(finding.get("id", "")): self._remediation_for_finding(record, finding)
            for finding in filtered
        }
        priority_map = {
            str(finding.get("id", "")): self._priority_score(
                record,
                finding,
                remediation=remediation_map[str(finding.get("id", ""))],
                max_spread_value=max_spread_value,
            )
            for finding in filtered
        }
        ordered = self._sort_findings(
            record=record,
            findings=filtered,
            sort_by=sort_by,
            priority_map=priority_map,
        )
        return [
            self._decorate_finding(
                record,
                finding,
                detail_level=detail_level,
                remediation=remediation_map[str(finding.get("id", ""))],
                priority_payload=priority_map[str(finding.get("id", ""))],
                max_spread_value=max_spread_value,
            )
            for finding in ordered
        ]

    def _sort_findings(
        self,
        *,
        record: MCPRunRecord,
        findings: Sequence[Mapping[str, object]],
        sort_by: FindingSort,
        priority_map: Mapping[str, Mapping[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        finding_rows = [dict(finding) for finding in findings]
        if sort_by == "default":
            return finding_rows
        if sort_by == "severity":
            finding_rows.sort(
                key=lambda finding: (
                    -self._severity_rank(str(finding.get("severity", ""))),
                    str(finding.get("id", "")),
                )
            )
        elif sort_by == "spread":
            finding_rows.sort(
                key=lambda finding: (
                    -self._spread_value(finding),
                    -_as_float(finding.get("priority", 0.0), 0.0),
                    str(finding.get("id", "")),
                )
            )
        else:
            finding_rows.sort(
                key=lambda finding: (
                    -_as_float(
                        self._as_mapping(
                            (priority_map or {}).get(str(finding.get("id", "")))
                        ).get("score", 0.0),
                        0.0,
                    )
                    if priority_map is not None
                    else -_as_float(
                        self._priority_score(record, finding)["score"],
                        0.0,
                    ),
                    -self._severity_rank(str(finding.get("severity", ""))),
                    str(finding.get("id", "")),
                )
            )
        return finding_rows

    def _decorate_finding(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
        *,
        detail_level: DetailLevel,
        remediation: Mapping[str, object] | None = None,
        priority_payload: Mapping[str, object] | None = None,
        max_spread_value: int | None = None,
    ) -> dict[str, object]:
        resolved_remediation = (
            remediation
            if remediation is not None
            else self._remediation_for_finding(record, finding)
        )
        resolved_priority_payload = (
            dict(priority_payload)
            if priority_payload is not None
            else self._priority_score(
                record,
                finding,
                remediation=resolved_remediation,
                max_spread_value=max_spread_value,
            )
        )
        payload = dict(finding)
        payload["priority_score"] = resolved_priority_payload["score"]
        payload["priority_factors"] = resolved_priority_payload["factors"]
        payload["locations"] = self._locations_for_finding(
            record,
            finding,
            include_uri=detail_level == "full",
        )
        payload["html_anchor"] = f"finding-{finding.get('id', '')}"
        if resolved_remediation is not None:
            payload["remediation"] = resolved_remediation
        return self._project_finding_detail(
            record,
            payload,
            detail_level=detail_level,
        )

    def _project_finding_detail(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
        *,
        detail_level: DetailLevel,
    ) -> dict[str, object]:
        if detail_level == "full":
            full_payload = dict(finding)
            full_payload["id"] = self._short_finding_id(
                record,
                str(finding.get("id", "")),
            )
            return full_payload
        payload: dict[str, object] = {
            "id": self._short_finding_id(record, str(finding.get("id", ""))),
            "kind": self._finding_kind_label(finding),
            "severity": str(finding.get("severity", "")),
            "novelty": str(finding.get("novelty", "")),
            "scope": self._finding_source_kind(finding),
            "count": _as_int(finding.get("count", 0), 0),
            "spread": dict(self._as_mapping(finding.get("spread"))),
            "priority": round(_as_float(finding.get("priority_score", 0.0), 0.0), 2),
        }
        clone_type = str(finding.get("clone_type", "")).strip()
        if clone_type:
            payload["type"] = clone_type
        locations = [
            self._as_mapping(item)
            for item in self._as_sequence(finding.get("locations"))
        ]
        if detail_level == "summary":
            remediation = self._as_mapping(finding.get("remediation"))
            if remediation:
                payload["effort"] = str(remediation.get("effort", ""))
            payload["locations"] = [
                summary_location
                for summary_location in (
                    self._summary_location_string(location) for location in locations
                )
                if summary_location
            ]
            return payload
        remediation = self._as_mapping(finding.get("remediation"))
        if remediation:
            payload["remediation"] = self._project_remediation(
                remediation,
                detail_level="normal",
            )
        payload["locations"] = [
            projected
            for projected in (
                self._normal_location_payload(location) for location in locations
            )
            if projected
        ]
        return payload

    def _finding_summary_card(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
    ) -> dict[str, object]:
        return self._finding_summary_card_payload(
            record,
            self._decorate_finding(record, finding, detail_level="full"),
        )

    def _finding_summary_card_payload(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
    ) -> dict[str, object]:
        return self._project_finding_detail(record, finding, detail_level="summary")

    def _comparison_finding_card(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
    ) -> dict[str, object]:
        summary_card = self._finding_summary_card(record, finding)
        return {
            "id": summary_card.get("id"),
            "kind": summary_card.get("kind"),
            "severity": summary_card.get("severity"),
        }

    @staticmethod
    def _finding_kind_label(finding: Mapping[str, object]) -> str:
        family = str(finding.get("family", "")).strip()
        kind = str(finding.get("kind", finding.get("category", ""))).strip()
        if family == FAMILY_CLONE:
            clone_kind = str(
                finding.get("clone_kind", finding.get("category", kind))
            ).strip()
            return f"{clone_kind}_clone" if clone_kind else "clone"
        if family == FAMILY_DEAD_CODE:
            return "dead_code"
        return kind or family

    @staticmethod
    def _summary_location_string(location: Mapping[str, object]) -> str:
        path = str(location.get("file", "")).strip()
        line = _as_int(location.get("line", 0), 0)
        if not path:
            return ""
        return f"{path}:{line}" if line > 0 else path

    def _normal_location_payload(
        self,
        location: Mapping[str, object],
    ) -> dict[str, object]:
        path = str(location.get("file", "")).strip()
        if not path:
            return {}
        payload: dict[str, object] = {
            "path": path,
            "line": _as_int(location.get("line", 0), 0),
            "end_line": _as_int(location.get("end_line", 0), 0),
        }
        symbol = self._leaf_symbol_name(location.get("symbol"))
        if symbol:
            payload["symbol"] = symbol
        return payload

    def _matches_finding_filters(
        self,
        *,
        finding: Mapping[str, object],
        family: FindingFamilyFilter,
        category: str | None = None,
        severity: str | None,
        source_kind: str | None,
        novelty: FindingNoveltyFilter,
    ) -> bool:
        finding_family = str(finding.get("family", "")).strip()
        if family != "all" and finding_family != family:
            return False
        if (
            category is not None
            and str(finding.get("category", "")).strip() != category
        ):
            return False
        if (
            severity is not None
            and str(finding.get("severity", "")).strip() != severity
        ):
            return False
        dominant_kind = str(
            self._as_mapping(finding.get("source_scope")).get("dominant_kind", "")
        ).strip()
        if source_kind is not None and dominant_kind != source_kind:
            return False
        return novelty == "all" or str(finding.get("novelty", "")).strip() == novelty

    def _finding_touches_paths(
        self,
        *,
        finding: Mapping[str, object],
        changed_paths: Sequence[str],
    ) -> bool:
        normalized_paths = tuple(changed_paths)
        for item in self._as_sequence(finding.get("items")):
            relative_path = str(self._as_mapping(item).get("relative_path", "")).strip()
            if relative_path and self._path_matches(relative_path, normalized_paths):
                return True
        return False

    @staticmethod
    def _path_matches(relative_path: str, changed_paths: Sequence[str]) -> bool:
        for candidate in changed_paths:
            if relative_path == candidate or relative_path.startswith(candidate + "/"):
                return True
        return False

    def _finding_is_reviewed(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
    ) -> bool:
        with self._state_lock:
            review_map = self._review_state.get(record.run_id, OrderedDict())
            return str(finding.get("id", "")) in review_map

    def _include_hotspot_finding(
        self,
        *,
        record: MCPRunRecord,
        finding: Mapping[str, object],
        changed_paths: Sequence[str],
        exclude_reviewed: bool,
    ) -> bool:
        if changed_paths and not self._finding_touches_paths(
            finding=finding,
            changed_paths=changed_paths,
        ):
            return False
        return not exclude_reviewed or not self._finding_is_reviewed(record, finding)

    def _priority_score(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
        *,
        remediation: Mapping[str, object] | None = None,
        max_spread_value: int | None = None,
    ) -> dict[str, object]:
        spread_weight = self._spread_weight(
            record,
            finding,
            max_spread_value=max_spread_value,
        )
        factors = {
            "severity_weight": _SEVERITY_WEIGHT.get(
                str(finding.get("severity", "")),
                0.2,
            ),
            "effort_weight": _EFFORT_WEIGHT.get(
                (
                    str(remediation.get("effort", EFFORT_MODERATE))
                    if remediation is not None
                    else EFFORT_MODERATE
                ),
                0.6,
            ),
            "novelty_weight": _NOVELTY_WEIGHT.get(
                str(finding.get("novelty", "")),
                0.7,
            ),
            "runtime_weight": _RUNTIME_WEIGHT.get(
                str(
                    self._as_mapping(finding.get("source_scope")).get(
                        "dominant_kind",
                        "other",
                    )
                ),
                0.5,
            ),
            "spread_weight": spread_weight,
            "confidence_weight": _CONFIDENCE_WEIGHT.get(
                str(finding.get("confidence", CONFIDENCE_MEDIUM)),
                0.7,
            ),
        }
        product = 1.0
        for value in factors.values():
            product *= max(_as_float(value, 0.01), 0.01)
        score = product ** (1.0 / max(len(factors), 1))
        return {
            "score": round(score, 4),
            "factors": {
                key: round(_as_float(value, 0.0), 4) for key, value in factors.items()
            },
        }

    def _spread_weight(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
        *,
        max_spread_value: int | None = None,
    ) -> float:
        spread_value = self._spread_value(finding)
        if max_spread_value is None:
            with self._state_lock:
                max_spread_value = self._spread_max_cache.get(record.run_id)
            if max_spread_value is None:
                max_spread_value = max(
                    (self._spread_value(item) for item in self._base_findings(record)),
                    default=0,
                )
                with self._state_lock:
                    self._spread_max_cache[record.run_id] = max_spread_value
        max_value = max_spread_value
        if max_value <= 0:
            return 0.3
        return max(0.2, min(1.0, spread_value / max_value))

    def _spread_value(self, finding: Mapping[str, object]) -> int:
        spread = self._as_mapping(finding.get("spread"))
        files = _as_int(spread.get("files", 0), 0)
        functions = _as_int(spread.get("functions", 0), 0)
        count = _as_int(finding.get("count", 0), 0)
        return max(files, functions, count, 1)

    def _locations_for_finding(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
        *,
        include_uri: bool = True,
    ) -> list[dict[str, object]]:
        locations: list[dict[str, object]] = []
        for item in self._as_sequence(finding.get("items")):
            item_map = self._as_mapping(item)
            relative_path = str(item_map.get("relative_path", "")).strip()
            if not relative_path:
                continue
            line = _as_int(item_map.get("start_line", 0) or 0, 0)
            end_line = _as_int(item_map.get("end_line", 0) or 0, 0)
            symbol = str(item_map.get("qualname", item_map.get("module", ""))).strip()
            location: dict[str, object] = {
                "file": relative_path,
                "line": line,
                "end_line": end_line,
                "symbol": symbol,
            }
            if include_uri:
                absolute_path = (record.root / relative_path).resolve()
                uri = absolute_path.as_uri()
                if line > 0:
                    uri = f"{uri}#L{line}"
                location["uri"] = uri
            locations.append(location)
        deduped: list[dict[str, object]] = []
        seen: set[tuple[str, int, str]] = set()
        for location in locations:
            key = (
                str(location.get("file", "")),
                _as_int(location.get("line", 0), 0),
                str(location.get("symbol", "")),
            )
            if key not in seen:
                seen.add(key)
                deduped.append(location)
        return deduped

    @staticmethod
    def _suggestion_finding_id(suggestion: object) -> str:
        return _suggestion_finding_id_payload(suggestion)

    def _remediation_for_finding(
        self,
        record: MCPRunRecord,
        finding: Mapping[str, object],
    ) -> dict[str, object] | None:
        suggestion = self._suggestion_for_finding(record, str(finding.get("id", "")))
        if suggestion is None:
            return None
        source_kind = str(getattr(suggestion, "source_kind", "other"))
        spread_files = _as_int(getattr(suggestion, "spread_files", 0), 0)
        spread_functions = _as_int(getattr(suggestion, "spread_functions", 0), 0)
        title = str(getattr(suggestion, "title", "")).strip()
        severity = str(finding.get("severity", "")).strip()
        novelty = str(finding.get("novelty", "known")).strip()
        count = _as_int(
            getattr(suggestion, "fact_count", 0) or finding.get("count", 0) or 0,
            0,
        )
        safe_refactor_shape = self._safe_refactor_shape(suggestion)
        effort = str(getattr(suggestion, "effort", EFFORT_MODERATE))
        confidence = str(getattr(suggestion, "confidence", CONFIDENCE_MEDIUM))
        risk_level = self._risk_level_for_effort(effort)
        return {
            "effort": effort,
            "priority": _as_float(getattr(suggestion, "priority", 0.0), 0.0),
            "confidence": confidence,
            "safe_refactor_shape": safe_refactor_shape,
            "steps": list(getattr(suggestion, "steps", ())),
            "risk_level": risk_level,
            "why_now": self._why_now_text(
                title=title,
                severity=severity,
                novelty=novelty,
                count=count,
                source_kind=source_kind,
                spread_files=spread_files,
                spread_functions=spread_functions,
                effort=effort,
            ),
            "blast_radius": {
                "files": spread_files,
                "functions": spread_functions,
                "is_production": source_kind == "production",
            },
        }

    def _suggestion_for_finding(
        self,
        record: MCPRunRecord,
        finding_id: str,
    ) -> object | None:
        for suggestion in record.suggestions:
            if self._suggestion_finding_id(suggestion) == finding_id:
                return suggestion
        return None

    @staticmethod
    def _safe_refactor_shape(suggestion: object) -> str:
        category = str(getattr(suggestion, "category", "")).strip()
        clone_type = str(getattr(suggestion, "clone_type", "")).strip()
        title = str(getattr(suggestion, "title", "")).strip()
        if category == CATEGORY_CLONE and clone_type == "Type-1":
            return "Keep one canonical implementation and route callers through it."
        if category == CATEGORY_CLONE and clone_type == "Type-2":
            return "Extract shared implementation with explicit parameters."
        if category == CATEGORY_CLONE and "Block" in title:
            return "Extract the repeated statement sequence into a helper."
        if category == CATEGORY_STRUCTURAL:
            return "Extract the repeated branch family into a named helper."
        if category == CATEGORY_COMPLEXITY:
            return "Split the function into smaller named steps."
        if category == CATEGORY_COUPLING:
            return "Isolate responsibilities and invert unnecessary dependencies."
        if category == CATEGORY_COHESION:
            return "Split the class by responsibility boundary."
        if category == CATEGORY_DEAD_CODE:
            return "Delete the unused symbol or document intentional reachability."
        if category == CATEGORY_DEPENDENCY:
            return "Break the cycle by moving shared abstractions to a lower layer."
        return "Extract the repeated logic into a shared, named abstraction."

    @staticmethod
    def _risk_level_for_effort(effort: str) -> str:
        return {
            EFFORT_EASY: "low",
            EFFORT_MODERATE: "medium",
            EFFORT_HARD: "high",
        }.get(effort, "medium")

    @staticmethod
    def _why_now_text(
        *,
        title: str,
        severity: str,
        novelty: str,
        count: int,
        source_kind: str,
        spread_files: int,
        spread_functions: int,
        effort: str,
    ) -> str:
        novelty_text = "new regression" if novelty == "new" else "known debt"
        context = (
            "production code"
            if source_kind == "production"
            else source_kind or "mixed scope"
        )
        spread_text = f"{spread_files} files / {spread_functions} functions"
        count_text = f"{count} instances" if count > 0 else "localized issue"
        return (
            f"{severity.upper()} {title} in {context} — {count_text}, "
            f"{spread_text}, {effort} fix, {novelty_text}."
        )

    def _project_remediation(
        self,
        remediation: Mapping[str, object],
        *,
        detail_level: DetailLevel,
    ) -> dict[str, object]:
        if detail_level == "full":
            return dict(remediation)
        projected = {
            "effort": remediation.get("effort"),
            "risk": remediation.get("risk_level"),
            "shape": remediation.get("safe_refactor_shape"),
            "why_now": remediation.get("why_now"),
        }
        if detail_level == "summary":
            return projected
        projected["steps"] = list(self._as_sequence(remediation.get("steps")))
        return projected

    def _hotspot_rows(
        self,
        *,
        record: MCPRunRecord,
        kind: HotlistKind,
        detail_level: DetailLevel,
        changed_paths: Sequence[str],
        exclude_reviewed: bool,
    ) -> list[dict[str, object]]:
        findings = self._base_findings(record)
        finding_index = {str(finding.get("id", "")): finding for finding in findings}
        max_spread_value = max(
            (self._spread_value(finding) for finding in findings),
            default=0,
        )
        with self._state_lock:
            self._spread_max_cache[record.run_id] = max_spread_value
        remediation_map = {
            str(finding.get("id", "")): self._remediation_for_finding(record, finding)
            for finding in findings
        }
        priority_map = {
            str(finding.get("id", "")): self._priority_score(
                record,
                finding,
                remediation=remediation_map[str(finding.get("id", ""))],
                max_spread_value=max_spread_value,
            )
            for finding in findings
        }
        derived = self._as_mapping(record.report_document.get("derived"))
        hotlists = self._as_mapping(derived.get("hotlists"))
        if kind == "highest_priority":
            ordered_ids = [
                str(finding.get("id", ""))
                for finding in self._sort_findings(
                    record=record,
                    findings=findings,
                    sort_by="priority",
                    priority_map=priority_map,
                )
            ]
        else:
            hotlist_key = _HOTLIST_REPORT_KEYS.get(kind)
            if hotlist_key is None:
                return []
            ordered_ids = [
                str(item)
                for item in self._as_sequence(hotlists.get(hotlist_key))
                if str(item)
            ]
        rows: list[dict[str, object]] = []
        for finding_id in ordered_ids:
            finding = finding_index.get(finding_id)
            if finding is None or not self._include_hotspot_finding(
                record=record,
                finding=finding,
                changed_paths=changed_paths,
                exclude_reviewed=exclude_reviewed,
            ):
                continue
            finding_id_key = str(finding.get("id", ""))
            rows.append(
                self._decorate_finding(
                    record,
                    finding,
                    detail_level=detail_level,
                    remediation=remediation_map[finding_id_key],
                    priority_payload=priority_map[finding_id_key],
                    max_spread_value=max_spread_value,
                )
            )
        return rows

    def _build_changed_projection(
        self,
        record: MCPRunRecord,
    ) -> dict[str, object] | None:
        if not record.changed_paths:
            return None
        items = self._query_findings(
            record=record,
            detail_level="summary",
            changed_paths=record.changed_paths,
        )
        new_count = sum(1 for item in items if str(item.get("novelty", "")) == "new")
        known_count = sum(
            1 for item in items if str(item.get("novelty", "")) == "known"
        )
        new_by_source_kind = self._source_kind_breakdown(
            item.get("source_kind")
            for item in items
            if str(item.get("novelty", "")) == "new"
        )
        health_delta = self._summary_health_delta(record.summary)
        return {
            "run_id": self._short_run_id(record.run_id),
            "changed_paths": list(record.changed_paths),
            "total": len(items),
            "new": new_count,
            "known": known_count,
            "new_by_source_kind": new_by_source_kind,
            "items": items,
            "health": dict(self._summary_health_payload(record.summary)),
            "health_delta": health_delta,
            "verdict": self._changed_verdict(
                changed_projection={"new": new_count, "total": len(items)},
                health_delta=health_delta,
            ),
        }

    def _changed_analysis_payload(
        self,
        record: MCPRunRecord,
    ) -> dict[str, object]:
        changed_projection = self._as_mapping(record.changed_projection)
        health = self._summary_health_payload(record.summary)
        health_payload = (
            {
                "score": health.get("score"),
                "grade": health.get("grade"),
            }
            if health.get("available") is not False
            else dict(health)
        )
        return {
            "run_id": self._short_run_id(record.run_id),
            "focus": _FOCUS_CHANGED_PATHS,
            "health_scope": _HEALTH_SCOPE_REPOSITORY,
            "changed_files": len(record.changed_paths),
            "health": health_payload,
            "analysis_profile": self._summary_analysis_profile_payload(record.summary),
            "health_delta": (
                _as_int(changed_projection.get("health_delta", 0), 0)
                if changed_projection.get("health_delta") is not None
                else None
            ),
            "verdict": str(changed_projection.get("verdict", "stable")),
            "new_findings": _as_int(changed_projection.get("new", 0), 0),
            "new_by_source_kind": dict(
                self._as_mapping(changed_projection.get("new_by_source_kind"))
            ),
            "resolved_findings": 0,
            "changed_findings": [],
        }

    def _augment_summary_with_changed(
        self,
        *,
        summary: Mapping[str, object],
        changed_paths: Sequence[str],
        changed_projection: Mapping[str, object] | None,
    ) -> dict[str, object]:
        payload = dict(summary)
        if changed_paths:
            payload["changed_paths"] = list(changed_paths)
        if changed_projection is not None:
            payload["changed_findings"] = {
                "total": _as_int(changed_projection.get("total", 0), 0),
                "new": _as_int(changed_projection.get("new", 0), 0),
                "known": _as_int(changed_projection.get("known", 0), 0),
                "items": [
                    dict(self._as_mapping(item))
                    for item in self._as_sequence(changed_projection.get("items"))[:10]
                ],
            }
            payload["health_delta"] = (
                _as_int(changed_projection.get("health_delta", 0), 0)
                if changed_projection.get("health_delta") is not None
                else None
            )
            payload["verdict"] = str(changed_projection.get("verdict", "stable"))
        return payload

    @staticmethod
    def _changed_verdict(
        *,
        changed_projection: Mapping[str, object],
        health_delta: int | None,
    ) -> str:
        if _as_int(changed_projection.get("new", 0), 0) > 0 or (
            health_delta is not None and health_delta < 0
        ):
            return "regressed"
        if (
            _as_int(changed_projection.get("total", 0), 0) == 0
            and health_delta is not None
            and health_delta > 0
        ):
            return "improved"
        return "stable"

    def _comparison_index(
        self,
        record: MCPRunRecord,
        *,
        focus: ComparisonFocus,
    ) -> dict[str, dict[str, object]]:
        findings = self._base_findings(record)
        if focus == "clones":
            findings = [f for f in findings if str(f.get("family", "")) == FAMILY_CLONE]
        elif focus == "structural":
            findings = [
                f for f in findings if str(f.get("family", "")) == FAMILY_STRUCTURAL
            ]
        elif focus == "metrics":
            findings = [
                f
                for f in findings
                if str(f.get("family", "")) in {FAMILY_DESIGN, FAMILY_DEAD_CODE}
            ]
        return {str(finding.get("id", "")): dict(finding) for finding in findings}

    @staticmethod
    def _comparison_verdict(
        *,
        regressions: int,
        improvements: int,
        health_delta: int | None,
    ) -> str:
        has_negative_signal = regressions > 0 or (
            health_delta is not None and health_delta < 0
        )
        has_positive_signal = improvements > 0 or (
            health_delta is not None and health_delta > 0
        )
        if has_negative_signal and has_positive_signal:
            return "mixed"
        if has_negative_signal:
            return "regressed"
        if has_positive_signal:
            return "improved"
        return "stable"

    @staticmethod
    def _comparison_summary_text(
        *,
        comparable: bool,
        comparability_reason: str,
        regressions: int,
        improvements: int,
        health_delta: int | None,
    ) -> str:
        if not comparable:
            reason_text = {
                "different_root": "different roots",
                "different_analysis_settings": "different analysis settings",
                "different_root_and_analysis_settings": (
                    "different roots and analysis settings"
                ),
            }.get(comparability_reason, "incomparable runs")
            return f"Finding and run health deltas omitted ({reason_text})"
        if health_delta is None:
            return (
                f"{improvements} findings resolved, {regressions} new regressions; "
                "run health delta omitted (metrics unavailable)"
            )
        return (
            f"{improvements} findings resolved, {regressions} new regressions, "
            f"run health delta {health_delta:+d}"
        )

    def _render_pr_summary_markdown(self, payload: Mapping[str, object]) -> str:
        health = self._as_mapping(payload.get("health"))
        score = health.get("score", "n/a")
        grade = health.get("grade", "n/a")
        delta = _as_int(payload.get("health_delta", 0), 0)
        changed_items = [
            self._as_mapping(item)
            for item in self._as_sequence(payload.get("new_findings_in_changed_files"))
        ]
        resolved = [
            self._as_mapping(item)
            for item in self._as_sequence(payload.get("resolved"))
        ]
        blocking_gates = [
            str(item)
            for item in self._as_sequence(payload.get("blocking_gates"))
            if str(item)
        ]
        health_line = (
            f"Health: {score}/100 ({grade}) | Delta: {delta:+d} | "
            f"Verdict: {payload.get('verdict', 'stable')}"
            if payload.get("health_delta") is not None
            else (
                f"Health: {score}/100 ({grade}) | Delta: n/a | "
                f"Verdict: {payload.get('verdict', 'stable')}"
            )
        )
        lines = [
            "## CodeClone Summary",
            "",
            health_line,
            "",
            f"### New findings in changed files ({len(changed_items)})",
        ]
        if not changed_items:
            lines.append("- None")
        else:
            lines.extend(
                [
                    (
                        f"- **{str(item.get('severity', 'info')).upper()}** "
                        f"{item.get('kind', 'finding')} in "
                        f"`{self._finding_display_location(item)}`"
                    )
                    for item in changed_items[:10]
                ]
            )
        lines.extend(["", f"### Resolved ({len(resolved)})"])
        if not resolved:
            lines.append("- None")
        else:
            lines.extend(
                [
                    (
                        f"- {item.get('kind', 'finding')} in "
                        f"`{self._finding_display_location(item)}`"
                    )
                    for item in resolved[:10]
                ]
            )
        lines.extend(["", "### Blocking gates"])
        if not blocking_gates:
            lines.append("- none")
        else:
            lines.extend([f"- `{reason}`" for reason in blocking_gates])
        return "\n".join(lines)

    def _finding_display_location(self, finding: Mapping[str, object]) -> str:
        locations = self._as_sequence(finding.get("locations"))
        if not locations:
            return "(unknown)"
        first = locations[0]
        if isinstance(first, str):
            return first
        location = self._as_mapping(first)
        path = str(location.get("path", location.get("file", ""))).strip()
        line = _as_int(location.get("line", 0), 0)
        if not path:
            return "(unknown)"
        return f"{path}:{line}" if line > 0 else path

    def _granular_payload(
        self,
        *,
        record: MCPRunRecord,
        check: str,
        items: Sequence[Mapping[str, object]],
        detail_level: DetailLevel,
        max_results: int,
        path: str | None,
    ) -> dict[str, object]:
        bounded_items = [dict(item) for item in items[: max(1, max_results)]]
        full_health = dict(self._as_mapping(record.summary.get("health")))
        dimensions = self._as_mapping(full_health.get("dimensions"))
        relevant_dimension = _CHECK_TO_DIMENSION.get(check)
        slim_dimensions = (
            {relevant_dimension: dimensions.get(relevant_dimension)}
            if relevant_dimension and relevant_dimension in dimensions
            else dict(dimensions)
        )
        return {
            "run_id": self._short_run_id(record.run_id),
            "check": check,
            "detail_level": detail_level,
            "path": path,
            "returned": len(bounded_items),
            "total": len(items),
            "health": {
                "score": full_health.get("score"),
                "grade": full_health.get("grade"),
                "dimensions": slim_dimensions,
            },
            "items": bounded_items,
        }

    @staticmethod
    def _normalized_source_kind(value: object) -> str:
        normalized = str(value).strip().lower()
        if normalized in SOURCE_KIND_ORDER:
            return normalized
        return SOURCE_KIND_OTHER

    def _finding_source_kind(self, finding: Mapping[str, object]) -> str:
        source_scope = self._as_mapping(finding.get("source_scope"))
        return self._normalized_source_kind(source_scope.get("dominant_kind"))

    def _source_kind_breakdown(
        self,
        source_kinds: Iterable[object],
    ) -> dict[str, int]:
        breakdown = dict.fromkeys(_SOURCE_KIND_BREAKDOWN_ORDER, 0)
        for value in source_kinds:
            breakdown[self._normalized_source_kind(value)] += 1
        return breakdown

    def _triage_suggestion_rows(self, record: MCPRunRecord) -> list[dict[str, object]]:
        derived = self._as_mapping(record.report_document.get("derived"))
        canonical_rows = self._dict_list(derived.get("suggestions"))
        suggestion_source_kinds = {
            self._suggestion_finding_id(suggestion): self._normalized_source_kind(
                getattr(suggestion, "source_kind", SOURCE_KIND_OTHER)
            )
            for suggestion in record.suggestions
        }
        rows: list[dict[str, object]] = []
        for row in canonical_rows:
            canonical_finding_id = str(row.get("finding_id", ""))
            action = self._as_mapping(row.get("action"))
            try:
                finding_id = self._short_finding_id(
                    record,
                    self._resolve_canonical_finding_id(record, canonical_finding_id),
                )
            except MCPFindingNotFoundError:
                finding_id = self._base_short_finding_id(canonical_finding_id)
            rows.append(
                {
                    "id": f"suggestion:{finding_id}",
                    "finding_id": finding_id,
                    "title": str(row.get("title", "")),
                    "summary": str(row.get("summary", "")),
                    "effort": str(action.get("effort", "")),
                    "steps": list(self._as_sequence(action.get("steps"))),
                    "source_kind": suggestion_source_kinds.get(
                        canonical_finding_id,
                        SOURCE_KIND_OTHER,
                    ),
                }
            )
        return rows

    def _derived_section_payload(self, record: MCPRunRecord) -> dict[str, object]:
        derived = self._as_mapping(record.report_document.get("derived"))
        if not derived:
            raise MCPServiceContractError(
                "Report section 'derived' is not available in this run."
            )
        suggestions = self._triage_suggestion_rows(record)
        canonical_to_short, _ = self._finding_id_maps(record)
        hotlists = self._as_mapping(derived.get("hotlists"))
        projected_hotlists: dict[str, list[str]] = {}
        for hotlist_key, hotlist_ids in hotlists.items():
            projected_hotlists[hotlist_key] = [
                canonical_to_short.get(
                    str(finding_id),
                    self._base_short_finding_id(str(finding_id)),
                )
                for finding_id in self._as_sequence(hotlist_ids)
                if str(finding_id)
            ]
        return {
            "suggestions": suggestions,
            "hotlists": projected_hotlists,
        }

    @staticmethod
    def _schema_resource_payload() -> dict[str, object]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "CodeCloneCanonicalReport",
            "type": "object",
            "required": [
                "report_schema_version",
                "meta",
                "inventory",
                "findings",
                "derived",
                "integrity",
            ],
            "properties": {
                "report_schema_version": {
                    "type": "string",
                    "const": REPORT_SCHEMA_VERSION,
                },
                "meta": {"type": "object"},
                "inventory": {"type": "object"},
                "findings": {"type": "object"},
                "metrics": {"type": "object"},
                "derived": {"type": "object"},
                "integrity": {"type": "object"},
            },
        }

    def _validate_analysis_request(self, request: MCPAnalysisRequest) -> None:
        self._validate_choice(
            "analysis_mode",
            request.analysis_mode,
            _VALID_ANALYSIS_MODES,
        )
        self._validate_choice(
            "cache_policy",
            request.cache_policy,
            _VALID_CACHE_POLICIES,
        )
        if request.cache_policy == "refresh":
            raise MCPServiceContractError(
                "cache_policy='refresh' is not supported by the read-only "
                "CodeClone MCP server. Use 'reuse' or 'off'."
            )

    @staticmethod
    def _validate_choice(
        name: str,
        value: str,
        allowed: Sequence[str] | frozenset[str],
    ) -> str:
        if value not in allowed:
            allowed_list = ", ".join(sorted(allowed))
            raise MCPServiceContractError(
                f"Invalid value for {name}: {value!r}. Expected one of: {allowed_list}."
            )
        return value

    def _validate_optional_choice(
        self,
        name: str,
        value: str | None,
        allowed: Sequence[str] | frozenset[str],
    ) -> str | None:
        if value is None:
            return None
        return self._validate_choice(name, value, allowed)

    @staticmethod
    def _resolve_root(root: str | None) -> Path:
        cleaned_root = "" if root is None else str(root).strip()
        if not cleaned_root:
            raise MCPServiceContractError(
                "MCP analysis requires an absolute repository root. "
                "Omitted or relative roots are unsafe because the MCP server "
                "working directory may not match the client workspace."
            )
        candidate = Path(cleaned_root).expanduser()
        if not candidate.is_absolute():
            raise MCPServiceContractError(
                f"MCP requires an absolute repository root; got relative root "
                f"{cleaned_root!r}. Relative roots like '.' are unsafe because "
                "the MCP server working directory may not match the client "
                "workspace."
            )
        try:
            root_path = candidate.resolve()
        except OSError as exc:
            raise MCPServiceContractError(
                f"Invalid root path '{cleaned_root}': {exc}"
            ) from exc
        if not root_path.exists():
            raise MCPServiceContractError(f"Root path does not exist: {root_path}")
        if not root_path.is_dir():
            raise MCPServiceContractError(f"Root path is not a directory: {root_path}")
        return root_path

    def _resolve_optional_root(self, root: str | None) -> Path | None:
        cleaned_root = "" if root is None else str(root).strip()
        if not cleaned_root:
            return None
        return self._resolve_root(cleaned_root)

    def _build_args(self, *, root_path: Path, request: MCPAnalysisRequest) -> Namespace:
        args = Namespace(
            root=str(root_path),
            min_loc=DEFAULT_MIN_LOC,
            min_stmt=DEFAULT_MIN_STMT,
            block_min_loc=DEFAULT_BLOCK_MIN_LOC,
            block_min_stmt=DEFAULT_BLOCK_MIN_STMT,
            segment_min_loc=DEFAULT_SEGMENT_MIN_LOC,
            segment_min_stmt=DEFAULT_SEGMENT_MIN_STMT,
            processes=None,
            cache_path=None,
            max_cache_size_mb=DEFAULT_MAX_CACHE_SIZE_MB,
            baseline=DEFAULT_BASELINE_PATH,
            max_baseline_size_mb=DEFAULT_MAX_BASELINE_SIZE_MB,
            update_baseline=False,
            fail_on_new=False,
            fail_threshold=-1,
            ci=False,
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=False,
            design_complexity_threshold=DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
            design_coupling_threshold=DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
            design_cohesion_threshold=DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
            update_metrics_baseline=False,
            metrics_baseline=DEFAULT_BASELINE_PATH,
            skip_metrics=False,
            skip_dead_code=False,
            skip_dependencies=False,
            html_out=None,
            json_out=None,
            md_out=None,
            sarif_out=None,
            text_out=None,
            no_progress=True,
            no_color=True,
            quiet=True,
            verbose=False,
            debug=False,
            open_html_report=False,
            timestamped_report_paths=False,
        )
        if request.respect_pyproject:
            try:
                config_values = load_pyproject_config(root_path)
            except ConfigValidationError as exc:
                raise MCPServiceContractError(str(exc)) from exc
            for key in sorted(_MCP_CONFIG_KEYS.intersection(config_values)):
                setattr(args, key, config_values[key])

        self._apply_request_overrides(args=args, root_path=root_path, request=request)

        if request.analysis_mode == "clones_only":
            args.skip_metrics = True
            args.skip_dead_code = True
            args.skip_dependencies = True
        else:
            args.skip_metrics = False
            args.skip_dead_code = False
            args.skip_dependencies = False

        if not validate_numeric_args(args):
            raise MCPServiceContractError(
                "Numeric analysis settings must be non-negative and thresholds "
                "must be >= -1."
            )

        return args

    def _apply_request_overrides(
        self,
        *,
        args: Namespace,
        root_path: Path,
        request: MCPAnalysisRequest,
    ) -> None:
        override_map: dict[str, object | None] = {
            "processes": request.processes,
            "min_loc": request.min_loc,
            "min_stmt": request.min_stmt,
            "block_min_loc": request.block_min_loc,
            "block_min_stmt": request.block_min_stmt,
            "segment_min_loc": request.segment_min_loc,
            "segment_min_stmt": request.segment_min_stmt,
            "max_baseline_size_mb": request.max_baseline_size_mb,
            "max_cache_size_mb": request.max_cache_size_mb,
            "design_complexity_threshold": request.complexity_threshold,
            "design_coupling_threshold": request.coupling_threshold,
            "design_cohesion_threshold": request.cohesion_threshold,
        }
        for key, value in override_map.items():
            if value is not None:
                setattr(args, key, value)

        if request.baseline_path is not None:
            args.baseline = str(
                self._resolve_optional_path(request.baseline_path, root_path)
            )
        if request.metrics_baseline_path is not None:
            args.metrics_baseline = str(
                self._resolve_optional_path(request.metrics_baseline_path, root_path)
            )
        if request.cache_path is not None:
            args.cache_path = str(
                self._resolve_optional_path(request.cache_path, root_path)
            )

    @staticmethod
    def _resolve_optional_path(value: str, root_path: Path) -> Path:
        candidate = Path(value).expanduser()
        resolved = candidate if candidate.is_absolute() else root_path / candidate
        try:
            return resolved.resolve()
        except OSError as exc:
            raise MCPServiceContractError(
                f"Invalid path '{value}' relative to '{root_path}': {exc}"
            ) from exc

    def _resolve_baseline_inputs(
        self,
        *,
        root_path: Path,
        args: Namespace,
    ) -> tuple[Path, bool, Path, bool, dict[str, object] | None]:
        baseline_path = self._resolve_optional_path(str(args.baseline), root_path)
        baseline_exists = baseline_path.exists()

        metrics_baseline_arg_path = self._resolve_optional_path(
            str(args.metrics_baseline),
            root_path,
        )
        shared_baseline_payload: dict[str, object] | None = None
        if metrics_baseline_arg_path == baseline_path:
            probe = probe_metrics_baseline_section(metrics_baseline_arg_path)
            metrics_baseline_exists = probe.has_metrics_section
            shared_baseline_payload = probe.payload
        else:
            metrics_baseline_exists = metrics_baseline_arg_path.exists()

        return (
            baseline_path,
            baseline_exists,
            metrics_baseline_arg_path,
            metrics_baseline_exists,
            shared_baseline_payload,
        )

    @staticmethod
    def _resolve_cache_path(*, root_path: Path, args: Namespace) -> Path:
        return resolve_cache_path(
            root_path=root_path,
            args=args,
            from_args=bool(args.cache_path),
            legacy_cache_path=_LEGACY_CACHE_PATH,
            console=_BufferConsole(),
        )

    @staticmethod
    def _build_cache(
        *,
        root_path: Path,
        args: Namespace,
        cache_path: Path,
        policy: CachePolicy,
    ) -> Cache:
        cache = Cache(
            cache_path,
            root=root_path,
            max_size_bytes=_as_int(args.max_cache_size_mb, 0) * 1024 * 1024,
            min_loc=_as_int(args.min_loc, DEFAULT_MIN_LOC),
            min_stmt=_as_int(args.min_stmt, DEFAULT_MIN_STMT),
            block_min_loc=_as_int(args.block_min_loc, DEFAULT_BLOCK_MIN_LOC),
            block_min_stmt=_as_int(args.block_min_stmt, DEFAULT_BLOCK_MIN_STMT),
            segment_min_loc=_as_int(args.segment_min_loc, DEFAULT_SEGMENT_MIN_LOC),
            segment_min_stmt=_as_int(
                args.segment_min_stmt,
                DEFAULT_SEGMENT_MIN_STMT,
            ),
        )
        if policy != "off":
            cache.load()
        return cache

    @staticmethod
    def _metrics_computed(analysis_mode: AnalysisMode) -> tuple[str, ...]:
        return (
            ()
            if analysis_mode == "clones_only"
            else (
                "complexity",
                "coupling",
                "cohesion",
                "health",
                "dependencies",
                "dead_code",
            )
        )

    @staticmethod
    def _load_report_document(report_json: str) -> dict[str, object]:
        return _load_report_document_payload(report_json)

    def _report_digest(self, report_document: Mapping[str, object]) -> str:
        integrity = self._as_mapping(report_document.get("integrity"))
        digest = self._as_mapping(integrity.get("digest"))
        value = digest.get("value")
        if not isinstance(value, str) or not value:
            raise MCPServiceError("Canonical report digest is missing.")
        return value

    def _build_run_summary_payload(
        self,
        *,
        run_id: str,
        root_path: Path,
        request: MCPAnalysisRequest,
        report_document: Mapping[str, object],
        baseline_state: CloneBaselineState,
        metrics_baseline_state: MetricsBaselineState,
        cache_status: CacheStatus,
        new_func: Sequence[str] | set[str],
        new_block: Sequence[str] | set[str],
        metrics_diff: MetricsDiff | None,
        warnings: Sequence[str],
        failures: Sequence[str],
    ) -> dict[str, object]:
        meta = self._as_mapping(report_document.get("meta"))
        meta_baseline = self._as_mapping(meta.get("baseline"))
        meta_metrics_baseline = self._as_mapping(meta.get("metrics_baseline"))
        meta_cache = self._as_mapping(meta.get("cache"))
        inventory = self._as_mapping(report_document.get("inventory"))
        findings = self._as_mapping(report_document.get("findings"))
        metrics = self._as_mapping(report_document.get("metrics"))
        metrics_summary = self._as_mapping(metrics.get("summary"))
        summary = self._as_mapping(findings.get("summary"))
        analysis_profile = self._summary_analysis_profile_payload(meta)
        payload = {
            "run_id": run_id,
            "root": str(root_path),
            "analysis_mode": request.analysis_mode,
            "codeclone_version": meta.get("codeclone_version", __version__),
            "report_schema_version": report_document.get(
                "report_schema_version",
                REPORT_SCHEMA_VERSION,
            ),
            "baseline": {
                "path": meta_baseline.get(
                    "path",
                    str(root_path / DEFAULT_BASELINE_PATH),
                ),
                "loaded": bool(meta_baseline.get("loaded", baseline_state.loaded)),
                "status": str(meta_baseline.get("status", baseline_state.status.value)),
                "trusted_for_diff": baseline_state.trusted_for_diff,
            },
            "metrics_baseline": {
                "path": meta_metrics_baseline.get(
                    "path",
                    str(root_path / DEFAULT_BASELINE_PATH),
                ),
                "loaded": bool(
                    meta_metrics_baseline.get(
                        "loaded",
                        metrics_baseline_state.loaded,
                    )
                ),
                "status": str(
                    meta_metrics_baseline.get(
                        "status",
                        metrics_baseline_state.status.value,
                    )
                ),
                "trusted_for_diff": metrics_baseline_state.trusted_for_diff,
            },
            "cache": {
                "path": meta_cache.get("path"),
                "status": str(meta_cache.get("status", cache_status.value)),
                "used": bool(meta_cache.get("used", False)),
                "schema_version": meta_cache.get("schema_version"),
            },
            "inventory": dict(inventory),
            "findings_summary": dict(summary),
            "health": dict(self._as_mapping(metrics_summary.get("health"))),
            "baseline_diff": {
                "new_function_clone_groups": len(new_func),
                "new_block_clone_groups": len(new_block),
                "new_clone_groups_total": len(new_func) + len(new_block),
            },
            "metrics_diff": self._metrics_diff_payload(metrics_diff),
            "warnings": list(warnings),
            "failures": list(failures),
        }
        if analysis_profile:
            payload["analysis_profile"] = analysis_profile
        payload["cache"] = self._summary_cache_payload(payload)
        payload["health"] = self._summary_health_payload(payload)
        return payload

    def _summary_payload(
        self,
        summary: Mapping[str, object],
        *,
        record: MCPRunRecord | None = None,
    ) -> dict[str, object]:
        inventory = self._as_mapping(summary.get("inventory"))
        if (
            not summary.get("run_id")
            and not record
            and "inventory" in summary
            and not summary.get("baseline")
        ):
            return {
                "focus": _FOCUS_REPOSITORY,
                "health_scope": _HEALTH_SCOPE_REPOSITORY,
                "inventory": self._summary_inventory_payload(inventory),
                "health": self._summary_health_payload(summary),
            }
        resolved_run_id = (
            record.run_id if record is not None else str(summary.get("run_id", ""))
        )
        payload: dict[str, object] = {
            "run_id": self._short_run_id(resolved_run_id) if resolved_run_id else "",
            "focus": _FOCUS_REPOSITORY,
            "health_scope": _HEALTH_SCOPE_REPOSITORY,
            "version": str(summary.get("codeclone_version", __version__)),
            "schema": str(summary.get("report_schema_version", REPORT_SCHEMA_VERSION)),
            "mode": str(summary.get("analysis_mode", "")),
            "baseline": self._summary_baseline_payload(summary),
            "metrics_baseline": self._summary_metrics_baseline_payload(summary),
            "cache": self._summary_cache_payload(summary),
            "inventory": self._summary_inventory_payload(inventory),
            "health": self._summary_health_payload(summary),
            "findings": self._summary_findings_payload(summary, record=record),
            "diff": self._summary_diff_payload(summary),
            "warnings": list(self._as_sequence(summary.get("warnings"))),
            "failures": list(self._as_sequence(summary.get("failures"))),
        }
        analysis_profile = self._summary_analysis_profile_payload(summary)
        if analysis_profile:
            payload["analysis_profile"] = analysis_profile
        return payload

    def _summary_analysis_profile_payload(
        self,
        summary: Mapping[str, object],
    ) -> dict[str, int]:
        analysis_profile = self._as_mapping(summary.get("analysis_profile"))
        if not analysis_profile:
            return {}
        keys = (
            "min_loc",
            "min_stmt",
            "block_min_loc",
            "block_min_stmt",
            "segment_min_loc",
            "segment_min_stmt",
        )
        payload = {key: _as_int(analysis_profile.get(key), -1) for key in keys}
        return {key: value for key, value in payload.items() if value >= 0}

    def _summary_baseline_payload(
        self,
        summary: Mapping[str, object],
    ) -> dict[str, object]:
        return self._summary_trusted_state_payload(summary, key="baseline")

    def _summary_metrics_baseline_payload(
        self,
        summary: Mapping[str, object],
    ) -> dict[str, object]:
        return self._summary_trusted_state_payload(summary, key="metrics_baseline")

    def _summary_trusted_state_payload(
        self,
        summary: Mapping[str, object],
        *,
        key: str,
    ) -> dict[str, object]:
        baseline = self._as_mapping(summary.get(key))
        return {
            "loaded": bool(baseline.get("loaded", False)),
            "status": str(baseline.get("status", "")),
            "trusted": bool(baseline.get("trusted_for_diff", False)),
        }

    def _summary_cache_payload(
        self,
        summary: Mapping[str, object],
    ) -> dict[str, object]:
        cache = dict(self._as_mapping(summary.get("cache")))
        if not cache:
            return {}
        return {
            "used": bool(cache.get("used", False)),
            "freshness": self._effective_freshness(summary),
        }

    def _effective_freshness(
        self,
        summary: Mapping[str, object],
    ) -> FreshnessKind:
        inventory = self._as_mapping(summary.get("inventory"))
        files = self._as_mapping(inventory.get("files"))
        analyzed = max(0, _as_int(files.get("analyzed", 0), 0))
        cached = max(0, _as_int(files.get("cached", 0), 0))
        cache = self._as_mapping(summary.get("cache"))
        cache_used = bool(cache.get("used"))
        if cache_used and cached > 0 and analyzed == 0:
            return "reused"
        if cache_used and cached > 0 and analyzed > 0:
            return "mixed"
        return "fresh"

    def _summary_inventory_payload(
        self,
        inventory: Mapping[str, object],
    ) -> dict[str, object]:
        if not inventory:
            return {}
        files = self._as_mapping(inventory.get("files"))
        code = self._as_mapping(inventory.get("code"))
        total_files = _as_int(
            files.get(
                "total_found",
                files.get(
                    "analyzed",
                    len(
                        self._as_sequence(
                            self._as_mapping(inventory.get("file_registry")).get(
                                "items"
                            )
                        )
                    ),
                ),
            ),
            0,
        )
        functions = _as_int(code.get("functions", 0), 0) + _as_int(
            code.get("methods", 0),
            0,
        )
        return {
            "files": total_files,
            "lines": _as_int(code.get("parsed_lines", 0), 0),
            "functions": functions,
            "classes": _as_int(code.get("classes", 0), 0),
        }

    def _summary_findings_payload(
        self,
        summary: Mapping[str, object],
        *,
        record: MCPRunRecord | None,
    ) -> dict[str, object]:
        findings_summary = self._as_mapping(summary.get("findings_summary"))
        if record is None:
            return {
                "total": _as_int(findings_summary.get("total", 0), 0),
                "new": 0,
                "known": 0,
                "by_family": {},
                "production": 0,
                "new_by_source_kind": self._source_kind_breakdown(()),
            }
        findings = self._base_findings(record)
        by_family: dict[str, int] = {
            "clones": 0,
            "structural": 0,
            "dead_code": 0,
            "design": 0,
        }
        new_count = 0
        known_count = 0
        production_count = 0
        new_by_source_kind = self._source_kind_breakdown(
            self._finding_source_kind(finding)
            for finding in findings
            if str(finding.get("novelty", "")).strip() == "new"
        )
        for finding in findings:
            family = str(finding.get("family", "")).strip()
            family_key = "clones" if family == FAMILY_CLONE else family
            if family_key in by_family:
                by_family[family_key] += 1
            if str(finding.get("novelty", "")).strip() == "new":
                new_count += 1
            else:
                known_count += 1
            if self._finding_source_kind(finding) == SOURCE_KIND_PRODUCTION:
                production_count += 1
        return {
            "total": len(findings),
            "new": new_count,
            "known": known_count,
            "by_family": {key: value for key, value in by_family.items() if value > 0},
            "production": production_count,
            "new_by_source_kind": new_by_source_kind,
        }

    def _summary_diff_payload(
        self,
        summary: Mapping[str, object],
    ) -> dict[str, object]:
        baseline_diff = self._as_mapping(summary.get("baseline_diff"))
        metrics_diff = self._as_mapping(summary.get("metrics_diff"))
        return {
            "new_clones": _as_int(baseline_diff.get("new_clone_groups_total", 0), 0),
            "health_delta": (
                _as_int(metrics_diff.get("health_delta", 0), 0)
                if metrics_diff
                and self._summary_health_payload(summary).get("available") is not False
                else None
            ),
        }

    def _metrics_detail_payload(
        self,
        *,
        metrics: Mapping[str, object],
        family: MetricsDetailFamily | None,
        path: str | None,
        offset: int,
        limit: int,
    ) -> dict[str, object]:
        summary = dict(self._as_mapping(metrics.get("summary")))
        families = self._as_mapping(metrics.get("families"))
        normalized_path = self._normalize_relative_path(path or "")
        if family is None and not normalized_path:
            return {
                "summary": summary,
                "_hint": "Use family and/or path parameters to access per-item detail.",
            }
        normalized_offset = max(0, offset)
        normalized_limit = max(1, min(limit, 200))
        family_names: Sequence[str] = (
            (family,) if family is not None else tuple(sorted(families))
        )
        items: list[dict[str, object]] = []
        for family_name in family_names:
            family_payload = self._as_mapping(families.get(family_name))
            for item in self._as_sequence(family_payload.get("items")):
                item_map = self._as_mapping(item)
                if normalized_path and not self._metric_item_matches_path(
                    item_map,
                    normalized_path,
                ):
                    continue
                compact_item = self._compact_metrics_item(item_map)
                if family is None:
                    compact_item = {"family": family_name, **compact_item}
                items.append(compact_item)
        if family is None:
            items.sort(
                key=lambda item: (
                    str(item.get("family", "")),
                    str(item.get("path", "")),
                    str(item.get("qualname", "")),
                    _as_int(item.get("start_line", 0), 0),
                )
            )
        page = items[normalized_offset : normalized_offset + normalized_limit]
        return {
            "family": family,
            "path": normalized_path or None,
            "offset": normalized_offset,
            "limit": normalized_limit,
            "returned": len(page),
            "total": len(items),
            "has_more": normalized_offset + len(page) < len(items),
            "items": page,
        }

    def _metric_item_matches_path(
        self,
        item: Mapping[str, object],
        normalized_path: str,
    ) -> bool:
        path_value = (
            str(item.get("relative_path", "")).strip()
            or str(item.get("path", "")).strip()
            or str(item.get("filepath", "")).strip()
            or str(item.get("file", "")).strip()
        )
        if not path_value:
            return False
        return self._path_matches(path_value, (normalized_path,))

    @staticmethod
    def _compact_metrics_item(
        item: Mapping[str, object],
    ) -> dict[str, object]:
        compact: dict[str, object] = {}
        path_value = (
            str(item.get("relative_path", "")).strip()
            or str(item.get("path", "")).strip()
            or str(item.get("filepath", "")).strip()
            or str(item.get("file", "")).strip()
        )
        if path_value:
            compact["path"] = path_value
        for key, value in item.items():
            if (
                key not in _COMPACT_ITEM_PATH_KEYS
                and value not in _COMPACT_ITEM_EMPTY_VALUES
            ):
                compact[str(key)] = value
        return compact

    @staticmethod
    def _metrics_diff_payload(
        metrics_diff: MetricsDiff | None,
    ) -> dict[str, object] | None:
        if metrics_diff is None:
            return None
        new_high_risk_functions = tuple(
            cast(Sequence[str], getattr(metrics_diff, "new_high_risk_functions", ()))
        )
        new_high_coupling_classes = tuple(
            cast(Sequence[str], getattr(metrics_diff, "new_high_coupling_classes", ()))
        )
        new_cycles = tuple(
            cast(Sequence[object], getattr(metrics_diff, "new_cycles", ()))
        )
        new_dead_code = tuple(
            cast(Sequence[str], getattr(metrics_diff, "new_dead_code", ()))
        )
        health_delta = getattr(metrics_diff, "health_delta", 0)
        return {
            "new_high_risk_functions": len(new_high_risk_functions),
            "new_high_coupling_classes": len(new_high_coupling_classes),
            "new_cycles": len(new_cycles),
            "new_dead_code": len(new_dead_code),
            "health_delta": _as_int(health_delta, 0),
        }

    def _dict_list(self, value: object) -> list[dict[str, object]]:
        return [dict(self._as_mapping(item)) for item in self._as_sequence(value)]

    @staticmethod
    def _as_mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _as_sequence(value: object) -> Sequence[object]:
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            return value
        return ()
