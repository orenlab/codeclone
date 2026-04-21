# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime, timezone
from enum import Enum
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING, Final

import orjson

from ..contracts.errors import BaselineValidationError
from ..utils.json_io import read_json_object as _read_json_object

if TYPE_CHECKING:
    from collections.abc import Collection

BASELINE_GENERATOR = "codeclone"
_BASELINE_SCHEMA_MAX_MINOR_BY_MAJOR = {1: 0, 2: 1}
MAX_BASELINE_SIZE_BYTES = 5 * 1024 * 1024
_UTC_ISO8601_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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


def _safe_stat_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as e:
        raise BaselineValidationError(
            f"Cannot stat baseline file at {path}: {e}",
            status=BaselineStatus.INVALID_TYPE,
        ) from e


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        return _read_json_object(path)
    except OSError as e:
        raise BaselineValidationError(
            f"Cannot read baseline file at {path}: {e}",
            status=BaselineStatus.INVALID_JSON,
        ) from e
    except JSONDecodeError as e:
        raise BaselineValidationError(
            f"Corrupted baseline file at {path}: {e}",
            status=BaselineStatus.INVALID_JSON,
        ) from e
    except TypeError:
        raise BaselineValidationError(
            f"Baseline payload must be an object at {path}",
            status=BaselineStatus.INVALID_TYPE,
        ) from None


def _parse_generator_meta(
    meta_obj: dict[str, object], *, path: Path
) -> tuple[str, str | None]:
    raw_generator = meta_obj.get("generator")

    if isinstance(raw_generator, str):
        generator_version = _optional_str(meta_obj, "generator_version", path=path)
        if generator_version is None:
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


def _compute_payload_sha256(
    *,
    functions: Collection[str],
    blocks: Collection[str],
    fingerprint_version: str,
    python_tag: str,
) -> str:
    canonical = {
        "blocks": sorted(blocks),
        "fingerprint_version": fingerprint_version,
        "functions": sorted(functions),
        "python_tag": python_tag,
    }
    serialized = orjson.dumps(canonical, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(serialized).hexdigest()


def current_python_tag() -> str:
    """Return the interpreter compatibility tag as an immutable string."""
    impl = sys.implementation.name
    major, minor = sys.version_info[:2]
    prefix = "cp" if impl == "cpython" else impl[:2]
    return f"{prefix}{major}{minor}"


def _utc_now_z() -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _require_str(obj: dict[str, object], key: str, *, path: Path) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be string",
            status=BaselineStatus.INVALID_TYPE,
        )
    return value


def _optional_str(obj: dict[str, object], key: str, *, path: Path) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be string",
            status=BaselineStatus.INVALID_TYPE,
        )
    return value


def _require_semver_str(obj: dict[str, object], key: str, *, path: Path) -> str:
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


def _require_python_tag(obj: dict[str, object], key: str, *, path: Path) -> str:
    value = _require_str(obj, key, path=path)
    if not re.fullmatch(r"[a-z]{2}\d{2,3}", value):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must look like 'cp313'",
            status=BaselineStatus.INVALID_TYPE,
        )
    return value


def _require_utc_iso8601_z(obj: dict[str, object], key: str, *, path: Path) -> str:
    value = _require_str(obj, key, path=path)
    if not _UTC_ISO8601_Z_RE.fullmatch(value):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be UTC ISO-8601 with Z",
            status=BaselineStatus.INVALID_TYPE,
        )
    try:
        datetime(
            int(value[0:4]),
            int(value[5:7]),
            int(value[8:10]),
            int(value[11:13]),
            int(value[14:16]),
            int(value[17:19]),
            tzinfo=timezone.utc,
        )
    except ValueError as e:
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be UTC ISO-8601 with Z",
            status=BaselineStatus.INVALID_TYPE,
        ) from e
    return value


def _require_sorted_unique_ids(
    obj: dict[str, object], key: str, *, pattern: re.Pattern[str], path: Path
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


__all__ = [
    "BASELINE_GENERATOR",
    "BASELINE_UNTRUSTED_STATUSES",
    "MAX_BASELINE_SIZE_BYTES",
    "_BASELINE_SCHEMA_MAX_MINOR_BY_MAJOR",
    "BaselineStatus",
    "_compute_payload_sha256",
    "_load_json_object",
    "_optional_str",
    "_parse_generator_meta",
    "_parse_semver",
    "_require_python_tag",
    "_require_semver_str",
    "_require_sorted_unique_ids",
    "_require_str",
    "_require_utc_iso8601_z",
    "_safe_stat_size",
    "_utc_now_z",
    "coerce_baseline_status",
    "current_python_tag",
]
