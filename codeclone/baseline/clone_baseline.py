# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hmac
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .. import __version__
from ..contracts import (
    BASELINE_FINGERPRINT_VERSION,
    BASELINE_SCHEMA_VERSION,
)
from ..contracts.errors import BaselineValidationError
from ..utils.json_io import (
    write_json_document_atomically as _write_json_document_atomically,
)
from ..utils.schema_validation import validate_top_level_structure
from . import trust as _trust
from .diff import diff_clone_groups

if TYPE_CHECKING:
    from collections.abc import Mapping

_TOP_LEVEL_REQUIRED_KEYS = {"meta", "clones"}
_TOP_LEVEL_OPTIONAL_KEYS = {"metrics", "api_surface"}
_TOP_LEVEL_ALLOWED_KEYS = _TOP_LEVEL_REQUIRED_KEYS | _TOP_LEVEL_OPTIONAL_KEYS
_META_REQUIRED_KEYS = {
    "generator",
    "schema_version",
    "fingerprint_version",
    "python_tag",
    "created_at",
    "payload_sha256",
}
_CLONES_REQUIRED_KEYS = {"functions", "blocks"}
_FUNCTION_ID_RE = re.compile(r"^[0-9a-f]{40}\|(?:\d+-\d+|\d+\+)$")
_BLOCK_ID_RE = re.compile(r"^[0-9a-f]{40}\|[0-9a-f]{40}\|[0-9a-f]{40}\|[0-9a-f]{40}$")


class Baseline:
    __slots__ = (
        "blocks",
        "created_at",
        "fingerprint_version",
        "functions",
        "generator",
        "generator_version",
        "path",
        "payload_sha256",
        "python_tag",
        "schema_version",
    )

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.functions: set[str] = set()
        self.blocks: set[str] = set()
        self.generator: str | None = None
        self.schema_version: str | None = None
        self.fingerprint_version: str | None = None
        self.python_tag: str | None = None
        self.created_at: str | None = None
        self.payload_sha256: str | None = None
        self.generator_version: str | None = None

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
                f"Cannot stat baseline file at {self.path}: {e}",
                status=_trust.BaselineStatus.INVALID_TYPE,
            ) from e
        if not exists:
            return

        size_limit = (
            _trust.MAX_BASELINE_SIZE_BYTES if max_size_bytes is None else max_size_bytes
        )
        size = _trust._safe_stat_size(self.path)
        if size > size_limit:
            raise BaselineValidationError(
                "Baseline file is too large "
                f"({size} bytes, max {size_limit} bytes) at {self.path}. "
                "Increase --max-baseline-size-mb or regenerate baseline.",
                status=_trust.BaselineStatus.TOO_LARGE,
            )

        if preloaded_payload is None:
            payload = _trust._load_json_object(self.path)
        else:
            if not isinstance(preloaded_payload, dict):
                raise BaselineValidationError(
                    f"Baseline payload must be an object at {self.path}",
                    status=_trust.BaselineStatus.INVALID_TYPE,
                )
            payload = preloaded_payload
        if _is_legacy_baseline_payload(payload):
            raise BaselineValidationError(
                "Baseline format is legacy (<=1.3.x) and must be regenerated. "
                "Please run --update-baseline.",
                status=_trust.BaselineStatus.MISSING_FIELDS,
            )

        _validate_top_level_structure(payload, path=self.path)

        meta_obj = payload.get("meta")
        clones_obj = payload.get("clones")
        if not isinstance(meta_obj, dict):
            raise BaselineValidationError(
                f"Invalid baseline schema at {self.path}: 'meta' must be object",
                status=_trust.BaselineStatus.INVALID_TYPE,
            )
        if not isinstance(clones_obj, dict):
            raise BaselineValidationError(
                f"Invalid baseline schema at {self.path}: 'clones' must be object",
                status=_trust.BaselineStatus.INVALID_TYPE,
            )

        _validate_required_keys(meta_obj, _META_REQUIRED_KEYS, path=self.path)
        _validate_required_keys(clones_obj, _CLONES_REQUIRED_KEYS, path=self.path)
        _validate_exact_clone_keys(clones_obj, path=self.path)

        generator, generator_version = _trust._parse_generator_meta(
            meta_obj,
            path=self.path,
        )
        schema_version = _trust._require_semver_str(
            meta_obj,
            "schema_version",
            path=self.path,
        )
        schema_major, _, _ = _trust._parse_semver(
            schema_version,
            key="schema_version",
            path=self.path,
        )
        if schema_major < 2 and "metrics" in payload:
            raise BaselineValidationError(
                f"Invalid baseline schema at {self.path}: "
                "top-level 'metrics' requires baseline schema >= 2.0.",
                status=_trust.BaselineStatus.MISMATCH_SCHEMA_VERSION,
            )
        fingerprint_version = _trust._require_str(
            meta_obj,
            "fingerprint_version",
            path=self.path,
        )
        python_tag = _trust._require_python_tag(meta_obj, "python_tag", path=self.path)
        created_at = _trust._require_utc_iso8601_z(
            meta_obj,
            "created_at",
            path=self.path,
        )
        payload_sha256 = _trust._require_str(meta_obj, "payload_sha256", path=self.path)

        function_ids = _trust._require_sorted_unique_ids(
            clones_obj,
            "functions",
            pattern=_FUNCTION_ID_RE,
            path=self.path,
        )
        block_ids = _trust._require_sorted_unique_ids(
            clones_obj,
            "blocks",
            pattern=_BLOCK_ID_RE,
            path=self.path,
        )

        self.generator = generator
        self.schema_version = schema_version
        self.fingerprint_version = fingerprint_version
        self.python_tag = python_tag
        self.created_at = created_at
        self.payload_sha256 = payload_sha256
        self.generator_version = generator_version
        self.functions = set(function_ids)
        self.blocks = set(block_ids)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _baseline_payload(
            functions=self.functions,
            blocks=self.blocks,
            generator=self.generator,
            schema_version=self.schema_version,
            fingerprint_version=self.fingerprint_version,
            python_tag=self.python_tag,
            generator_version=self.generator_version,
            created_at=self.created_at,
        )
        (
            preserved_metrics,
            preserved_metrics_hash,
            preserved_api_surface,
            preserved_api_surface_hash,
        ) = _preserve_embedded_metrics(self.path)
        if preserved_metrics is not None:
            payload["metrics"] = preserved_metrics
            if preserved_metrics_hash is not None:
                meta_obj = payload.get("meta")
                if isinstance(meta_obj, dict):
                    meta_obj["metrics_payload_sha256"] = preserved_metrics_hash
                    if preserved_api_surface_hash is not None:
                        meta_obj["api_surface_payload_sha256"] = (
                            preserved_api_surface_hash
                        )
        if preserved_api_surface is not None:
            payload["api_surface"] = preserved_api_surface
        _atomic_write_json(self.path, payload)

        meta_obj = payload.get("meta")
        if not isinstance(meta_obj, dict):
            return

        generator_obj = meta_obj.get("generator")
        if isinstance(generator_obj, dict):
            generator_name = generator_obj.get("name")
            generator_version = generator_obj.get("version")
            if isinstance(generator_name, str):
                self.generator = generator_name
            if isinstance(generator_version, str):
                self.generator_version = generator_version
        elif isinstance(generator_obj, str):
            self.generator = generator_obj

        schema_version = meta_obj.get("schema_version")
        fingerprint_version = meta_obj.get("fingerprint_version")
        python_tag = meta_obj.get("python_tag")
        created_at = meta_obj.get("created_at")
        payload_sha256 = meta_obj.get("payload_sha256")

        if isinstance(schema_version, str):
            self.schema_version = schema_version
        if isinstance(fingerprint_version, str):
            self.fingerprint_version = fingerprint_version
        if isinstance(python_tag, str):
            self.python_tag = python_tag
        if isinstance(created_at, str):
            self.created_at = created_at
        if isinstance(payload_sha256, str):
            self.payload_sha256 = payload_sha256

    def verify_compatibility(self, *, current_python_tag: str) -> None:
        if self.generator != _trust.BASELINE_GENERATOR:
            raise BaselineValidationError(
                "Baseline generator mismatch: expected 'codeclone'.",
                status=_trust.BaselineStatus.GENERATOR_MISMATCH,
            )
        if self.schema_version is None:
            raise BaselineValidationError(
                "Baseline schema version is missing.",
                status=_trust.BaselineStatus.MISSING_FIELDS,
            )
        if self.fingerprint_version is None:
            raise BaselineValidationError(
                "Baseline fingerprint version is missing.",
                status=_trust.BaselineStatus.MISSING_FIELDS,
            )
        if self.python_tag is None:
            raise BaselineValidationError(
                "Baseline python_tag is missing.",
                status=_trust.BaselineStatus.MISSING_FIELDS,
            )

        schema_major, schema_minor, _ = _trust._parse_semver(
            self.schema_version,
            key="schema_version",
            path=self.path,
        )
        max_minor = _trust._BASELINE_SCHEMA_MAX_MINOR_BY_MAJOR.get(schema_major)
        if max_minor is None:
            supported = ",".join(
                str(major)
                for major in sorted(_trust._BASELINE_SCHEMA_MAX_MINOR_BY_MAJOR)
            )
            raise BaselineValidationError(
                "Baseline schema version mismatch: "
                f"baseline={self.schema_version}, "
                f"supported_majors={supported}.",
                status=_trust.BaselineStatus.MISMATCH_SCHEMA_VERSION,
            )
        if schema_minor > max_minor:
            raise BaselineValidationError(
                "Baseline schema version is newer than supported: "
                f"baseline={self.schema_version}, "
                f"max={schema_major}.{max_minor}.",
                status=_trust.BaselineStatus.MISMATCH_SCHEMA_VERSION,
            )
        if self.fingerprint_version != BASELINE_FINGERPRINT_VERSION:
            raise BaselineValidationError(
                "Baseline fingerprint version mismatch: "
                f"baseline={self.fingerprint_version}, "
                f"expected={BASELINE_FINGERPRINT_VERSION}.",
                status=_trust.BaselineStatus.MISMATCH_FINGERPRINT_VERSION,
            )
        if self.python_tag != current_python_tag:
            raise BaselineValidationError(
                "Baseline python tag mismatch: "
                f"baseline={self.python_tag}, current={current_python_tag}.",
                status=_trust.BaselineStatus.MISMATCH_PYTHON_VERSION,
            )
        self.verify_integrity()

    def verify_integrity(self) -> None:
        if not isinstance(self.payload_sha256, str):
            raise BaselineValidationError(
                "Baseline integrity payload hash is missing.",
                status=_trust.BaselineStatus.INTEGRITY_MISSING,
            )
        if len(self.payload_sha256) != 64:
            raise BaselineValidationError(
                "Baseline integrity payload hash is missing.",
                status=_trust.BaselineStatus.INTEGRITY_MISSING,
            )
        try:
            int(self.payload_sha256, 16)
        except ValueError as e:
            raise BaselineValidationError(
                "Baseline integrity payload hash is missing.",
                status=_trust.BaselineStatus.INTEGRITY_MISSING,
            ) from e
        if self.schema_version is None:
            raise BaselineValidationError(
                "Baseline schema version is missing for integrity validation.",
                status=_trust.BaselineStatus.MISSING_FIELDS,
            )
        if self.fingerprint_version is None:
            raise BaselineValidationError(
                "Baseline fingerprint version is missing for integrity validation.",
                status=_trust.BaselineStatus.MISSING_FIELDS,
            )
        if self.python_tag is None:
            raise BaselineValidationError(
                "Baseline python_tag is missing for integrity validation.",
                status=_trust.BaselineStatus.MISSING_FIELDS,
            )
        expected = _trust._compute_payload_sha256(
            functions=self.functions,
            blocks=self.blocks,
            fingerprint_version=self.fingerprint_version,
            python_tag=self.python_tag,
        )
        if not hmac.compare_digest(self.payload_sha256, expected):
            raise BaselineValidationError(
                "Baseline integrity check failed: payload_sha256 mismatch.",
                status=_trust.BaselineStatus.INTEGRITY_FAILED,
            )

    @staticmethod
    def from_groups(
        func_groups: Mapping[str, object],
        block_groups: Mapping[str, object],
        path: str | Path = "",
        schema_version: str | None = None,
        fingerprint_version: str | None = None,
        python_tag: str | None = None,
        generator_version: str | None = None,
    ) -> Baseline:
        baseline = Baseline(path)
        baseline.functions = set(func_groups.keys())
        baseline.blocks = set(block_groups.keys())
        baseline.generator = _trust.BASELINE_GENERATOR
        baseline.schema_version = schema_version or BASELINE_SCHEMA_VERSION
        baseline.fingerprint_version = (
            fingerprint_version or BASELINE_FINGERPRINT_VERSION
        )
        baseline.python_tag = python_tag or _trust.current_python_tag()
        baseline.generator_version = generator_version or __version__
        return baseline

    def diff(
        self, func_groups: Mapping[str, object], block_groups: Mapping[str, object]
    ) -> tuple[set[str], set[str]]:
        return diff_clone_groups(
            known_functions=self.functions,
            known_blocks=self.blocks,
            func_groups=func_groups,
            block_groups=block_groups,
        )


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    _write_json_document_atomically(
        path,
        payload,
        indent=True,
        trailing_newline=True,
    )


def _validate_top_level_structure(payload: dict[str, object], *, path: Path) -> None:
    validate_top_level_structure(
        payload,
        path=path,
        required_keys=_TOP_LEVEL_REQUIRED_KEYS,
        allowed_keys=_TOP_LEVEL_ALLOWED_KEYS,
        schema_label="baseline",
        missing_status=_trust.BaselineStatus.MISSING_FIELDS,
        extra_status=_trust.BaselineStatus.INVALID_TYPE,
    )


def _validate_required_keys(
    obj: dict[str, object], required: set[str], *, path: Path
) -> None:
    missing = required - set(obj.keys())
    if missing:
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: missing required fields: "
            f"{', '.join(sorted(missing))}",
            status=_trust.BaselineStatus.MISSING_FIELDS,
        )


def _validate_exact_clone_keys(clones: dict[str, object], *, path: Path) -> None:
    keys = set(clones.keys())
    extra = keys - _CLONES_REQUIRED_KEYS
    if extra:
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: unexpected clone keys: "
            f"{', '.join(sorted(extra))}",
            status=_trust.BaselineStatus.INVALID_TYPE,
        )


def _is_legacy_baseline_payload(payload: dict[str, object]) -> bool:
    return "functions" in payload and "blocks" in payload


def _preserve_embedded_metrics(
    path: Path,
) -> tuple[
    dict[str, object] | None,
    str | None,
    dict[str, object] | None,
    str | None,
]:
    try:
        payload = _trust._load_json_object(path)
    except BaselineValidationError:
        return None, None, None, None
    metrics_obj = payload.get("metrics")
    api_surface_obj = payload.get("api_surface")
    preserved_api_surface = (
        dict(api_surface_obj) if isinstance(api_surface_obj, dict) else None
    )
    if not isinstance(metrics_obj, dict):
        return None, None, preserved_api_surface, None
    meta_obj = payload.get("meta")
    if not isinstance(meta_obj, dict):
        return dict(metrics_obj), None, preserved_api_surface, None
    metrics_hash = meta_obj.get("metrics_payload_sha256")
    api_surface_hash = meta_obj.get("api_surface_payload_sha256")
    normalized_api_surface_hash = (
        api_surface_hash if isinstance(api_surface_hash, str) else None
    )
    if not isinstance(metrics_hash, str):
        return (
            dict(metrics_obj),
            None,
            preserved_api_surface,
            normalized_api_surface_hash,
        )
    return (
        dict(metrics_obj),
        metrics_hash,
        preserved_api_surface,
        normalized_api_surface_hash,
    )


def _baseline_payload(
    *,
    functions: set[str],
    blocks: set[str],
    generator: str | None,
    schema_version: str | None,
    fingerprint_version: str | None,
    python_tag: str | None,
    generator_version: str | None,
    created_at: str | None,
) -> dict[str, object]:
    resolved_generator = generator or _trust.BASELINE_GENERATOR
    resolved_schema = schema_version or BASELINE_SCHEMA_VERSION
    resolved_fingerprint = fingerprint_version or BASELINE_FINGERPRINT_VERSION
    resolved_python_tag = python_tag or _trust.current_python_tag()
    resolved_generator_version = generator_version or __version__
    resolved_created_at = created_at or _trust._utc_now_z()

    sorted_functions = sorted(functions)
    sorted_blocks = sorted(blocks)
    payload_sha256 = _trust._compute_payload_sha256(
        functions=sorted_functions,
        blocks=sorted_blocks,
        fingerprint_version=resolved_fingerprint,
        python_tag=resolved_python_tag,
    )

    return {
        "meta": {
            "generator": {
                "name": resolved_generator,
                "version": resolved_generator_version,
            },
            "schema_version": resolved_schema,
            "fingerprint_version": resolved_fingerprint,
            "python_tag": resolved_python_tag,
            "created_at": resolved_created_at,
            "payload_sha256": payload_sha256,
        },
        "clones": {
            "functions": sorted_functions,
            "blocks": sorted_blocks,
        },
    }


__all__ = [
    "_BLOCK_ID_RE",
    "_FUNCTION_ID_RE",
    "Baseline",
    "_atomic_write_json",
    "_baseline_payload",
    "_preserve_embedded_metrics",
]
