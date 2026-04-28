# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from types import TracebackType
from typing import Protocol

from . import _session_helpers as _helpers
from ._session_shared import (
    _CHECK_TO_DIMENSION,
    _CONFIDENCE_WEIGHT,
    _DESIGN_CHECK_CONTEXT,
    _EFFORT_WEIGHT,
    _HOTLIST_REPORT_KEYS,
    _NOVELTY_WEIGHT,
    _RUNTIME_WEIGHT,
    _SEVERITY_WEIGHT,
    _VALID_ANALYSIS_MODES,
    _VALID_CACHE_POLICIES,
    _VALID_DETAIL_LEVELS,
    _VALID_FINDING_FAMILIES,
    _VALID_FINDING_NOVELTY,
    _VALID_FINDING_SORT,
    _VALID_HOTLIST_KINDS,
    _VALID_SEVERITIES,
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CONFIDENCE_MEDIUM,
    EFFORT_MODERATE,
    FAMILY_CLONES,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_STRUCTURAL,
    SOURCE_KIND_OTHER,
    AnalysisMode,
    CodeCloneMCPRunStore,
    DetailLevel,
    FindingFamilyFilter,
    FindingNoveltyFilter,
    FindingSort,
    HotlistKind,
    Mapping,
    MCPAnalysisRequest,
    MCPFindingNotFoundError,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPServiceContractError,
    OrderedDict,
    Path,
    Sequence,
    _as_float,
    _as_int,
    _git_diff_lines_payload,
    paginate,
    resolve_finding_id,
)


class _StateLock(Protocol):
    def __enter__(self) -> object: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...


class _MCPSessionFindingMixin:
    _runs: CodeCloneMCPRunStore
    _state_lock: _StateLock
    _review_state: dict[str, OrderedDict[str, str | None]]
    _last_gate_results: dict[str, dict[str, object]]
    _spread_max_cache: dict[str, int]

    def _validate_analysis_request(self, request: MCPAnalysisRequest) -> None:
        _helpers._validate_choice(
            "analysis_mode",
            request.analysis_mode,
            _VALID_ANALYSIS_MODES,
        )
        _helpers._validate_choice(
            "cache_policy",
            request.cache_policy,
            _VALID_CACHE_POLICIES,
        )
        if request.cache_policy == "refresh":
            raise MCPServiceContractError(
                "cache_policy='refresh' is not supported by the read-only "
                "CodeClone MCP server. Use 'reuse' or 'off'."
            )
        if request.analysis_mode == "clones_only" and request.coverage_xml is not None:
            raise MCPServiceContractError(
                "coverage_xml requires analysis_mode='full' because coverage join "
                "depends on metrics-enabled analysis."
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
            cleaned = _helpers._normalize_relative_path(candidate.as_posix())
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

    def _path_filter_tuple(self, path: str | None) -> tuple[str, ...]:
        if not path:
            return ()
        cleaned = _helpers._normalize_relative_path(Path(path).as_posix())
        return (cleaned,) if cleaned else ()

    def _previous_run_for_root(self, record: MCPRunRecord) -> MCPRunRecord | None:
        previous: MCPRunRecord | None = None
        for item in self._runs.records():
            if item.run_id == record.run_id:
                return previous
            if item.root == record.root:
                previous = item
        return None

    def _latest_compatible_record(
        self,
        *,
        analysis_mode: AnalysisMode,
        root_path: Path | None = None,
    ) -> MCPRunRecord | None:
        for item in reversed(self._runs.records()):
            if root_path is not None and item.root != root_path:
                continue
            if _helpers._record_supports_analysis_mode(
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
            if _helpers._record_supports_analysis_mode(
                record,
                analysis_mode=analysis_mode,
            ):
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

    def _resolve_optional_root(self, root: str | None) -> Path | None:
        cleaned_root = "" if root is None else str(root).strip()
        if not cleaned_root:
            return None
        return _helpers._resolve_root(cleaned_root)

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
            canonical_id: _helpers._base_short_finding_id(canonical_id)
            for canonical_id in canonical_ids
        }
        grouped: dict[str, list[str]] = {}
        for canonical_id, short_name in base_ids.items():
            grouped.setdefault(short_name, []).append(canonical_id)
        canonical_to_short: dict[str, str] = {}
        short_to_canonical: dict[str, str] = {}
        for short_name, group in grouped.items():
            if len(group) == 1:
                canonical_id = group[0]
                canonical_to_short[canonical_id] = short_name
                short_to_canonical[short_name] = canonical_id
                continue
            disambiguated_ids = _helpers._disambiguated_short_finding_ids(group)
            for canonical_id, disambiguated in disambiguated_ids.items():
                canonical_to_short[canonical_id] = disambiguated
                short_to_canonical[disambiguated] = canonical_id
        return canonical_to_short, short_to_canonical

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
        canonical = resolve_finding_id(
            canonical_to_short=canonical_to_short,
            short_to_canonical=short_to_canonical,
            finding_id=finding_id,
        )
        if canonical is not None:
            return canonical
        raise MCPFindingNotFoundError(
            f"Finding id '{finding_id}' was not found in run "
            f"'{_helpers._short_run_id(record.run_id)}'."
        )

    def _base_findings(self, record: MCPRunRecord) -> list[dict[str, object]]:
        report_document = record.report_document
        findings = _helpers._as_mapping(report_document.get("findings"))
        groups = _helpers._as_mapping(findings.get("groups"))
        clone_groups = _helpers._as_mapping(groups.get(FAMILY_CLONES))
        return [
            *_helpers._dict_list(clone_groups.get("functions")),
            *_helpers._dict_list(clone_groups.get("blocks")),
            *_helpers._dict_list(clone_groups.get("segments")),
            *_helpers._dict_list(
                _helpers._as_mapping(groups.get(FAMILY_STRUCTURAL)).get("groups")
            ),
            *_helpers._dict_list(
                _helpers._as_mapping(groups.get(FAMILY_DEAD_CODE)).get("groups")
            ),
            *_helpers._dict_list(
                _helpers._as_mapping(groups.get(FAMILY_DESIGN)).get("groups")
            ),
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
                    -_helpers._severity_rank(str(finding.get("severity", ""))),
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
                        _helpers._as_mapping(
                            (priority_map or {}).get(str(finding.get("id", "")))
                        ).get("score", 0.0),
                        0.0,
                    )
                    if priority_map is not None
                    else -_as_float(
                        self._priority_score(record, finding)["score"],
                        0.0,
                    ),
                    -_helpers._severity_rank(str(finding.get("severity", ""))),
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
            "kind": _helpers._finding_kind_label(finding),
            "severity": str(finding.get("severity", "")),
            "novelty": str(finding.get("novelty", "")),
            "scope": _helpers._finding_source_kind(finding),
            "count": _as_int(finding.get("count", 0), 0),
            "spread": dict(_helpers._as_mapping(finding.get("spread"))),
            "priority": round(_as_float(finding.get("priority_score", 0.0), 0.0), 2),
        }
        clone_type = str(finding.get("clone_type", "")).strip()
        if clone_type:
            payload["type"] = clone_type
        locations = [
            _helpers._as_mapping(item)
            for item in _helpers._as_sequence(finding.get("locations"))
        ]
        if detail_level == "summary":
            remediation = _helpers._as_mapping(finding.get("remediation"))
            if remediation:
                payload["effort"] = str(remediation.get("effort", ""))
            payload["locations"] = [
                summary_location
                for summary_location in (
                    _helpers._summary_location_string(location)
                    for location in locations
                )
                if summary_location
            ]
            return payload
        remediation = _helpers._as_mapping(finding.get("remediation"))
        if remediation:
            payload["remediation"] = _helpers._project_remediation(
                remediation,
                detail_level="normal",
            )
        payload["locations"] = [
            projected
            for projected in (
                _helpers._normal_location_payload(location) for location in locations
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
            _helpers._as_mapping(finding.get("source_scope")).get("dominant_kind", "")
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
        for item in _helpers._as_sequence(finding.get("items")):
            relative_path = str(
                _helpers._as_mapping(item).get("relative_path", "")
            ).strip()
            if relative_path and _helpers._path_matches(
                relative_path,
                normalized_paths,
            ):
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
                    _helpers._as_mapping(finding.get("source_scope")).get(
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
        spread = _helpers._as_mapping(finding.get("spread"))
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
        for item in _helpers._as_sequence(finding.get("items")):
            item_map = _helpers._as_mapping(item)
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
        safe_refactor_shape = _helpers._safe_refactor_shape(suggestion)
        effort = str(getattr(suggestion, "effort", EFFORT_MODERATE))
        confidence = str(getattr(suggestion, "confidence", CONFIDENCE_MEDIUM))
        risk_level = _helpers._risk_level_for_effort(effort)
        return {
            "effort": effort,
            "priority": _as_float(getattr(suggestion, "priority", 0.0), 0.0),
            "confidence": confidence,
            "safe_refactor_shape": safe_refactor_shape,
            "steps": list(getattr(suggestion, "steps", ())),
            "risk_level": risk_level,
            "why_now": _helpers._why_now_text(
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
            if _helpers._suggestion_finding_id(suggestion) == finding_id:
                return suggestion
        return None

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
        derived = _helpers._as_mapping(record.report_document.get("derived"))
        hotlists = _helpers._as_mapping(derived.get("hotlists"))
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
                for item in _helpers._as_sequence(hotlists.get(hotlist_key))
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

    def _granular_payload(
        self,
        *,
        record: MCPRunRecord,
        check: str,
        items: Sequence[Mapping[str, object]],
        detail_level: DetailLevel,
        max_results: int,
        path: str | None,
        threshold_context: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        bounded_items = [dict(item) for item in items[: max(1, max_results)]]
        full_health = dict(_helpers._as_mapping(record.summary.get("health")))
        dimensions = _helpers._as_mapping(full_health.get("dimensions"))
        relevant_dimension = _CHECK_TO_DIMENSION.get(check)
        slim_dimensions = (
            {relevant_dimension: dimensions.get(relevant_dimension)}
            if relevant_dimension and relevant_dimension in dimensions
            else dict(dimensions)
        )
        payload: dict[str, object] = {
            "run_id": _helpers._short_run_id(record.run_id),
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
        if threshold_context:
            payload["threshold_context"] = dict(threshold_context)
        return payload

    def _design_threshold_context(
        self,
        *,
        record: MCPRunRecord,
        check: str,
        path: str | None,
        items: Sequence[Mapping[str, object]],
        requested_min: int | None = None,
    ) -> dict[str, object] | None:
        if items:
            return None
        spec = _DESIGN_CHECK_CONTEXT.get(check)
        if spec is None:
            return None
        category = str(spec["category"])
        metric = str(spec["metric"])
        operator = str(spec["operator"])
        normalized_path = _helpers._normalize_relative_path(path or "")
        metrics = _helpers._as_mapping(record.report_document.get("metrics"))
        families = _helpers._as_mapping(metrics.get("families"))
        family = _helpers._as_mapping(families.get(category))
        metric_items = [
            _helpers._as_mapping(item)
            for item in _helpers._as_sequence(family.get("items"))
            if not normalized_path
            or _helpers._metric_item_matches_path(
                _helpers._as_mapping(item),
                normalized_path,
            )
        ]
        if not metric_items:
            return None
        values = [_as_int(item.get(metric), 0) for item in metric_items]
        finding_threshold = self._design_finding_threshold(
            record=record,
            check=check,
        )
        threshold = finding_threshold
        threshold_kind = "finding_threshold"
        if requested_min is not None and requested_min > finding_threshold:
            threshold = requested_min
            threshold_kind = "requested_min"
        highest_below = _helpers._highest_below_threshold(
            values=values,
            operator=operator,
            threshold=threshold,
        )
        payload: dict[str, object] = {
            "metric": metric,
            "threshold": threshold,
            "threshold_kind": threshold_kind,
            "measured_units": len(metric_items),
        }
        if threshold_kind != "finding_threshold":
            payload["finding_threshold"] = finding_threshold
        if highest_below is not None:
            payload["highest_below_threshold"] = highest_below
        return payload

    def _design_finding_threshold(
        self,
        *,
        record: MCPRunRecord,
        check: str,
    ) -> int:
        spec = _DESIGN_CHECK_CONTEXT[check]
        category = str(spec["category"])
        default_threshold = _as_int(spec["default_threshold"])
        findings = _helpers._as_mapping(record.report_document.get("findings"))
        thresholds = _helpers._as_mapping(
            _helpers._as_mapping(findings.get("thresholds")).get("design_findings")
        )
        threshold_payload = _helpers._as_mapping(thresholds.get(category))
        if threshold_payload:
            return _as_int(threshold_payload.get("value"), default_threshold)
        request_value = {
            "complexity": record.request.complexity_threshold,
            "coupling": record.request.coupling_threshold,
            "cohesion": record.request.cohesion_threshold,
        }.get(check)
        return _as_int(request_value, default_threshold)

    def _triage_suggestion_rows(self, record: MCPRunRecord) -> list[dict[str, object]]:
        derived = _helpers._as_mapping(record.report_document.get("derived"))
        canonical_rows = _helpers._dict_list(derived.get("suggestions"))
        suggestion_source_kinds = {
            _helpers._suggestion_finding_id(
                suggestion
            ): _helpers._normalized_source_kind(
                getattr(suggestion, "source_kind", SOURCE_KIND_OTHER)
            )
            for suggestion in record.suggestions
        }
        rows: list[dict[str, object]] = []
        for row in canonical_rows:
            canonical_finding_id = str(row.get("finding_id", ""))
            action = _helpers._as_mapping(row.get("action"))
            try:
                finding_id = self._short_finding_id(
                    record,
                    self._resolve_canonical_finding_id(record, canonical_finding_id),
                )
            except MCPFindingNotFoundError:
                finding_id = _helpers._base_short_finding_id(canonical_finding_id)
            rows.append(
                {
                    "id": f"suggestion:{finding_id}",
                    "finding_id": finding_id,
                    "title": str(row.get("title", "")),
                    "summary": str(row.get("summary", "")),
                    "effort": str(action.get("effort", "")),
                    "steps": list(_helpers._as_sequence(action.get("steps"))),
                    "source_kind": suggestion_source_kinds.get(
                        canonical_finding_id,
                        SOURCE_KIND_OTHER,
                    ),
                }
            )
        return rows

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
        validated_family = _helpers._validate_choice(
            "family",
            family,
            _VALID_FINDING_FAMILIES,
        )
        validated_novelty = _helpers._validate_choice(
            "novelty",
            novelty,
            _VALID_FINDING_NOVELTY,
        )
        validated_sort = _helpers._validate_choice(
            "sort_by",
            sort_by,
            _VALID_FINDING_SORT,
        )
        validated_detail = _helpers._validate_choice(
            "detail_level",
            detail_level,
            _VALID_DETAIL_LEVELS,
        )
        validated_severity = _helpers._validate_optional_choice(
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
        page = paginate(
            filtered,
            offset=offset,
            limit=normalized_limit,
            max_limit=200,
        )
        return {
            "run_id": _helpers._short_run_id(record.run_id),
            "detail_level": validated_detail,
            "sort_by": validated_sort,
            "changed_paths": list(paths_filter),
            "offset": page.offset,
            "limit": page.limit,
            "returned": len(page.items),
            "total": page.total,
            "next_offset": page.next_offset,
            "items": page.items,
        }

    def get_finding(
        self,
        *,
        finding_id: str,
        run_id: str | None = None,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        validated_detail = _helpers._validate_choice(
            "detail_level",
            detail_level,
            _VALID_DETAIL_LEVELS,
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
            f"'{_helpers._short_run_id(record.run_id)}'."
        )

    def _service_get_finding(
        self,
        *,
        finding_id: str,
        run_id: str | None = None,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        return self.get_finding(
            finding_id=finding_id,
            run_id=run_id,
            detail_level=detail_level,
        )

    def get_remediation(
        self,
        *,
        finding_id: str,
        run_id: str | None = None,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        validated_detail = _helpers._validate_choice(
            "detail_level",
            detail_level,
            _VALID_DETAIL_LEVELS,
        )
        record = self._runs.get(run_id)
        canonical_id = self._resolve_canonical_finding_id(record, finding_id)
        finding = self._service_get_finding(
            finding_id=canonical_id,
            run_id=record.run_id,
            detail_level="full",
        )
        remediation = _helpers._as_mapping(finding.get("remediation"))
        if not remediation:
            raise MCPFindingNotFoundError(
                f"Finding id '{finding_id}' does not expose remediation guidance."
            )
        return {
            "run_id": _helpers._short_run_id(record.run_id),
            "finding_id": self._short_finding_id(record, canonical_id),
            "detail_level": validated_detail,
            "remediation": _helpers._project_remediation(
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
        validated_kind = _helpers._validate_choice("kind", kind, _VALID_HOTLIST_KINDS)
        validated_detail = _helpers._validate_choice(
            "detail_level",
            detail_level,
            _VALID_DETAIL_LEVELS,
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
            "run_id": _helpers._short_run_id(record.run_id),
            "kind": validated_kind,
            "detail_level": validated_detail,
            "changed_paths": list(paths_filter),
            "returned": min(len(rows), normalized_limit),
            "total": len(rows),
            "items": [
                dict(_helpers._as_mapping(item)) for item in rows[:normalized_limit]
            ],
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
        self._service_get_finding(
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
            "run_id": _helpers._short_run_id(record.run_id),
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
                finding = self._service_get_finding(
                    finding_id=finding_id,
                    run_id=record.run_id,
                    detail_level="full",
                )
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
            "run_id": _helpers._short_run_id(record.run_id),
            "reviewed_count": len(items),
            "items": items,
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
        validated_detail = _helpers._validate_choice(
            "detail_level",
            detail_level,
            _VALID_DETAIL_LEVELS,
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
                    _helpers._as_mapping(finding.get("facts")).get(
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
            threshold_context=self._design_threshold_context(
                record=record,
                check="complexity",
                path=path,
                items=findings,
                requested_min=min_complexity,
            ),
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
        validated_detail = _helpers._validate_choice(
            "detail_level",
            detail_level,
            _VALID_DETAIL_LEVELS,
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
        validated_detail = _helpers._validate_choice(
            "detail_level",
            detail_level,
            _VALID_DETAIL_LEVELS,
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
            threshold_context=self._design_threshold_context(
                record=record,
                check=check,
                path=path,
                items=findings,
            ),
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
        validated_detail = _helpers._validate_choice(
            "detail_level",
            detail_level,
            _VALID_DETAIL_LEVELS,
        )
        validated_min_severity = _helpers._validate_optional_choice(
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
                if _helpers._severity_rank(str(finding.get("severity", "")))
                >= _helpers._severity_rank(validated_min_severity)
            ]
        return self._granular_payload(
            record=record,
            check="dead_code",
            items=findings,
            detail_level=validated_detail,
            max_results=max_results,
            path=path,
        )
