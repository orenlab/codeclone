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
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .errors import BaselineValidationError

BASELINE_SCHEMA_VERSION = 1
MAX_BASELINE_SIZE_BYTES = 5 * 1024 * 1024
BASELINE_GENERATOR = "codeclone"


class Baseline:
    __slots__ = (
        "baseline_version",
        "blocks",
        "created_at",
        "functions",
        "generator",
        "path",
        "payload_sha256",
        "python_version",
        "schema_version",
    )

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.functions: set[str] = set()
        self.blocks: set[str] = set()
        self.python_version: str | None = None
        self.baseline_version: str | None = None
        self.schema_version: int | None = None
        self.generator: str | None = None
        self.payload_sha256: str | None = None
        self.created_at: str | None = None

    def load(self, *, max_size_bytes: int | None = None) -> None:
        if not self.path.exists():
            return
        size_limit = (
            MAX_BASELINE_SIZE_BYTES if max_size_bytes is None else max_size_bytes
        )

        try:
            size = self.path.stat().st_size
        except OSError as e:
            raise BaselineValidationError(
                f"Cannot stat baseline file at {self.path}: {e}"
            ) from e
        if size > size_limit:
            raise BaselineValidationError(
                "Baseline file is too large "
                f"({size} bytes, max {size_limit} bytes) at {self.path}",
                status="too_large",
            )

        try:
            data = json.loads(self.path.read_text("utf-8"))
        except json.JSONDecodeError as e:
            raise BaselineValidationError(
                f"Corrupted baseline file at {self.path}: {e}"
            ) from e

        if not isinstance(data, dict):
            raise BaselineValidationError(
                f"Baseline payload must be an object at {self.path}"
            )

        functions = _require_str_list(data, "functions", path=self.path)
        blocks = _require_str_list(data, "blocks", path=self.path)
        python_version = _optional_str(data, "python_version", path=self.path)
        baseline_version = _optional_str(data, "baseline_version", path=self.path)
        schema_version = _optional_int(data, "schema_version", path=self.path)
        generator = _optional_str_loose(data, "generator")
        payload_sha256 = _optional_str_loose(data, "payload_sha256")
        created_at = _optional_str(data, "created_at", path=self.path)

        self.functions = set(functions)
        self.blocks = set(blocks)
        self.python_version = python_version
        self.baseline_version = baseline_version
        self.schema_version = schema_version
        self.generator = generator
        self.payload_sha256 = payload_sha256
        self.created_at = created_at

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.path.write_text(
            json.dumps(
                _baseline_payload(
                    self.functions,
                    self.blocks,
                    self.python_version,
                    self.baseline_version,
                    self.schema_version,
                    self.generator,
                    now_utc,
                ),
                indent=2,
                ensure_ascii=False,
            ),
            "utf-8",
        )

    def is_legacy_format(self) -> bool:
        return self.baseline_version is None or self.schema_version is None

    def verify_integrity(self) -> None:
        if self.is_legacy_format():
            return
        if self.generator != BASELINE_GENERATOR:
            raise BaselineValidationError(
                "Baseline generator mismatch: expected 'codeclone'.",
                status="generator_mismatch",
            )
        if not isinstance(self.payload_sha256, str):
            raise BaselineValidationError(
                "Baseline integrity payload hash is missing.",
                status="integrity_missing",
            )
        expected = _compute_payload_sha256(self.functions, self.blocks)
        if not hmac.compare_digest(self.payload_sha256, expected):
            raise BaselineValidationError(
                "Baseline integrity check failed: payload_sha256 mismatch.",
                status="integrity_failed",
            )

    @staticmethod
    def from_groups(
        func_groups: Mapping[str, object],
        block_groups: Mapping[str, object],
        path: str | Path = "",
        python_version: str | None = None,
        baseline_version: str | None = None,
        schema_version: int | None = None,
    ) -> Baseline:
        bl = Baseline(path)
        bl.functions = set(func_groups.keys())
        bl.blocks = set(block_groups.keys())
        bl.python_version = python_version
        bl.baseline_version = baseline_version
        bl.schema_version = schema_version
        bl.generator = BASELINE_GENERATOR
        return bl

    def diff(
        self, func_groups: Mapping[str, object], block_groups: Mapping[str, object]
    ) -> tuple[set[str], set[str]]:
        new_funcs = set(func_groups.keys()) - self.functions
        new_blocks = set(block_groups.keys()) - self.blocks
        return new_funcs, new_blocks


def _baseline_payload(
    functions: set[str],
    blocks: set[str],
    python_version: str | None,
    baseline_version: str | None,
    schema_version: int | None,
    generator: str | None,
    created_at: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = _canonical_payload(functions, blocks)
    if python_version:
        payload["python_version"] = python_version
    payload["baseline_version"] = baseline_version or __version__
    payload["schema_version"] = (
        schema_version if schema_version is not None else BASELINE_SCHEMA_VERSION
    )
    payload["generator"] = generator or BASELINE_GENERATOR
    payload["payload_sha256"] = _compute_payload_sha256(functions, blocks)
    if created_at:
        payload["created_at"] = created_at
    return payload


def _canonical_payload(functions: set[str], blocks: set[str]) -> dict[str, list[str]]:
    return {
        "functions": sorted(functions),
        "blocks": sorted(blocks),
    }


def _compute_payload_sha256(functions: set[str], blocks: set[str]) -> str:
    serialized = json.dumps(
        _canonical_payload(functions, blocks),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _require_str_list(data: dict[str, Any], key: str, *, path: Path) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be list[str]"
        )
    return value


def _optional_str(data: dict[str, Any], key: str, *, path: Path) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be string"
        )
    return value


def _optional_int(data: dict[str, Any], key: str, *, path: Path) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: '{key}' must be integer"
        )
    return value


def _optional_str_loose(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str):
        return value
    return None
