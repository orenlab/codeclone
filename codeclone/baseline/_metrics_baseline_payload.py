# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import orjson

from ..cache.projection import wire_filepath_from_runtime
from ..models import ApiSurfaceSnapshot, MetricsSnapshot, ProjectMetrics
from ._metrics_baseline_contract import _API_SURFACE_PAYLOAD_SHA256_KEY


def snapshot_from_project_metrics(project_metrics: ProjectMetrics) -> MetricsSnapshot:
    return MetricsSnapshot(
        max_complexity=int(project_metrics.complexity_max),
        high_risk_functions=tuple(sorted(set(project_metrics.high_risk_functions))),
        max_coupling=int(project_metrics.coupling_max),
        high_coupling_classes=tuple(sorted(set(project_metrics.high_risk_classes))),
        max_cohesion=int(project_metrics.cohesion_max),
        low_cohesion_classes=tuple(sorted(set(project_metrics.low_cohesion_classes))),
        dependency_cycles=tuple(
            sorted({tuple(cycle) for cycle in project_metrics.dependency_cycles})
        ),
        dependency_max_depth=int(project_metrics.dependency_max_depth),
        dead_code_items=tuple(
            sorted({item.qualname for item in project_metrics.dead_code})
        ),
        health_score=int(project_metrics.health.total),
        health_grade=project_metrics.health.grade,
        typing_param_permille=_permille(
            project_metrics.typing_param_annotated,
            project_metrics.typing_param_total,
        ),
        typing_return_permille=_permille(
            project_metrics.typing_return_annotated,
            project_metrics.typing_return_total,
        ),
        docstring_permille=_permille(
            project_metrics.docstring_public_documented,
            project_metrics.docstring_public_total,
        ),
        typing_any_count=int(project_metrics.typing_any_count),
    )


def _permille(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round((1000.0 * float(numerator)) / float(denominator))


def _canonical_json(payload: object) -> str:
    return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS).decode("utf-8")


def _snapshot_payload(
    snapshot: MetricsSnapshot,
    *,
    include_adoption: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "max_complexity": int(snapshot.max_complexity),
        "high_risk_functions": list(snapshot.high_risk_functions),
        "max_coupling": int(snapshot.max_coupling),
        "high_coupling_classes": list(snapshot.high_coupling_classes),
        "max_cohesion": int(snapshot.max_cohesion),
        "low_cohesion_classes": list(snapshot.low_cohesion_classes),
        "dependency_cycles": [list(cycle) for cycle in snapshot.dependency_cycles],
        "dependency_max_depth": int(snapshot.dependency_max_depth),
        "dead_code_items": list(snapshot.dead_code_items),
        "health_score": int(snapshot.health_score),
        "health_grade": snapshot.health_grade,
    }
    if include_adoption:
        payload.update(
            {
                "typing_param_permille": int(snapshot.typing_param_permille),
                "typing_return_permille": int(snapshot.typing_return_permille),
                "docstring_permille": int(snapshot.docstring_permille),
                "typing_any_count": int(snapshot.typing_any_count),
            }
        )
    return payload


def _compute_payload_sha256(
    snapshot: MetricsSnapshot,
    *,
    include_adoption: bool = True,
) -> str:
    canonical = _canonical_json(
        _snapshot_payload(snapshot, include_adoption=include_adoption)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _has_coverage_adoption_snapshot(metrics_obj: dict[str, object]) -> bool:
    return all(
        key in metrics_obj
        for key in (
            "typing_param_permille",
            "typing_return_permille",
            "docstring_permille",
        )
    )


def _api_surface_snapshot_payload(
    snapshot: ApiSurfaceSnapshot,
    *,
    root: Path | None = None,
    legacy_qualname: bool = False,
) -> dict[str, object]:
    return {
        "modules": [
            {
                "module": module.module,
                "filepath": wire_filepath_from_runtime(module.filepath, root=root),
                "all_declared": list(module.all_declared or ()),
                "symbols": [
                    {
                        ("qualname" if legacy_qualname else "local_name"): (
                            symbol.qualname
                            if legacy_qualname
                            else _local_name_from_qualname(
                                module=module.module,
                                qualname=symbol.qualname,
                            )
                        ),
                        "kind": symbol.kind,
                        "start_line": symbol.start_line,
                        "end_line": symbol.end_line,
                        "params": [
                            {
                                "name": param.name,
                                "kind": param.kind,
                                "has_default": param.has_default,
                                "annotation_hash": param.annotation_hash,
                            }
                            for param in symbol.params
                        ],
                        "returns_hash": symbol.returns_hash,
                        "exported_via": symbol.exported_via,
                    }
                    for symbol in sorted(
                        module.symbols,
                        key=lambda item: item.qualname,
                    )
                ],
            }
            for module in sorted(
                snapshot.modules,
                key=lambda item: (item.filepath, item.module),
            )
        ]
    }


def _compute_api_surface_payload_sha256(
    snapshot: ApiSurfaceSnapshot,
    *,
    root: Path | None = None,
) -> str:
    canonical = _canonical_json(_api_surface_snapshot_payload(snapshot, root=root))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compute_legacy_api_surface_payload_sha256(
    snapshot: ApiSurfaceSnapshot,
    *,
    root: Path | None = None,
) -> str:
    canonical = _canonical_json(
        _api_surface_snapshot_payload(snapshot, root=root, legacy_qualname=True)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compose_api_surface_qualname(*, module: str, local_name: str) -> str:
    return f"{module}:{local_name}"


def _local_name_from_qualname(*, module: str, qualname: str) -> str:
    prefix = f"{module}:"
    if qualname.startswith(prefix):
        return qualname[len(prefix) :]
    return qualname


def _build_payload(
    *,
    snapshot: MetricsSnapshot,
    schema_version: str,
    python_tag: str,
    generator_name: str,
    generator_version: str,
    created_at: str,
    include_adoption: bool = True,
    api_surface_snapshot: ApiSurfaceSnapshot | None = None,
    api_surface_root: Path | None = None,
) -> dict[str, Any]:
    payload_sha256 = _compute_payload_sha256(
        snapshot,
        include_adoption=include_adoption,
    )
    payload: dict[str, Any] = {
        "meta": {
            "generator": {
                "name": generator_name,
                "version": generator_version,
            },
            "schema_version": schema_version,
            "python_tag": python_tag,
            "created_at": created_at,
            "payload_sha256": payload_sha256,
        },
        "metrics": _snapshot_payload(
            snapshot,
            include_adoption=include_adoption,
        ),
    }
    if api_surface_snapshot is not None:
        payload["meta"][_API_SURFACE_PAYLOAD_SHA256_KEY] = (
            _compute_api_surface_payload_sha256(
                api_surface_snapshot,
                root=api_surface_root,
            )
        )
        payload["api_surface"] = _api_surface_snapshot_payload(
            api_surface_snapshot,
            root=api_surface_root,
        )
    return payload


__all__ = [
    "snapshot_from_project_metrics",
]
