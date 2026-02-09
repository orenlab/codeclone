"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Final

from . import __version__
from .contracts import (
    BASELINE_FINGERPRINT_VERSION,
    BASELINE_SCHEMA_VERSION,
)
from .errors import BaselineValidationError

# Any: baseline JSON parsing/serialization boundary. Values are validated
# and narrowed before entering compatibility/integrity checks.

BASELINE_GENERATOR = "codeclone"
BASELINE_SCHEMA_MAJOR = 1
BASELINE_SCHEMA_MAX_MINOR = 0
MAX_BASELINE_SIZE_BYTES = 5 * 1024 * 1024


class BaselineStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    TOO_LARGE = "too_large"
    INVALID_JSON = "invalid_json"
    INVALID_TYPE = "invalid_type"
    MISSING_FIELDS = "missing_fields"
    MISMATCH_SCHEMA_VERSION = "mismatch_schema_version"
    MISMATCH_FINGERPRINT_VERSION = "mismatch_fingerprint_version"
    MISMATCH_PYTHON_VERSION = "mismatch_python_version"
    GENERATOR_MISMATCH = "generator_mismatch"
    INTEGRITY_MISSING = "integrity_missing"
    INTEGRITY_FAILED = "integrity_failed"


BASELINE_UNTRUSTED_STATUSES: Final[frozenset[BaselineStatus]] = frozenset(
    {
        BaselineStatus.MISSING,
        BaselineStatus.TOO_LARGE,
        BaselineStatus.INVALID_JSON,
        BaselineStatus.INVALID_TYPE,
        BaselineStatus.MISSING_FIELDS,
        BaselineStatus.MISMATCH_SCHEMA_VERSION,
        BaselineStatus.MISMATCH_FINGERPRINT_VERSION,
        BaselineStatus.MISMATCH_PYTHON_VERSION,
        BaselineStatus.GENERATOR_MISMATCH,
        BaselineStatus.INTEGRITY_MISSING,
        BaselineStatus.INTEGRITY_FAILED,
    }
)


def coerce_baseline_status(
    raw_status: str | BaselineStatus | None,
) -> BaselineStatus:
    if isinstance(raw_status, BaselineStatus):
        return raw_status
    if isinstance(raw_status, str):
        try:
            return BaselineStatus(raw_status)
        except ValueError:
            return BaselineStatus.INVALID_TYPE
    return BaselineStatus.INVALID_TYPE


_TOP_LEVEL_KEYS = {"meta", "clones"}
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

    def load(self, *, max_size_bytes: int | None = None) -> None:
        try:
            exists = self.path.exists()
        except OSError as e:
            raise BaselineValidationError(
                f"Cannot stat baseline file at {self.path}: {e}",
                status=BaselineStatus.INVALID_TYPE,
            ) from e
        if not exists:
            return

        size_limit = (
            MAX_BASELINE_SIZE_BYTES if max_size_bytes is None else max_size_bytes
        )
        size = _safe_stat_size(self.path)
        if size > size_limit:
            raise BaselineValidationError(
                "Baseline file is too large "
                f"({size} bytes, max {size_limit} bytes) at {self.path}. "
                "Increase --max-baseline-size-mb or regenerate baseline.",
                status=BaselineStatus.TOO_LARGE,
            )

        payload = _load_json_object(self.path)
        if _is_legacy_baseline_payload(payload):
            raise BaselineValidationError(
                "Baseline format is legacy (<=1.3.x) and must be regenerated. "
                "Please run --update-baseline.",
                status=BaselineStatus.MISSING_FIELDS,
            )

        _validate_top_level_structure(payload, path=self.path)

        meta_obj = payload.get("meta")
        clones_obj = payload.get("clones")
        if not isinstance(meta_obj, dict):
            raise BaselineValidationError(
                f"Invalid baseline schema at {self.path}: 'meta' must be object",
                status=BaselineStatus.INVALID_TYPE,
            )
        if not isinstance(clones_obj, dict):
            raise BaselineValidationError(
                f"Invalid baseline schema at {self.path}: 'clones' must be object",
                status=BaselineStatus.INVALID_TYPE,
            )

        _validate_required_keys(meta_obj, _META_REQUIRED_KEYS, path=self.path)
        _validate_required_keys(clones_obj, _CLONES_REQUIRED_KEYS, path=self.path)
        _validate_exact_clone_keys(clones_obj, path=self.path)

        generator, generator_version = _parse_generator_meta(meta_obj, path=self.path)
        schema_version = _require_semver_str(meta_obj, "schema_version", path=self.path)
        fingerprint_version = _require_str(
            meta_obj, "fingerprint_version", path=self.path
        )
        python_tag = _require_python_tag(meta_obj, "python_tag", path=self.path)
        created_at = _require_utc_iso8601_z(meta_obj, "created_at", path=self.path)
        payload_sha256 = _require_str(meta_obj, "payload_sha256", path=self.path)

        function_ids = _require_sorted_unique_ids(
            clones_obj,
            "functions",
            pattern=_FUNCTION_ID_RE,
            path=self.path,
        )
        block_ids = _require_sorted_unique_ids(
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
        _atomic_write_json(self.path, payload)

    def verify_compatibility(self, *, current_python_tag: str) -> None:
        if self.generator != BASELINE_GENERATOR:
            raise BaselineValidationError(
                "Baseline generator mismatch: expected 'codeclone'.",
                status=BaselineStatus.GENERATOR_MISMATCH,
            )
        if self.schema_version is None:
            raise BaselineValidationError(
                "Baseline schema version is missing.",
                status=BaselineStatus.MISSING_FIELDS,
            )
        if self.fingerprint_version is None:
            raise BaselineValidationError(
                "Baseline fingerprint version is missing.",
                status=BaselineStatus.MISSING_FIELDS,
            )
        if self.python_tag is None:
            raise BaselineValidationError(
                "Baseline python_tag is missing.",
                status=BaselineStatus.MISSING_FIELDS,
            )

        schema_major, schema_minor, _ = _parse_semver(
            self.schema_version, key="schema_version", path=self.path
        )
        if schema_major != BASELINE_SCHEMA_MAJOR:
            raise BaselineValidationError(
                "Baseline schema version mismatch: "
                f"baseline={self.schema_version}, "
                f"supported_major={BASELINE_SCHEMA_MAJOR}.",
                status=BaselineStatus.MISMATCH_SCHEMA_VERSION,
            )
        if schema_minor > BASELINE_SCHEMA_MAX_MINOR:
            raise BaselineValidationError(
                "Baseline schema version is newer than supported: "
                f"baseline={self.schema_version}, "
                f"max=1.{BASELINE_SCHEMA_MAX_MINOR}.",
                status=BaselineStatus.MISMATCH_SCHEMA_VERSION,
            )
        if self.fingerprint_version != BASELINE_FINGERPRINT_VERSION:
            raise BaselineValidationError(
                "Baseline fingerprint version mismatch: "
                f"baseline={self.fingerprint_version}, "
                f"expected={BASELINE_FINGERPRINT_VERSION}.",
                status=BaselineStatus.MISMATCH_FINGERPRINT_VERSION,
            )
        if self.python_tag != current_python_tag:
            raise BaselineValidationError(
                "Baseline python tag mismatch: "
                f"baseline={self.python_tag}, current={current_python_tag}.",
                status=BaselineStatus.MISMATCH_PYTHON_VERSION,
            )
        self.verify_integrity()

    def verify_integrity(self) -> None:
        if not isinstance(self.payload_sha256, str):
            raise BaselineValidationError(
                "Baseline integrity payload hash is missing.",
                status=BaselineStatus.INTEGRITY_MISSING,
            )
        if len(self.payload_sha256) != 64:
            raise BaselineValidationError(
                "Baseline integrity payload hash is missing.",
                status=BaselineStatus.INTEGRITY_MISSING,
            )
        try:
            int(self.payload_sha256, 16)
        except ValueError as e:
            raise BaselineValidationError(
                "Baseline integrity payload hash is missing.",
                status=BaselineStatus.INTEGRITY_MISSING,
            ) from e
        if self.schema_version is None:
            raise BaselineValidationError(
                "Baseline schema version is missing for integrity validation.",
                status=BaselineStatus.MISSING_FIELDS,
            )
        if self.fingerprint_version is None:
            raise BaselineValidationError(
                "Baseline fingerprint version is missing for integrity validation.",
                status=BaselineStatus.MISSING_FIELDS,
            )
        if self.python_tag is None:
            raise BaselineValidationError(
                "Baseline python_tag is missing for integrity validation.",
                status=BaselineStatus.MISSING_FIELDS,
            )
        expected = _compute_payload_sha256(
            functions=self.functions,
            blocks=self.blocks,
            schema_version=self.schema_version,
            fingerprint_version=self.fingerprint_version,
            python_tag=self.python_tag,
        )
        if not hmac.compare_digest(self.payload_sha256, expected):
            raise BaselineValidationError(
                "Baseline integrity check failed: payload_sha256 mismatch.",
                status=BaselineStatus.INTEGRITY_FAILED,
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
        baseline.generator = BASELINE_GENERATOR
        baseline.schema_version = schema_version or BASELINE_SCHEMA_VERSION
        baseline.fingerprint_version = (
            fingerprint_version or BASELINE_FINGERPRINT_VERSION
        )
        baseline.python_tag = python_tag or _current_python_tag()
        baseline.generator_version = generator_version or __version__
        return baseline

    def diff(
        self, func_groups: Mapping[str, object], block_groups: Mapping[str, object]
    ) -> tuple[set[str], set[str]]:
        new_funcs = set(func_groups.keys()) - self.functions
        new_blocks = set(block_groups.keys()) - self.blocks
        return new_funcs, new_blocks


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with tmp_path.open("wb") as tmp_file:
        tmp_file.write(data.encode("utf-8"))
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
    os.replace(tmp_path, path)


def _safe_stat_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as e:
        raise BaselineValidationError(
            f"Cannot stat baseline file at {path}: {e}",
            status=BaselineStatus.INVALID_TYPE,
        ) from e


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text("utf-8")
    except OSError as e:
        raise BaselineValidationError(
            f"Cannot read baseline file at {path}: {e}",
            status=BaselineStatus.INVALID_JSON,
        ) from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BaselineValidationError(
            f"Corrupted baseline file at {path}: {e}",
            status=BaselineStatus.INVALID_JSON,
        ) from e
    if not isinstance(data, dict):
        raise BaselineValidationError(
            f"Baseline payload must be an object at {path}",
            status=BaselineStatus.INVALID_TYPE,
        )
    return data


def _validate_top_level_structure(payload: dict[str, Any], *, path: Path) -> None:
    keys = set(payload.keys())
    missing = _TOP_LEVEL_KEYS - keys
    extra = keys - _TOP_LEVEL_KEYS
    if missing:
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: missing top-level keys: "
            f"{', '.join(sorted(missing))}",
            status=BaselineStatus.MISSING_FIELDS,
        )
    if extra:
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: unexpected top-level keys: "
            f"{', '.join(sorted(extra))}",
            status=BaselineStatus.INVALID_TYPE,
        )


def _validate_required_keys(
    obj: dict[str, Any], required: set[str], *, path: Path
) -> None:
    missing = required - set(obj.keys())
    if missing:
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: missing required fields: "
            f"{', '.join(sorted(missing))}",
            status=BaselineStatus.MISSING_FIELDS,
        )


def _validate_exact_clone_keys(clones: dict[str, Any], *, path: Path) -> None:
    keys = set(clones.keys())
    extra = keys - _CLONES_REQUIRED_KEYS
    if extra:
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: unexpected clone keys: "
            f"{', '.join(sorted(extra))}",
            status=BaselineStatus.INVALID_TYPE,
        )


def _is_legacy_baseline_payload(payload: dict[str, Any]) -> bool:
    return "functions" in payload and "blocks" in payload


def _parse_generator_meta(
    meta_obj: dict[str, Any], *, path: Path
) -> tuple[str, str | None]:
    raw_generator = meta_obj.get("generator")

    if isinstance(raw_generator, str):
        generator_version = _optional_str(meta_obj, "generator_version", path=path)
        if generator_version is None:
            # Legacy alias for baselines produced before generator_version rename.
            generator_version = _optional_str(meta_obj, "codeclone_version", path=path)
        return raw_generator, generator_version

    if isinstance(raw_generator, dict):
        allowed_keys = {"name", "version"}
        extra = set(raw_generator.keys()) - allowed_keys
        if extra:
            raise BaselineValidationError(
                f"Invalid baseline schema at {path}: unexpected generator keys: "
                f"{', '.join(sorted(extra))}",
                status=BaselineStatus.INVALID_TYPE,
            )
        generator_name = _require_str(raw_generator, "name", path=path)
        generator_version = _optional_str(raw_generator, "version", path=path)

        if generator_version is None:
            generator_version = _optional_str(meta_obj, "generator_version", path=path)
            if generator_version is None:
                generator_version = _optional_str(
                    meta_obj, "codeclone_version", path=path
                )

        return generator_name, generator_version

    raise BaselineValidationError(
        f"Invalid baseline schema at {path}: 'generator' must be string or object",
        status=BaselineStatus.INVALID_TYPE,
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
) -> dict[str, Any]:
    resolved_generator = generator or BASELINE_GENERATOR
    resolved_schema = schema_version or BASELINE_SCHEMA_VERSION
    resolved_fingerprint = fingerprint_version or BASELINE_FINGERPRINT_VERSION
    resolved_python_tag = python_tag or _current_python_tag()
    resolved_generator_version = generator_version or __version__
    resolved_created_at = created_at or _utc_now_z()

    sorted_functions = sorted(functions)
    sorted_blocks = sorted(blocks)
    payload_sha256 = _compute_payload_sha256(
        functions=set(sorted_functions),
        blocks=set(sorted_blocks),
        schema_version=resolved_schema,
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


def _compute_payload_sha256(
    *,
    functions: set[str],
    blocks: set[str],
    schema_version: str,
    fingerprint_version: str,
    python_tag: str,
) -> str:
    canonical = {
        "blocks": sorted(blocks),
        "fingerprint_version": fingerprint_version,
        "functions": sorted(functions),
        "python_tag": python_tag,
        "schema_version": schema_version,
    }
    serialized = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _current_python_tag() -> str:
    impl = sys.implementation.name
    major, minor = sys.version_info[:2]
    prefix = "cp" if impl == "cpython" else impl[:2]
    return f"{prefix}{major}{minor}"


def _utc_now_z() -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _require_str(obj: dict[str, Any], key: str, *, path: Path) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be string",
            status=BaselineStatus.INVALID_TYPE,
        )
    return value


def _optional_str(obj: dict[str, Any], key: str, *, path: Path) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be string",
            status=BaselineStatus.INVALID_TYPE,
        )
    return value


def _require_semver_str(obj: dict[str, Any], key: str, *, path: Path) -> str:
    value = _require_str(obj, key, path=path)
    _parse_semver(value, key=key, path=path)
    return value


def _parse_semver(value: str, *, key: str, path: Path) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) not in {2, 3} or not all(part.isdigit() for part in parts):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be semver string",
            status=BaselineStatus.INVALID_TYPE,
        )
    if len(parts) == 2:
        major, minor = int(parts[0]), int(parts[1])
        patch = 0
    else:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    return major, minor, patch


def _require_python_tag(obj: dict[str, Any], key: str, *, path: Path) -> str:
    value = _require_str(obj, key, path=path)
    if not re.fullmatch(r"[a-z]{2}\d{2,3}", value):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must look like 'cp313'",
            status=BaselineStatus.INVALID_TYPE,
        )
    return value


def _require_utc_iso8601_z(obj: dict[str, Any], key: str, *, path: Path) -> str:
    value = _require_str(obj, key, path=path)
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be UTC ISO-8601 with Z",
            status=BaselineStatus.INVALID_TYPE,
        ) from e
    return value


def _require_sorted_unique_ids(
    obj: dict[str, Any], key: str, *, pattern: re.Pattern[str], path: Path
) -> list[str]:
    value = obj.get(key)
    if not isinstance(value, list):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be list[str]",
            status=BaselineStatus.INVALID_TYPE,
        )
    if not all(isinstance(item, str) for item in value):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be list[str]",
            status=BaselineStatus.INVALID_TYPE,
        )
    values = list(value)
    if values != sorted(values) or len(values) != len(set(values)):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be sorted and unique",
            status=BaselineStatus.INVALID_TYPE,
        )
    if not all(pattern.fullmatch(item) for item in values):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' has invalid id format",
            status=BaselineStatus.INVALID_TYPE,
        )
    return values
