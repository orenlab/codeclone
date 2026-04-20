# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ...domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
)
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence

if TYPE_CHECKING:
    pass

from ._common import (
    _analysis_profile_payload,
    _contract_path,
    _count_file_lines,
    _design_findings_thresholds_payload,
    _optional_str,
)


def _derive_inventory_code_counts(
    *,
    metrics_payload: Mapping[str, object],
    inventory_code: Mapping[str, object],
    file_list: Sequence[str],
    cached_files: int,
) -> dict[str, object]:
    complexity = _as_mapping(
        _as_mapping(metrics_payload.get("families")).get(CATEGORY_COMPLEXITY)
    )
    cohesion = _as_mapping(
        _as_mapping(metrics_payload.get("families")).get(CATEGORY_COHESION)
    )
    complexity_items = _as_sequence(complexity.get("items"))
    cohesion_items = _as_sequence(cohesion.get("items"))

    exact_entities = bool(complexity_items or cohesion_items)
    method_count = sum(
        _as_int(_as_mapping(item).get("method_count")) for item in cohesion_items
    )
    class_count = len(cohesion_items)
    function_total = max(len(complexity_items) - method_count, 0)

    if not exact_entities:
        function_total = _as_int(inventory_code.get("functions"))
        method_count = _as_int(inventory_code.get("methods"))
        class_count = _as_int(inventory_code.get("classes"))

    parsed_lines_raw = inventory_code.get("parsed_lines")
    if isinstance(parsed_lines_raw, int) and parsed_lines_raw >= 0:
        parsed_lines = parsed_lines_raw
    elif cached_files > 0 and file_list:
        parsed_lines = _count_file_lines(file_list)
    else:
        parsed_lines = _as_int(parsed_lines_raw)

    if exact_entities and ((cached_files > 0 and file_list) or parsed_lines > 0):
        scope = "analysis_root"
    elif cached_files > 0 and file_list:
        scope = "mixed"
    else:
        scope = "current_run"

    return {
        "scope": scope,
        "parsed_lines": parsed_lines,
        "functions": function_total,
        "methods": method_count,
        "classes": class_count,
    }


def _build_inventory_payload(
    *,
    inventory: Mapping[str, object] | None,
    file_list: Sequence[str],
    metrics_payload: Mapping[str, object],
    scan_root: str,
) -> dict[str, object]:
    inventory_map = _as_mapping(inventory)
    files_map = _as_mapping(inventory_map.get("files"))
    code_map = _as_mapping(inventory_map.get("code"))
    cached_files = _as_int(files_map.get("cached"))
    file_registry = [
        path
        for path in (
            _contract_path(filepath, scan_root=scan_root)[0] for filepath in file_list
        )
        if path is not None
    ]
    return {
        "files": {
            "total_found": _as_int(files_map.get("total_found"), len(file_list)),
            "analyzed": _as_int(files_map.get("analyzed")),
            "cached": cached_files,
            "skipped": _as_int(files_map.get("skipped")),
            "source_io_skipped": _as_int(files_map.get("source_io_skipped")),
        },
        "code": _derive_inventory_code_counts(
            metrics_payload=metrics_payload,
            inventory_code=code_map,
            file_list=file_list,
            cached_files=cached_files,
        ),
        "file_registry": {
            "encoding": "relative_path",
            "items": file_registry,
        },
    }


def _baseline_is_trusted(meta: Mapping[str, object]) -> bool:
    baseline = _as_mapping(meta.get("baseline"))
    return (
        baseline.get("loaded") is True
        and str(baseline.get("status", "")).strip().lower() == "ok"
    )


def _build_meta_payload(
    raw_meta: Mapping[str, object] | None,
    *,
    scan_root: str,
) -> dict[str, object]:
    meta = dict(raw_meta or {})
    metrics_computed = sorted(
        {
            str(item)
            for item in _as_sequence(meta.get("metrics_computed"))
            if str(item).strip()
        }
    )
    baseline_path, baseline_path_scope, baseline_abs = _contract_path(
        meta.get("baseline_path"),
        scan_root=scan_root,
    )
    cache_path, cache_path_scope, cache_abs = _contract_path(
        meta.get("cache_path"),
        scan_root=scan_root,
    )
    metrics_baseline_path, metrics_baseline_path_scope, metrics_baseline_abs = (
        _contract_path(
            meta.get("metrics_baseline_path"),
            scan_root=scan_root,
        )
    )
    payload: dict[str, object] = {
        "codeclone_version": str(meta.get("codeclone_version", "")),
        "project_name": str(meta.get("project_name", "")),
        "scan_root": ".",
        "python_version": str(meta.get("python_version", "")),
        "python_tag": str(meta.get("python_tag", "")),
        "analysis_mode": str(meta.get("analysis_mode", "full") or "full"),
        "report_mode": str(meta.get("report_mode", "full") or "full"),
        "computed_metric_families": metrics_computed,
        "analysis_thresholds": _design_findings_thresholds_payload(meta),
        "baseline": {
            "path": baseline_path,
            "path_scope": baseline_path_scope,
            "loaded": bool(meta.get("baseline_loaded")),
            "status": _optional_str(meta.get("baseline_status")),
            "fingerprint_version": _optional_str(
                meta.get("baseline_fingerprint_version")
            ),
            "schema_version": _optional_str(meta.get("baseline_schema_version")),
            "python_tag": _optional_str(meta.get("baseline_python_tag")),
            "generator_name": _optional_str(meta.get("baseline_generator_name")),
            "generator_version": _optional_str(meta.get("baseline_generator_version")),
            "payload_sha256": _optional_str(meta.get("baseline_payload_sha256")),
            "payload_sha256_verified": bool(
                meta.get("baseline_payload_sha256_verified")
            ),
        },
        "cache": {
            "path": cache_path,
            "path_scope": cache_path_scope,
            "used": bool(meta.get("cache_used")),
            "status": _optional_str(meta.get("cache_status")),
            "schema_version": _optional_str(meta.get("cache_schema_version")),
        },
        "metrics_baseline": {
            "path": metrics_baseline_path,
            "path_scope": metrics_baseline_path_scope,
            "loaded": bool(meta.get("metrics_baseline_loaded")),
            "status": _optional_str(meta.get("metrics_baseline_status")),
            "schema_version": _optional_str(
                meta.get("metrics_baseline_schema_version")
            ),
            "payload_sha256": _optional_str(
                meta.get("metrics_baseline_payload_sha256")
            ),
            "payload_sha256_verified": bool(
                meta.get("metrics_baseline_payload_sha256_verified")
            ),
        },
        "runtime": {
            "analysis_started_at_utc": _optional_str(
                meta.get("analysis_started_at_utc")
            ),
            "report_generated_at_utc": _optional_str(
                meta.get("report_generated_at_utc")
            ),
            "scan_root_absolute": _optional_str(meta.get("scan_root")),
            "baseline_path_absolute": baseline_abs,
            "cache_path_absolute": cache_abs,
            "metrics_baseline_path_absolute": metrics_baseline_abs,
        },
    }
    analysis_profile = _analysis_profile_payload(meta)
    if analysis_profile is not None:
        payload["analysis_profile"] = analysis_profile
    return payload
