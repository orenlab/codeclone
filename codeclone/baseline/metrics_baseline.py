# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..contracts import BASELINE_SCHEMA_VERSION, METRICS_BASELINE_SCHEMA_VERSION
from ..contracts.errors import BaselineValidationError
from ..models import ApiSurfaceSnapshot, MetricsDiff, MetricsSnapshot, ProjectMetrics
from ._metrics_baseline_contract import (
    _API_SURFACE_PAYLOAD_SHA256_KEY,
    _META_REQUIRED_KEYS,
    _METRICS_OPTIONAL_KEYS,
    _METRICS_PAYLOAD_SHA256_KEY,
    _METRICS_REQUIRED_KEYS,
    MAX_METRICS_BASELINE_SIZE_BYTES,
    METRICS_BASELINE_GENERATOR,
    METRICS_BASELINE_UNTRUSTED_STATUSES,
    MetricsBaselineStatus,
    coerce_metrics_baseline_status,
)
from ._metrics_baseline_payload import (
    _build_payload,
    _compute_api_surface_payload_sha256,
    _compute_legacy_api_surface_payload_sha256,
    _compute_payload_sha256,
    _has_coverage_adoption_snapshot,
    snapshot_from_project_metrics,
)
from ._metrics_baseline_validation import (
    _atomic_write_json,
    _extract_metrics_payload_sha256,
    _extract_optional_payload_sha256,
    _is_compatible_metrics_schema,
    _load_json_object,
    _optional_require_str,
    _parse_api_surface_snapshot,
    _parse_generator,
    _parse_snapshot,
    _require_embedded_clone_baseline_payload,
    _require_str,
    _resolve_embedded_schema_version,
    _validate_exact_keys,
    _validate_required_keys,
    _validate_top_level_structure,
)
from .diff import diff_metrics
from .trust import current_python_tag


def _now_utc_z() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class MetricsBaseline:
    __slots__ = (
        "api_surface_payload_sha256",
        "api_surface_snapshot",
        "created_at",
        "generator_name",
        "generator_version",
        "has_coverage_adoption_snapshot",
        "is_embedded_in_clone_baseline",
        "path",
        "payload_sha256",
        "python_tag",
        "schema_version",
        "snapshot",
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.generator_name: str | None = None
        self.generator_version: str | None = None
        self.schema_version: str | None = None
        self.python_tag: str | None = None
        self.created_at: str | None = None
        self.payload_sha256: str | None = None
        self.snapshot: MetricsSnapshot | None = None
        self.has_coverage_adoption_snapshot = False
        self.api_surface_payload_sha256: str | None = None
        self.api_surface_snapshot: ApiSurfaceSnapshot | None = None
        self.is_embedded_in_clone_baseline = False

    def load(
        self,
        *,
        max_size_bytes: int | None = None,
        preloaded_payload: dict[str, object] | None = None,
    ) -> None:
        try:
            exists = self.path.exists()
        except OSError as e:
            raise BaselineValidationError(
                f"Cannot stat metrics baseline file at {self.path}: {e}",
                status=MetricsBaselineStatus.INVALID_TYPE,
            ) from e
        if not exists:
            return

        size_limit = (
            MAX_METRICS_BASELINE_SIZE_BYTES
            if max_size_bytes is None
            else max_size_bytes
        )
        try:
            file_size = self.path.stat().st_size
        except OSError as e:
            raise BaselineValidationError(
                f"Cannot stat metrics baseline file at {self.path}: {e}",
                status=MetricsBaselineStatus.INVALID_TYPE,
            ) from e
        if file_size > size_limit:
            raise BaselineValidationError(
                "Metrics baseline file is too large "
                f"({file_size} bytes, max {size_limit} bytes) at {self.path}.",
                status=MetricsBaselineStatus.TOO_LARGE,
            )

        if preloaded_payload is None:
            payload = _load_json_object(self.path)
        else:
            if not isinstance(preloaded_payload, dict):
                raise BaselineValidationError(
                    f"Metrics baseline payload must be an object at {self.path}",
                    status=MetricsBaselineStatus.INVALID_TYPE,
                )
            payload = preloaded_payload

        _validate_top_level_structure(payload, path=self.path)
        self.is_embedded_in_clone_baseline = "clones" in payload

        meta_obj = payload.get("meta")
        metrics_obj = payload.get("metrics")
        if not isinstance(meta_obj, dict):
            raise BaselineValidationError(
                f"Invalid metrics baseline schema at {self.path}: "
                "'meta' must be object",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        if not isinstance(metrics_obj, dict):
            raise BaselineValidationError(
                f"Invalid metrics baseline schema at {self.path}: "
                "'metrics' must be object",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )

        _validate_required_keys(meta_obj, _META_REQUIRED_KEYS, path=self.path)
        _validate_required_keys(metrics_obj, _METRICS_REQUIRED_KEYS, path=self.path)
        _validate_exact_keys(
            metrics_obj,
            _METRICS_REQUIRED_KEYS | _METRICS_OPTIONAL_KEYS,
            path=self.path,
        )

        generator_name, generator_version = _parse_generator(meta_obj, path=self.path)
        self.generator_name = generator_name
        self.generator_version = generator_version
        self.schema_version = _require_str(meta_obj, "schema_version", path=self.path)
        self.python_tag = _require_str(meta_obj, "python_tag", path=self.path)
        self.created_at = _require_str(meta_obj, "created_at", path=self.path)
        self.payload_sha256 = _extract_metrics_payload_sha256(
            meta_obj,
            path=self.path,
        )
        self.api_surface_payload_sha256 = _extract_optional_payload_sha256(
            meta_obj,
            key=_API_SURFACE_PAYLOAD_SHA256_KEY,
        )
        self.snapshot = _parse_snapshot(metrics_obj, path=self.path)
        self.has_coverage_adoption_snapshot = _has_coverage_adoption_snapshot(
            metrics_obj
        )
        self.api_surface_snapshot = _parse_api_surface_snapshot(
            payload.get("api_surface"),
            path=self.path,
            root=self.path.parent,
        )

    def save(self) -> None:
        if self.snapshot is None:
            raise BaselineValidationError(
                "Metrics baseline snapshot is missing.",
                status=MetricsBaselineStatus.MISSING_FIELDS,
            )

        payload = _build_payload(
            snapshot=self.snapshot,
            schema_version=self.schema_version or METRICS_BASELINE_SCHEMA_VERSION,
            python_tag=self.python_tag or current_python_tag(),
            generator_name=self.generator_name or METRICS_BASELINE_GENERATOR,
            generator_version=self.generator_version or __version__,
            created_at=self.created_at or _now_utc_z(),
            include_adoption=self.has_coverage_adoption_snapshot,
            api_surface_snapshot=self.api_surface_snapshot,
            api_surface_root=self.path.parent,
        )
        payload_meta = payload.get("meta")
        if not isinstance(payload_meta, dict):
            raise BaselineValidationError(
                f"Invalid metrics baseline schema at {self.path}: "
                "'meta' must be object",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        payload_metrics_hash = _require_str(
            payload_meta,
            "payload_sha256",
            path=self.path,
        )
        payload_api_surface_hash = _optional_require_str(
            payload_meta,
            _API_SURFACE_PAYLOAD_SHA256_KEY,
            path=self.path,
        )

        existing: dict[str, object] | None = None
        try:
            if self.path.exists():
                loaded = _load_json_object(self.path)
                if "clones" in loaded:
                    existing = loaded
        except BaselineValidationError as e:
            raise BaselineValidationError(
                f"Cannot read existing baseline file at {self.path}: {e}",
                status=MetricsBaselineStatus.INVALID_JSON,
            ) from e

        if existing is not None:
            existing_meta, clones_obj = _require_embedded_clone_baseline_payload(
                existing,
                path=self.path,
            )
            merged_schema_version = _resolve_embedded_schema_version(
                existing_meta,
                path=self.path,
            )
            merged_meta = dict(existing_meta)
            merged_meta["schema_version"] = merged_schema_version
            merged_meta[_METRICS_PAYLOAD_SHA256_KEY] = payload_metrics_hash
            if payload_api_surface_hash is None:
                merged_meta.pop(_API_SURFACE_PAYLOAD_SHA256_KEY, None)
            else:
                merged_meta[_API_SURFACE_PAYLOAD_SHA256_KEY] = payload_api_surface_hash
            merged_payload: dict[str, object] = {
                "meta": merged_meta,
                "clones": clones_obj,
                "metrics": payload["metrics"],
            }
            api_surface_payload = payload.get("api_surface")
            if api_surface_payload is not None:
                merged_payload["api_surface"] = api_surface_payload
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_json(self.path, merged_payload)
            self.is_embedded_in_clone_baseline = True
            self.schema_version = merged_schema_version
            self.python_tag = _require_str(merged_meta, "python_tag", path=self.path)
            self.created_at = _require_str(merged_meta, "created_at", path=self.path)
            self.payload_sha256 = _require_str(
                merged_meta,
                _METRICS_PAYLOAD_SHA256_KEY,
                path=self.path,
            )
            self.api_surface_payload_sha256 = _optional_require_str(
                merged_meta,
                _API_SURFACE_PAYLOAD_SHA256_KEY,
                path=self.path,
            )
            self.generator_name, self.generator_version = _parse_generator(
                merged_meta,
                path=self.path,
            )
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.path, payload)
        self.is_embedded_in_clone_baseline = False
        self.schema_version = _require_str(
            payload_meta,
            "schema_version",
            path=self.path,
        )
        self.python_tag = _require_str(
            payload_meta,
            "python_tag",
            path=self.path,
        )
        self.created_at = _require_str(
            payload_meta,
            "created_at",
            path=self.path,
        )
        self.payload_sha256 = payload_metrics_hash
        self.api_surface_payload_sha256 = payload_api_surface_hash

    def verify_compatibility(self, *, runtime_python_tag: str) -> None:
        if self.generator_name != METRICS_BASELINE_GENERATOR:
            raise BaselineValidationError(
                "Metrics baseline generator mismatch: expected 'codeclone'.",
                status=MetricsBaselineStatus.GENERATOR_MISMATCH,
            )
        expected_schema = (
            BASELINE_SCHEMA_VERSION
            if self.is_embedded_in_clone_baseline
            else METRICS_BASELINE_SCHEMA_VERSION
        )
        if not _is_compatible_metrics_schema(
            baseline_version=self.schema_version,
            expected_version=expected_schema,
        ):
            raise BaselineValidationError(
                "Metrics baseline schema version mismatch: "
                f"baseline={self.schema_version}, "
                f"expected={expected_schema}.",
                status=MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION,
            )
        if self.python_tag != runtime_python_tag:
            raise BaselineValidationError(
                "Metrics baseline python tag mismatch: "
                f"baseline={self.python_tag}, current={runtime_python_tag}.",
                status=MetricsBaselineStatus.MISMATCH_PYTHON_VERSION,
            )
        self.verify_integrity()

    def verify_integrity(self) -> None:
        if self.snapshot is None:
            raise BaselineValidationError(
                "Metrics baseline snapshot is missing.",
                status=MetricsBaselineStatus.MISSING_FIELDS,
            )
        if not isinstance(self.payload_sha256, str) or len(self.payload_sha256) != 64:
            raise BaselineValidationError(
                "Metrics baseline integrity payload hash is missing.",
                status=MetricsBaselineStatus.INTEGRITY_MISSING,
            )

        expected = _compute_payload_sha256(
            self.snapshot,
            include_adoption=self.has_coverage_adoption_snapshot,
        )
        if not hmac.compare_digest(self.payload_sha256, expected):
            raise BaselineValidationError(
                "Metrics baseline integrity check failed: payload_sha256 mismatch.",
                status=MetricsBaselineStatus.INTEGRITY_FAILED,
            )

        if self.api_surface_snapshot is None:
            return
        if (
            not isinstance(self.api_surface_payload_sha256, str)
            or len(self.api_surface_payload_sha256) != 64
        ):
            raise BaselineValidationError(
                "Metrics baseline API surface integrity payload hash is missing.",
                status=MetricsBaselineStatus.INTEGRITY_MISSING,
            )

        expected_api = _compute_api_surface_payload_sha256(
            self.api_surface_snapshot,
            root=self.path.parent,
        )
        legacy_absolute_expected_api = _compute_api_surface_payload_sha256(
            self.api_surface_snapshot
        )
        legacy_expected_api = _compute_legacy_api_surface_payload_sha256(
            self.api_surface_snapshot,
            root=self.path.parent,
        )
        legacy_absolute_qualname_expected_api = (
            _compute_legacy_api_surface_payload_sha256(self.api_surface_snapshot)
        )
        if not (
            hmac.compare_digest(self.api_surface_payload_sha256, expected_api)
            or hmac.compare_digest(
                self.api_surface_payload_sha256,
                legacy_absolute_expected_api,
            )
            or hmac.compare_digest(
                self.api_surface_payload_sha256,
                legacy_expected_api,
            )
            or hmac.compare_digest(
                self.api_surface_payload_sha256,
                legacy_absolute_qualname_expected_api,
            )
        ):
            raise BaselineValidationError(
                "Metrics baseline integrity check failed: "
                "api_surface payload_sha256 mismatch.",
                status=MetricsBaselineStatus.INTEGRITY_FAILED,
            )

    @staticmethod
    def from_project_metrics(
        *,
        project_metrics: ProjectMetrics,
        path: str | Path,
        schema_version: str | None = None,
        python_tag: str | None = None,
        generator_version: str | None = None,
        include_adoption: bool = True,
        include_api_surface: bool = True,
    ) -> MetricsBaseline:
        baseline = MetricsBaseline(path)
        baseline.generator_name = METRICS_BASELINE_GENERATOR
        baseline.generator_version = generator_version or __version__
        baseline.schema_version = schema_version or METRICS_BASELINE_SCHEMA_VERSION
        baseline.python_tag = python_tag or current_python_tag()
        baseline.created_at = _now_utc_z()
        baseline.snapshot = snapshot_from_project_metrics(project_metrics)
        baseline.payload_sha256 = _compute_payload_sha256(
            baseline.snapshot,
            include_adoption=include_adoption,
        )
        baseline.has_coverage_adoption_snapshot = include_adoption
        baseline.api_surface_snapshot = (
            project_metrics.api_surface if include_api_surface else None
        )
        baseline.api_surface_payload_sha256 = (
            _compute_api_surface_payload_sha256(
                baseline.api_surface_snapshot,
                root=baseline.path.parent,
            )
            if baseline.api_surface_snapshot is not None
            else None
        )
        return baseline

    def diff(self, current: ProjectMetrics) -> MetricsDiff:
        return diff_metrics(
            baseline_snapshot=self.snapshot,
            current_snapshot=snapshot_from_project_metrics(current),
            baseline_api_surface=self.api_surface_snapshot,
            current_api_surface=current.api_surface,
        )


__all__ = [
    "BASELINE_SCHEMA_VERSION",
    "MAX_METRICS_BASELINE_SIZE_BYTES",
    "METRICS_BASELINE_GENERATOR",
    "METRICS_BASELINE_SCHEMA_VERSION",
    "METRICS_BASELINE_UNTRUSTED_STATUSES",
    "MetricsBaseline",
    "MetricsBaselineStatus",
    "coerce_metrics_baseline_status",
    "current_python_tag",
    "snapshot_from_project_metrics",
]
