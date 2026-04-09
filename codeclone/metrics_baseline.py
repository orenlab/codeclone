# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from enum import Enum
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, cast

import orjson

from . import __version__
from ._json_io import read_json_object as _read_json_object
from ._json_io import write_json_document_atomically as _write_json_document_atomically
from ._schema_validation import validate_top_level_structure
from .baseline import current_python_tag
from .cache_paths import runtime_filepath_from_wire, wire_filepath_from_runtime
from .contracts import BASELINE_SCHEMA_VERSION, METRICS_BASELINE_SCHEMA_VERSION
from .errors import BaselineValidationError
from .metrics.api_surface import compare_api_surfaces
from .models import (
    ApiParamSpec,
    ApiSurfaceSnapshot,
    MetricsDiff,
    MetricsSnapshot,
    ModuleApiSurface,
    ProjectMetrics,
    PublicSymbol,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

METRICS_BASELINE_GENERATOR: Final = "codeclone"
MAX_METRICS_BASELINE_SIZE_BYTES: Final = 5 * 1024 * 1024


class MetricsBaselineStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    TOO_LARGE = "too_large"
    INVALID_JSON = "invalid_json"
    INVALID_TYPE = "invalid_type"
    MISSING_FIELDS = "missing_fields"
    MISMATCH_SCHEMA_VERSION = "mismatch_schema_version"
    MISMATCH_PYTHON_VERSION = "mismatch_python_version"
    GENERATOR_MISMATCH = "generator_mismatch"
    INTEGRITY_MISSING = "integrity_missing"
    INTEGRITY_FAILED = "integrity_failed"


METRICS_BASELINE_UNTRUSTED_STATUSES: Final[frozenset[MetricsBaselineStatus]] = (
    frozenset(
        {
            MetricsBaselineStatus.MISSING,
            MetricsBaselineStatus.TOO_LARGE,
            MetricsBaselineStatus.INVALID_JSON,
            MetricsBaselineStatus.INVALID_TYPE,
            MetricsBaselineStatus.MISSING_FIELDS,
            MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION,
            MetricsBaselineStatus.MISMATCH_PYTHON_VERSION,
            MetricsBaselineStatus.GENERATOR_MISMATCH,
            MetricsBaselineStatus.INTEGRITY_MISSING,
            MetricsBaselineStatus.INTEGRITY_FAILED,
        }
    )
)

_TOP_LEVEL_REQUIRED_KEYS = frozenset({"meta", "metrics"})
_TOP_LEVEL_ALLOWED_KEYS = _TOP_LEVEL_REQUIRED_KEYS | frozenset(
    {"clones", "api_surface"}
)
_META_REQUIRED_KEYS = frozenset(
    {"generator", "schema_version", "python_tag", "created_at", "payload_sha256"}
)
_METRICS_REQUIRED_KEYS = frozenset(
    {
        "max_complexity",
        "high_risk_functions",
        "max_coupling",
        "high_coupling_classes",
        "max_cohesion",
        "low_cohesion_classes",
        "dependency_cycles",
        "dependency_max_depth",
        "dead_code_items",
        "health_score",
        "health_grade",
    }
)
_METRICS_OPTIONAL_KEYS = frozenset(
    {
        "typing_param_permille",
        "typing_return_permille",
        "docstring_permille",
        "typing_any_count",
    }
)
_METRICS_PAYLOAD_SHA256_KEY = "metrics_payload_sha256"
_API_SURFACE_PAYLOAD_SHA256_KEY = "api_surface_payload_sha256"


def coerce_metrics_baseline_status(
    raw_status: str | MetricsBaselineStatus | None,
) -> MetricsBaselineStatus:
    if isinstance(raw_status, MetricsBaselineStatus):
        return raw_status
    if isinstance(raw_status, str):
        try:
            return MetricsBaselineStatus(raw_status)
        except ValueError:
            return MetricsBaselineStatus.INVALID_TYPE
    return MetricsBaselineStatus.INVALID_TYPE


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


def _now_utc_z() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
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
        schema_version = _require_str(meta_obj, "schema_version", path=self.path)
        python_tag = _require_str(meta_obj, "python_tag", path=self.path)
        created_at = _require_str(meta_obj, "created_at", path=self.path)
        payload_sha256 = _extract_metrics_payload_sha256(meta_obj, path=self.path)
        api_surface_payload_sha256 = _extract_optional_payload_sha256(
            meta_obj,
            key=_API_SURFACE_PAYLOAD_SHA256_KEY,
        )

        self.generator_name = generator_name
        self.generator_version = generator_version
        self.schema_version = schema_version
        self.python_tag = python_tag
        self.created_at = created_at
        self.payload_sha256 = payload_sha256
        self.api_surface_payload_sha256 = api_surface_payload_sha256
        self.snapshot = _parse_snapshot(metrics_obj, path=self.path)
        self.has_coverage_adoption_snapshot = _has_coverage_adoption_snapshot(
            metrics_obj,
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
            api_surface_snapshot=self.api_surface_snapshot,
            api_surface_root=self.path.parent,
        )
        payload_meta = cast("Mapping[str, Any]", payload["meta"])
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
        existing: dict[str, Any] | None = None
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
                existing, path=self.path
            )
            merged_schema_version = _resolve_embedded_schema_version(
                existing_meta, path=self.path
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
                merged_meta, _METRICS_PAYLOAD_SHA256_KEY, path=self.path
            )
            self.has_coverage_adoption_snapshot = True
            self.api_surface_payload_sha256 = _optional_require_str(
                merged_meta,
                _API_SURFACE_PAYLOAD_SHA256_KEY,
                path=self.path,
            )
            self.generator_name, self.generator_version = _parse_generator(
                merged_meta, path=self.path
            )
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.path, payload)
        self.is_embedded_in_clone_baseline = False
        self.schema_version = _require_str(
            payload_meta, "schema_version", path=self.path
        )
        self.python_tag = _require_str(payload_meta, "python_tag", path=self.path)
        self.created_at = _require_str(payload_meta, "created_at", path=self.path)
        self.payload_sha256 = payload_metrics_hash
        self.has_coverage_adoption_snapshot = True
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
        if not isinstance(self.payload_sha256, str):
            raise BaselineValidationError(
                "Metrics baseline integrity payload hash is missing.",
                status=MetricsBaselineStatus.INTEGRITY_MISSING,
            )
        if len(self.payload_sha256) != 64:
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
        if self.api_surface_snapshot is not None:
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
    ) -> MetricsBaseline:
        baseline = MetricsBaseline(path)
        baseline.generator_name = METRICS_BASELINE_GENERATOR
        baseline.generator_version = generator_version or __version__
        baseline.schema_version = schema_version or METRICS_BASELINE_SCHEMA_VERSION
        baseline.python_tag = python_tag or current_python_tag()
        baseline.created_at = _now_utc_z()
        baseline.snapshot = snapshot_from_project_metrics(project_metrics)
        baseline.payload_sha256 = _compute_payload_sha256(baseline.snapshot)
        baseline.has_coverage_adoption_snapshot = True
        baseline.api_surface_snapshot = project_metrics.api_surface
        baseline.api_surface_payload_sha256 = (
            _compute_api_surface_payload_sha256(
                project_metrics.api_surface,
                root=baseline.path.parent,
            )
            if project_metrics.api_surface is not None
            else None
        )
        return baseline

    def diff(self, current: ProjectMetrics) -> MetricsDiff:
        if self.snapshot is None:
            snapshot = MetricsSnapshot(
                max_complexity=0,
                high_risk_functions=(),
                max_coupling=0,
                high_coupling_classes=(),
                max_cohesion=0,
                low_cohesion_classes=(),
                dependency_cycles=(),
                dependency_max_depth=0,
                dead_code_items=(),
                health_score=0,
                health_grade="F",
                typing_param_permille=0,
                typing_return_permille=0,
                docstring_permille=0,
                typing_any_count=0,
            )
        else:
            snapshot = self.snapshot

        current_snapshot = snapshot_from_project_metrics(current)

        new_high_risk_functions = tuple(
            sorted(
                set(current_snapshot.high_risk_functions)
                - set(snapshot.high_risk_functions)
            )
        )
        new_high_coupling_classes = tuple(
            sorted(
                set(current_snapshot.high_coupling_classes)
                - set(snapshot.high_coupling_classes)
            )
        )
        new_cycles = tuple(
            sorted(
                set(current_snapshot.dependency_cycles)
                - set(snapshot.dependency_cycles)
            )
        )
        new_dead_code = tuple(
            sorted(
                set(current_snapshot.dead_code_items) - set(snapshot.dead_code_items)
            )
        )
        added_api_symbols, api_breaking_changes = compare_api_surfaces(
            baseline=self.api_surface_snapshot,
            current=current.api_surface,
            strict_types=False,
        )

        return MetricsDiff(
            new_high_risk_functions=new_high_risk_functions,
            new_high_coupling_classes=new_high_coupling_classes,
            new_cycles=new_cycles,
            new_dead_code=new_dead_code,
            health_delta=current_snapshot.health_score - snapshot.health_score,
            typing_param_permille_delta=(
                current_snapshot.typing_param_permille - snapshot.typing_param_permille
            ),
            typing_return_permille_delta=(
                current_snapshot.typing_return_permille
                - snapshot.typing_return_permille
            ),
            docstring_permille_delta=(
                current_snapshot.docstring_permille - snapshot.docstring_permille
            ),
            new_api_symbols=added_api_symbols,
            new_api_breaking_changes=api_breaking_changes,
        )


def _is_compatible_metrics_schema(
    *,
    baseline_version: str | None,
    expected_version: str,
) -> bool:
    if baseline_version is None:
        return False
    baseline_major_minor = _parse_major_minor(baseline_version)
    expected_major_minor = _parse_major_minor(expected_version)
    if baseline_major_minor is None or expected_major_minor is None:
        return baseline_version == expected_version
    baseline_major, baseline_minor = baseline_major_minor
    expected_major, expected_minor = expected_major_minor
    return baseline_major == expected_major and baseline_minor <= expected_minor


def _has_coverage_adoption_snapshot(metrics_obj: Mapping[str, object]) -> bool:
    return all(
        key in metrics_obj
        for key in (
            "typing_param_permille",
            "typing_return_permille",
            "docstring_permille",
        )
    )


def _parse_major_minor(version: str) -> tuple[int, int] | None:
    parts = version.split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1])


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    _write_json_document_atomically(
        path,
        payload,
        indent=True,
        trailing_newline=True,
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        return _read_json_object(path)
    except OSError as e:
        raise BaselineValidationError(
            f"Cannot read metrics baseline file at {path}: {e}",
            status=MetricsBaselineStatus.INVALID_JSON,
        ) from e
    except JSONDecodeError as e:
        raise BaselineValidationError(
            f"Corrupted metrics baseline file at {path}: {e}",
            status=MetricsBaselineStatus.INVALID_JSON,
        ) from e
    except TypeError:
        raise BaselineValidationError(
            f"Metrics baseline payload must be an object at {path}",
            status=MetricsBaselineStatus.INVALID_TYPE,
        ) from None


def _validate_top_level_structure(payload: dict[str, Any], *, path: Path) -> None:
    validate_top_level_structure(
        payload,
        path=path,
        required_keys=_TOP_LEVEL_REQUIRED_KEYS,
        allowed_keys=_TOP_LEVEL_ALLOWED_KEYS,
        schema_label="metrics baseline",
        missing_status=MetricsBaselineStatus.MISSING_FIELDS,
        extra_status=MetricsBaselineStatus.INVALID_TYPE,
    )


def _validate_required_keys(
    payload: Mapping[str, Any],
    required: frozenset[str],
    *,
    path: Path,
) -> None:
    missing = required - set(payload.keys())
    if missing:
        raise BaselineValidationError(
            "Invalid metrics baseline schema at "
            f"{path}: missing required fields: {', '.join(sorted(missing))}",
            status=MetricsBaselineStatus.MISSING_FIELDS,
        )


def _validate_exact_keys(
    payload: Mapping[str, Any],
    required: frozenset[str],
    *,
    path: Path,
) -> None:
    extra = set(payload.keys()) - set(required)
    if extra:
        raise BaselineValidationError(
            "Invalid metrics baseline schema at "
            f"{path}: unexpected fields: {', '.join(sorted(extra))}",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )


def _require_str(payload: Mapping[str, Any], key: str, *, path: Path) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    raise BaselineValidationError(
        f"Invalid metrics baseline schema at {path}: {key!r} must be str",
        status=MetricsBaselineStatus.INVALID_TYPE,
    )


def _extract_metrics_payload_sha256(
    payload: Mapping[str, Any],
    *,
    path: Path,
) -> str:
    direct = payload.get(_METRICS_PAYLOAD_SHA256_KEY)
    if isinstance(direct, str):
        return direct
    return _require_str(payload, "payload_sha256", path=path)


def _extract_optional_payload_sha256(
    payload: Mapping[str, Any],
    *,
    key: str,
) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _require_int(payload: Mapping[str, Any], key: str, *, path: Path) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: {key!r} must be int",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    if isinstance(value, int):
        return value
    raise BaselineValidationError(
        f"Invalid metrics baseline schema at {path}: {key!r} must be int",
        status=MetricsBaselineStatus.INVALID_TYPE,
    )


def _optional_require_str(
    payload: Mapping[str, Any],
    key: str,
    *,
    path: Path,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise BaselineValidationError(
        f"Invalid metrics baseline schema at {path}: {key!r} must be str",
        status=MetricsBaselineStatus.INVALID_TYPE,
    )


def _require_str_list(payload: Mapping[str, Any], key: str, *, path: Path) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: {key!r} must be list[str]",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    if not all(isinstance(item, str) for item in value):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: {key!r} must be list[str]",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    return value


def _parse_cycles(
    payload: Mapping[str, Any],
    *,
    key: str,
    path: Path,
) -> tuple[tuple[str, ...], ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: {key!r} must be list",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )

    cycles: list[tuple[str, ...]] = []
    for cycle in value:
        if not isinstance(cycle, list):
            raise BaselineValidationError(
                "Invalid metrics baseline schema at "
                f"{path}: {key!r} cycle item must be list[str]",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        if not all(isinstance(item, str) for item in cycle):
            raise BaselineValidationError(
                "Invalid metrics baseline schema at "
                f"{path}: {key!r} cycle item must be list[str]",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        cycles.append(tuple(cycle))
    return tuple(sorted(set(cycles)))


def _parse_generator(
    meta: Mapping[str, Any],
    *,
    path: Path,
) -> tuple[str, str | None]:
    generator = meta.get("generator")
    if isinstance(generator, str):
        version_value = meta.get("generator_version")
        if version_value is None:
            version_value = meta.get("codeclone_version")
        if version_value is None:
            return generator, None
        if not isinstance(version_value, str):
            raise BaselineValidationError(
                "Invalid metrics baseline schema at "
                f"{path}: generator_version must be str",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        return generator, version_value

    if isinstance(generator, dict):
        allowed_keys = {"name", "version"}
        extra = set(generator.keys()) - allowed_keys
        if extra:
            raise BaselineValidationError(
                f"Invalid metrics baseline schema at {path}: "
                f"unexpected generator keys: {', '.join(sorted(extra))}",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        name = generator.get("name")
        version = generator.get("version")
        if not isinstance(name, str):
            raise BaselineValidationError(
                "Invalid metrics baseline schema at "
                f"{path}: generator.name must be str",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        if version is not None and not isinstance(version, str):
            raise BaselineValidationError(
                "Invalid metrics baseline schema at "
                f"{path}: generator.version must be str",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        return name, version if isinstance(version, str) else None

    raise BaselineValidationError(
        f"Invalid metrics baseline schema at {path}: generator must be object or str",
        status=MetricsBaselineStatus.INVALID_TYPE,
    )


def _require_embedded_clone_baseline_payload(
    payload: Mapping[str, Any],
    *,
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    meta_obj = payload.get("meta")
    clones_obj = payload.get("clones")
    if not isinstance(meta_obj, dict):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: 'meta' must be object",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    if not isinstance(clones_obj, dict):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: 'clones' must be object",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    _require_str(meta_obj, "payload_sha256", path=path)
    _require_str(meta_obj, "python_tag", path=path)
    _require_str(meta_obj, "created_at", path=path)
    functions = clones_obj.get("functions")
    blocks = clones_obj.get("blocks")
    if not isinstance(functions, list) or not all(
        isinstance(item, str) for item in functions
    ):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: 'clones.functions' must be list[str]",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    if not isinstance(blocks, list) or not all(
        isinstance(item, str) for item in blocks
    ):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: 'clones.blocks' must be list[str]",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    return meta_obj, clones_obj


def _resolve_embedded_schema_version(meta: Mapping[str, Any], *, path: Path) -> str:
    raw_version = _require_str(meta, "schema_version", path=path)
    parts = raw_version.split(".")
    if len(parts) not in {2, 3} or not all(part.isdigit() for part in parts):
        raise BaselineValidationError(
            "Invalid baseline schema at "
            f"{path}: 'schema_version' must be semver string",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    major = int(parts[0])
    if major >= 2:
        return raw_version
    return BASELINE_SCHEMA_VERSION


def _parse_snapshot(
    payload: Mapping[str, Any],
    *,
    path: Path,
) -> MetricsSnapshot:
    grade = _require_str(payload, "health_grade", path=path)
    if grade not in {"A", "B", "C", "D", "F"}:
        raise BaselineValidationError(
            "Invalid metrics baseline schema at "
            f"{path}: 'health_grade' must be one of A/B/C/D/F",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )

    return MetricsSnapshot(
        max_complexity=_require_int(payload, "max_complexity", path=path),
        high_risk_functions=tuple(
            sorted(set(_require_str_list(payload, "high_risk_functions", path=path)))
        ),
        max_coupling=_require_int(payload, "max_coupling", path=path),
        high_coupling_classes=tuple(
            sorted(set(_require_str_list(payload, "high_coupling_classes", path=path)))
        ),
        max_cohesion=_require_int(payload, "max_cohesion", path=path),
        low_cohesion_classes=tuple(
            sorted(set(_require_str_list(payload, "low_cohesion_classes", path=path)))
        ),
        dependency_cycles=_parse_cycles(payload, key="dependency_cycles", path=path),
        dependency_max_depth=_require_int(payload, "dependency_max_depth", path=path),
        dead_code_items=tuple(
            sorted(set(_require_str_list(payload, "dead_code_items", path=path)))
        ),
        health_score=_require_int(payload, "health_score", path=path),
        health_grade=cast("Literal['A', 'B', 'C', 'D', 'F']", grade),
        typing_param_permille=_optional_int(
            payload,
            "typing_param_permille",
            path=path,
        ),
        typing_return_permille=_optional_int(
            payload,
            "typing_return_permille",
            path=path,
        ),
        docstring_permille=_optional_int(payload, "docstring_permille", path=path),
        typing_any_count=_optional_int(payload, "typing_any_count", path=path),
    )


def _optional_int(payload: Mapping[str, Any], key: str, *, path: Path) -> int:
    value = payload.get(key)
    if value is None:
        return 0
    return _require_int(payload, key, path=path)


def _parse_api_surface_snapshot(
    payload: object,
    *,
    path: Path,
    root: Path | None = None,
) -> ApiSurfaceSnapshot | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: 'api_surface' must be object",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    raw_modules = payload.get("modules", [])
    if not isinstance(raw_modules, list):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: "
            "'api_surface.modules' must be list",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    modules: list[ModuleApiSurface] = []
    for raw_module in raw_modules:
        if not isinstance(raw_module, dict):
            raise BaselineValidationError(
                f"Invalid metrics baseline schema at {path}: "
                "api surface module must be object",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        module = _require_str(raw_module, "module", path=path)
        wire_filepath = _require_str(raw_module, "filepath", path=path)
        filepath = runtime_filepath_from_wire(wire_filepath, root=root)
        all_declared = _require_str_list_or_none(raw_module, "all_declared", path=path)
        raw_symbols = raw_module.get("symbols", [])
        if not isinstance(raw_symbols, list):
            raise BaselineValidationError(
                f"Invalid metrics baseline schema at {path}: "
                "api surface symbols must be list",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        symbols: list[PublicSymbol] = []
        for raw_symbol in raw_symbols:
            if not isinstance(raw_symbol, dict):
                raise BaselineValidationError(
                    f"Invalid metrics baseline schema at {path}: "
                    "api surface symbol must be object",
                    status=MetricsBaselineStatus.INVALID_TYPE,
                )
            local_name = _optional_require_str(raw_symbol, "local_name", path=path)
            legacy_qualname = _optional_require_str(raw_symbol, "qualname", path=path)
            if local_name is None and legacy_qualname is None:
                raise BaselineValidationError(
                    f"Invalid metrics baseline schema at {path}: "
                    "api surface symbol requires 'local_name' or 'qualname'",
                    status=MetricsBaselineStatus.MISSING_FIELDS,
                )
            if local_name is None:
                assert legacy_qualname is not None
                qualname = legacy_qualname
            else:
                qualname = _compose_api_surface_qualname(
                    module=module,
                    local_name=local_name,
                )
            kind = _require_str(raw_symbol, "kind", path=path)
            exported_via = _require_str(raw_symbol, "exported_via", path=path)
            params_raw = raw_symbol.get("params", [])
            if not isinstance(params_raw, list):
                raise BaselineValidationError(
                    f"Invalid metrics baseline schema at {path}: "
                    "api surface params must be list",
                    status=MetricsBaselineStatus.INVALID_TYPE,
                )
            params: list[ApiParamSpec] = []
            for raw_param in params_raw:
                if not isinstance(raw_param, dict):
                    raise BaselineValidationError(
                        f"Invalid metrics baseline schema at {path}: "
                        "api param must be object",
                        status=MetricsBaselineStatus.INVALID_TYPE,
                    )
                name = _require_str(raw_param, "name", path=path)
                param_kind = _require_str(raw_param, "kind", path=path)
                has_default = raw_param.get("has_default")
                annotation_hash = _optional_require_str(
                    raw_param,
                    "annotation_hash",
                    path=path,
                )
                if not isinstance(has_default, bool):
                    raise BaselineValidationError(
                        f"Invalid metrics baseline schema at {path}: "
                        "api param 'has_default' must be bool",
                        status=MetricsBaselineStatus.INVALID_TYPE,
                    )
                params.append(
                    ApiParamSpec(
                        name=name,
                        kind=cast(
                            (
                                "Literal['pos_only', 'pos_or_kw', "
                                "'vararg', 'kw_only', 'kwarg']"
                            ),
                            param_kind,
                        ),
                        has_default=has_default,
                        annotation_hash=annotation_hash or "",
                    )
                )
            symbols.append(
                PublicSymbol(
                    qualname=qualname,
                    kind=cast(
                        "Literal['function', 'class', 'method', 'constant']",
                        kind,
                    ),
                    start_line=_require_int(raw_symbol, "start_line", path=path),
                    end_line=_require_int(raw_symbol, "end_line", path=path),
                    params=tuple(params),
                    returns_hash=_optional_require_str(
                        raw_symbol,
                        "returns_hash",
                        path=path,
                    )
                    or "",
                    exported_via=cast("Literal['all', 'name']", exported_via),
                )
            )
        modules.append(
            ModuleApiSurface(
                module=module,
                filepath=filepath,
                symbols=tuple(sorted(symbols, key=lambda item: item.qualname)),
                all_declared=tuple(all_declared) if all_declared is not None else None,
            )
        )
    return ApiSurfaceSnapshot(
        modules=tuple(sorted(modules, key=lambda item: (item.filepath, item.module)))
    )


def _require_str_list_or_none(
    payload: Mapping[str, Any],
    key: str,
    *,
    path: Path,
) -> list[str] | None:
    value = payload.get(key)
    if value is None:
        return None
    return _require_str_list(payload, key, path=path)


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
    api_surface_snapshot: ApiSurfaceSnapshot | None = None,
    api_surface_root: Path | None = None,
) -> dict[str, Any]:
    payload_sha256 = _compute_payload_sha256(snapshot)
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
        "metrics": _snapshot_payload(snapshot),
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
