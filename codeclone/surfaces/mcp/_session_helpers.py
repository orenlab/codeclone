# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ...cache.store import Cache
from ...contracts import REPORT_SCHEMA_VERSION
from ...domain.findings import (
    CATEGORY_CLONE,
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CATEGORY_STRUCTURAL,
    FAMILY_CLONE,
    FAMILY_DEAD_CODE,
)
from ...domain.quality import (
    EFFORT_EASY,
    EFFORT_HARD,
    EFFORT_MODERATE,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from ...domain.source_scope import (
    SOURCE_KIND_ORDER,
    SOURCE_KIND_OTHER,
)
from ...models import MetricsDiff
from ._session_runtime import resolve_cache_path
from ._session_shared import (
    _COMPACT_ITEM_EMPTY_VALUES,
    _COMPACT_ITEM_PATH_KEYS,
    _SHORT_RUN_ID_LENGTH,
    _SOURCE_KIND_BREAKDOWN_ORDER,
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_MIN_LOC,
    DEFAULT_MIN_STMT,
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
    AnalysisMode,
    CachePolicy,
    ChoiceT,
    DetailLevel,
    FreshnessKind,
    Iterable,
    Mapping,
    MCPAnalysisRequest,
    MCPRunRecord,
    MCPServiceContractError,
    MCPServiceError,
    MetricsDetailFamily,
    Namespace,
    Path,
    Sequence,
    _as_int,
    _base_short_finding_id_payload,
    _disambiguated_clone_short_ids_payload,
    _disambiguated_short_finding_id_payload,
    _leaf_symbol_name_payload,
    _load_report_document_payload,
    _suggestion_finding_id_payload,
    _summarize_metrics_diff,
)
from .payloads import short_id


def _summary_health_payload(summary: Mapping[str, object]) -> dict[str, object]:
    if str(summary.get("analysis_mode", "")) == "clones_only":
        return {"available": False, "reason": "metrics_skipped"}
    health = dict(_as_mapping(summary.get("health")))
    if health:
        return health
    return {"available": False, "reason": "unavailable"}


def _summary_health_score(summary: Mapping[str, object]) -> int | None:
    health = _summary_health_payload(summary)
    if health.get("available") is False:
        return None
    return _as_int(health.get("score", 0), 0)


def _summary_health_delta(summary: Mapping[str, object]) -> int | None:
    if _summary_health_payload(summary).get("available") is False:
        return None
    metrics_diff = _as_mapping(summary.get("metrics_diff"))
    return _as_int(metrics_diff.get("health_delta", 0), 0)


def _severity_rank(severity: str) -> int:
    return {
        SEVERITY_CRITICAL: 3,
        SEVERITY_WARNING: 2,
        SEVERITY_INFO: 1,
    }.get(severity, 0)


def _validate_choice(
    name: str,
    value: ChoiceT,
    allowed: Sequence[str] | frozenset[str],
) -> ChoiceT:
    if value not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise MCPServiceContractError(
            f"Invalid value for {name}: {value!r}. Expected one of: {allowed_list}."
        )
    return value


def _validate_optional_choice(
    name: str,
    value: ChoiceT | None,
    allowed: Sequence[str] | frozenset[str],
) -> ChoiceT | None:
    if value is None:
        return None
    return _validate_choice(name, value, allowed)


def _metrics_detail_family(value: str | None) -> MetricsDetailFamily | None:
    match value:
        case "complexity":
            return "complexity"
        case "coupling":
            return "coupling"
        case "cohesion":
            return "cohesion"
        case "coverage_adoption":
            return "coverage_adoption"
        case "coverage_join":
            return "coverage_join"
        case "dependencies":
            return "dependencies"
        case "dead_code":
            return "dead_code"
        case "api_surface":
            return "api_surface"
        case "god_modules" | "overloaded_modules":
            return "overloaded_modules"
        case "health":
            return "health"
        case _:
            return None


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _string_rows(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _dict_list(value: object) -> list[dict[str, object]]:
    return [dict(_as_mapping(item)) for item in _as_sequence(value)]


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _short_run_id(run_id: str) -> str:
    return short_id(run_id, length=_SHORT_RUN_ID_LENGTH)


def _normalize_relative_path(path: str) -> str:
    cleaned = path.strip()
    if cleaned == ".":
        return ""
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.rstrip("/")
    if ".." in Path(cleaned).parts:
        raise MCPServiceContractError(f"path traversal not allowed: {path}")
    return cleaned


def _path_matches(relative_path: str, changed_paths: Sequence[str]) -> bool:
    return any(
        relative_path == candidate or relative_path.startswith(candidate + "/")
        for candidate in changed_paths
    )


def _record_supports_analysis_mode(
    record: MCPRunRecord,
    *,
    analysis_mode: AnalysisMode,
) -> bool:
    record_mode = record.request.analysis_mode
    if analysis_mode == "clones_only":
        return record_mode in {"clones_only", "full"}
    return record_mode == "full"


def _resolve_root(root: str | None) -> Path:
    if not isinstance(root, str) or not root.strip():
        raise MCPServiceContractError(
            "CodeClone MCP analyze_repository requires an absolute repository root."
        )
    root_path = Path(root).expanduser()
    if not root_path.is_absolute():
        raise MCPServiceContractError(
            "CodeClone MCP analyze_repository requires an absolute repository root."
        )
    try:
        resolved = root_path.resolve()
    except OSError as exc:
        raise MCPServiceContractError(
            f"Unable to resolve repository root '{root}': {exc}"
        ) from exc
    if not resolved.exists():
        raise MCPServiceContractError(f"Repository root '{resolved}' does not exist.")
    if not resolved.is_dir():
        raise MCPServiceContractError(
            f"Repository root '{resolved}' is not a directory."
        )
    return resolved


def _resolve_optional_path(value: str, root_path: Path) -> Path:
    candidate = Path(value).expanduser()
    resolved = candidate if candidate.is_absolute() else root_path / candidate
    try:
        return resolved.resolve()
    except OSError as exc:
        raise MCPServiceContractError(
            f"Invalid path '{value}' relative to '{root_path}': {exc}"
        ) from exc


def _base_short_finding_id(canonical_id: str) -> str:
    return _base_short_finding_id_payload(canonical_id)


def _disambiguated_short_finding_id(canonical_id: str) -> str:
    return _disambiguated_short_finding_id_payload(canonical_id)


def _disambiguated_short_finding_ids(
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
        canonical_id: _disambiguated_short_finding_id(canonical_id)
        for canonical_id in canonical_ids
    }


def _leaf_symbol_name(value: object) -> str:
    return _leaf_symbol_name_payload(value)


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


def _summary_location_string(location: Mapping[str, object]) -> str:
    path = str(location.get("file", "")).strip()
    line = _as_int(location.get("line", 0), 0)
    if not path:
        return ""
    return f"{path}:{line}" if line > 0 else path


def _normal_location_payload(location: Mapping[str, object]) -> dict[str, object]:
    path = str(location.get("file", "")).strip()
    if not path:
        return {}
    payload: dict[str, object] = {
        "path": path,
        "line": _as_int(location.get("line", 0), 0),
        "end_line": _as_int(location.get("end_line", 0), 0),
    }
    symbol = _leaf_symbol_name(location.get("symbol"))
    if symbol:
        payload["symbol"] = symbol
    return payload


def _suggestion_finding_id(suggestion: object) -> str:
    return _suggestion_finding_id_payload(suggestion)


def _project_remediation(
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
    projected["steps"] = list(_as_sequence(remediation.get("steps")))
    return projected


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


def _risk_level_for_effort(effort: str) -> str:
    return {
        EFFORT_EASY: "low",
        EFFORT_MODERATE: "medium",
        EFFORT_HARD: "high",
    }.get(effort, "medium")


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


def _highest_below_threshold(
    *,
    values: Sequence[int],
    operator: str,
    threshold: int,
) -> int | None:
    if operator == ">":
        below = [value for value in values if value <= threshold]
    elif operator == ">=":
        below = [value for value in values if value < threshold]
    else:
        return None
    return max(below) if below else None


def _normalized_source_kind(value: object) -> str:
    normalized = str(value).strip().lower()
    if normalized in SOURCE_KIND_ORDER:
        return normalized
    return SOURCE_KIND_OTHER


def _finding_source_kind(finding: Mapping[str, object]) -> str:
    source_scope = _as_mapping(finding.get("source_scope"))
    return _normalized_source_kind(source_scope.get("dominant_kind"))


def _source_kind_breakdown(source_kinds: Iterable[object]) -> dict[str, int]:
    breakdown = dict.fromkeys(_SOURCE_KIND_BREAKDOWN_ORDER, 0)
    for value in source_kinds:
        breakdown[_normalized_source_kind(value)] += 1
    return breakdown


def _metric_item_matches_path(item: Mapping[str, object], normalized_path: str) -> bool:
    path_value = (
        str(item.get("relative_path", "")).strip()
        or str(item.get("path", "")).strip()
        or str(item.get("filepath", "")).strip()
        or str(item.get("file", "")).strip()
    )
    if not path_value:
        return False
    return _path_matches(path_value, (normalized_path,))


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


def _resolve_cache_path(*, root_path: Path, args: Namespace) -> Path:
    return resolve_cache_path(root_path=root_path, args=args)


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
        segment_min_stmt=_as_int(args.segment_min_stmt, DEFAULT_SEGMENT_MIN_STMT),
        collect_api_surface=bool(getattr(args, "api_surface", False)),
    )
    if policy != "off":
        cache.load()
    return cache


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


def _load_report_document(report_json: str) -> dict[str, object]:
    return _load_report_document_payload(report_json)


def _report_digest(report_document: Mapping[str, object]) -> str:
    integrity = _as_mapping(report_document.get("integrity"))
    digest = _as_mapping(integrity.get("digest"))
    value = digest.get("value")
    if not isinstance(value, str) or not value:
        raise MCPServiceError("Canonical report digest is missing.")
    return value


def _summary_analysis_profile_payload(summary: Mapping[str, object]) -> dict[str, int]:
    analysis_profile = _as_mapping(summary.get("analysis_profile"))
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


def _summary_trusted_state_payload(
    summary: Mapping[str, object],
    *,
    key: str,
) -> dict[str, object]:
    baseline = _as_mapping(summary.get(key))
    trusted = bool(baseline.get("trusted_for_diff", False))
    payload: dict[str, object] = {
        "loaded": bool(baseline.get("loaded", False)),
        "status": str(baseline.get("status", "")),
        "trusted": trusted,
    }
    if key == "baseline":
        payload["compared_without_valid_baseline"] = not trusted
        baseline_python_tag = baseline.get("python_tag")
        runtime_python_tag = summary.get("python_tag")
        if isinstance(baseline_python_tag, str) and baseline_python_tag.strip():
            payload["baseline_python_tag"] = baseline_python_tag
        if isinstance(runtime_python_tag, str) and runtime_python_tag.strip():
            payload["runtime_python_tag"] = runtime_python_tag
    return payload


def _summary_cache_payload(summary: Mapping[str, object]) -> dict[str, object]:
    cache = dict(_as_mapping(summary.get("cache")))
    if not cache:
        return {}
    return {
        "used": bool(cache.get("used", False)),
        "freshness": _effective_freshness(summary),
    }


def _effective_freshness(summary: Mapping[str, object]) -> FreshnessKind:
    inventory = _as_mapping(summary.get("inventory"))
    files = _as_mapping(inventory.get("files"))
    analyzed = max(0, _as_int(files.get("analyzed", 0), 0))
    cached = max(0, _as_int(files.get("cached", 0), 0))
    cache = _as_mapping(summary.get("cache"))
    cache_used = bool(cache.get("used"))
    if cache_used and cached > 0 and analyzed == 0:
        return "reused"
    if cache_used and cached > 0 and analyzed > 0:
        return "mixed"
    return "fresh"


def _summary_inventory_payload(inventory: Mapping[str, object]) -> dict[str, object]:
    if not inventory:
        return {}
    files = _as_mapping(inventory.get("files"))
    code = _as_mapping(inventory.get("code"))
    total_files = _as_int(
        files.get(
            "total_found",
            files.get(
                "analyzed",
                len(
                    _as_sequence(
                        _as_mapping(inventory.get("file_registry")).get("items")
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


def _summary_diff_payload(summary: Mapping[str, object]) -> dict[str, object]:
    baseline_diff = _as_mapping(summary.get("baseline_diff"))
    metrics_diff = _as_mapping(summary.get("metrics_diff"))
    return {
        "new_clones": _as_int(baseline_diff.get("new_clone_groups_total", 0), 0),
        "health_delta": (
            _as_int(metrics_diff.get("health_delta", 0), 0)
            if (
                metrics_diff
                and _summary_health_payload(summary).get("available") is not False
            )
            else None
        ),
        "typing_param_permille_delta": _as_int(
            metrics_diff.get("typing_param_permille_delta", 0),
            0,
        ),
        "typing_return_permille_delta": _as_int(
            metrics_diff.get("typing_return_permille_delta", 0),
            0,
        ),
        "docstring_permille_delta": _as_int(
            metrics_diff.get("docstring_permille_delta", 0),
            0,
        ),
        "api_breaking_changes": _as_int(metrics_diff.get("api_breaking_changes", 0), 0),
        "new_api_symbols": _as_int(metrics_diff.get("new_api_symbols", 0), 0),
    }


def _summary_coverage_join_payload(record: MCPRunRecord) -> dict[str, object]:
    metrics = _as_mapping(record.report_document.get("metrics"))
    families = _as_mapping(metrics.get("families"))
    coverage_join = _as_mapping(families.get("coverage_join"))
    summary = _as_mapping(coverage_join.get("summary"))
    if not summary:
        return {}
    payload: dict[str, object] = {
        "status": str(summary.get("status", "")).strip(),
        "overall_permille": _as_int(summary.get("overall_permille", 0), 0),
        "coverage_hotspots": _as_int(summary.get("coverage_hotspots", 0), 0),
        "scope_gap_hotspots": _as_int(summary.get("scope_gap_hotspots", 0), 0),
        "hotspot_threshold_percent": _as_int(
            summary.get("hotspot_threshold_percent", 0),
            0,
        ),
    }
    source_value = summary.get("source")
    source = source_value.strip() if isinstance(source_value, str) else ""
    if source:
        payload["source"] = source
    invalid_reason_value = summary.get("invalid_reason")
    invalid_reason = (
        invalid_reason_value.strip() if isinstance(invalid_reason_value, str) else ""
    )
    if invalid_reason:
        payload["invalid_reason"] = invalid_reason
    return payload


def _compact_metrics_item(item: Mapping[str, object]) -> dict[str, object]:
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


def _metrics_diff_payload(metrics_diff: MetricsDiff | None) -> dict[str, object] | None:
    payload = _summarize_metrics_diff(metrics_diff)
    return dict(payload) if payload is not None else None


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


def _finding_display_location(finding: Mapping[str, object]) -> str:
    locations = _as_sequence(finding.get("locations"))
    if not locations:
        return "(unknown)"
    first = locations[0]
    if isinstance(first, str):
        return first
    location = _as_mapping(first)
    path = str(location.get("path", location.get("file", ""))).strip()
    if not path:
        return "(unknown)"
    line = _as_int(location.get("line", 0), 0)
    return f"{path}:{line}" if line > 0 else path


def _render_pr_summary_markdown(payload: Mapping[str, object]) -> str:
    health = _as_mapping(payload.get("health"))
    score = health.get("score", "n/a")
    grade = health.get("grade", "n/a")
    delta = _as_int(payload.get("health_delta", 0), 0)
    changed_items = [
        _as_mapping(item)
        for item in _as_sequence(payload.get("new_findings_in_changed_files"))
    ]
    resolved = [_as_mapping(item) for item in _as_sequence(payload.get("resolved"))]
    blocking_gates = [
        str(item) for item in _as_sequence(payload.get("blocking_gates")) if str(item)
    ]
    health_line = (
        "Health: "
        f"{score}/100 ({grade}) | Delta: {delta:+d} | "
        f"Verdict: {payload.get('verdict', 'stable')}"
        if payload.get("health_delta") is not None
        else (
            "Health: "
            f"{score}/100 ({grade}) | Delta: n/a | "
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
                    f"`{_finding_display_location(item)}`"
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
                f"- {item.get('kind', 'finding')} in "
                f"`{_finding_display_location(item)}`"
                for item in resolved[:10]
            ]
        )
    lines.extend(["", "### Blocking gates"])
    if not blocking_gates:
        lines.append("- none")
    else:
        lines.extend([f"- `{reason}`" for reason in blocking_gates])
    return "\n".join(lines)
