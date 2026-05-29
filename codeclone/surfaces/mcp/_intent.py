# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final

DEFAULT_FORBIDDEN: Final[tuple[str, ...]] = (
    "codeclone.baseline.json",
    ".cache/codeclone/**",
)
DEFAULT_INTENT_GUARDS: Final[tuple[str, ...]] = (
    "scope_expansion_requires_explanation",
    "baseline_update_forbidden",
    "cache_update_forbidden",
    "generated_report_update_forbidden",
    "out_of_scope_production_change_requires_human",
    "new_structural_regression_forbidden",
    "report_only_claims_forbidden",
    "concurrent_workspace_intent_conflict_requires_review",
)


class IntentStatus(str, Enum):
    ACTIVE = "active"
    QUEUED = "queued"
    CLEAN = "clean"
    EXPANDED = "expanded"
    VIOLATED = "violated"
    UNVERIFIED = "unverified"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class IntentScope:
    allowed_files: tuple[str, ...]
    allowed_related: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = DEFAULT_FORBIDDEN

    @property
    def allowed_paths(self) -> tuple[str, ...]:
        return tuple(sorted({*self.allowed_files, *self.allowed_related}))

    def to_payload(self) -> dict[str, object]:
        return {
            "allowed_files": list(self.allowed_files),
            "allowed_related": list(self.allowed_related),
            "forbidden": list(self.forbidden),
        }


@dataclass(frozen=True, slots=True)
class IntentCheckResult:
    status: IntentStatus
    declared_scope: tuple[str, ...]
    actual_changed_files: tuple[str, ...]
    unexpected_files: tuple[str, ...]
    forbidden_touched: tuple[str, ...]
    required_action: str | None
    message: str

    def to_payload(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "declared_scope": list(self.declared_scope),
            "actual_changed_files": list(self.actual_changed_files),
            "unexpected_files": list(self.unexpected_files),
            "forbidden_touched": list(self.forbidden_touched),
            "required_action": self.required_action,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class IntentRecord:
    intent_id: str
    run_id: str
    report_digest: str
    status: IntentStatus
    declared_at_utc: str
    scope: IntentScope
    intent_description: str
    expected_effects: tuple[str, ...]
    guards: tuple[str, ...]
    blast_radius_summary: dict[str, object] | None = None
    check_result: IntentCheckResult | None = None

    def to_payload(self, *, short_run_id: str | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "intent_id": self.intent_id,
            "run_id": short_run_id or self.run_id,
            "status": self.status.value,
            "scope": self.scope.to_payload(),
            "intent": self.intent_description,
            "expected_effects": list(self.expected_effects),
            "guards": list(self.guards),
            "declared_at_utc": self.declared_at_utc,
            "report_digest": self.report_digest,
            "blast_radius_summary": self.blast_radius_summary or {},
        }
        if self.check_result is not None:
            payload["check_result"] = self.check_result.to_payload()
        return payload


def _normalize_path(value: object) -> str:
    text = str(value).replace("\\", "/").strip()
    if text == ".":
        return ""
    if text.startswith("./"):
        text = text[2:]
    text = text.rstrip("/")
    if Path(text).is_absolute():
        raise ValueError(f"intent paths must be relative: {value!r}")
    if ".." in Path(text).parts:
        raise ValueError(f"path traversal not allowed: {value!r}")
    return text


def _normalize_required_paths(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"scope.{field_name} must be a list of relative paths.")
    paths = tuple(
        sorted({_normalize_path(item) for item in value if str(item).strip()})
    )
    if not paths:
        raise ValueError(f"scope.{field_name} must contain at least one path.")
    return paths


def _normalize_optional_paths(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"scope.{field_name} must be a list of relative paths.")
    return tuple(sorted({_normalize_path(item) for item in value if str(item).strip()}))


def normalize_intent_scope(scope: object) -> IntentScope:
    if not isinstance(scope, Mapping):
        raise ValueError(
            'scope must be an object, e.g. {"allowed_files": ["path/to/file.py"]}.'
        )
    allowed_files = _normalize_required_paths(
        scope.get("allowed_files"),
        field_name="allowed_files",
    )
    allowed_related = _normalize_optional_paths(
        scope.get("allowed_related"),
        field_name="allowed_related",
    )
    raw_forbidden = scope.get("forbidden")
    forbidden = (
        (
            *DEFAULT_FORBIDDEN,
            *_normalize_optional_paths(raw_forbidden, field_name="forbidden"),
        )
        if raw_forbidden is not None
        else DEFAULT_FORBIDDEN
    )
    return IntentScope(
        allowed_files=allowed_files,
        allowed_related=allowed_related,
        forbidden=tuple(sorted(set(forbidden))),
    )


def normalize_expected_effects(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("expected_effects must be a list of strings.")
    return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))


def forbidden_touched(
    *,
    changed_files: Sequence[str],
    forbidden_patterns: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                path
                for path in changed_files
                if any(fnmatchcase(path, pattern) for pattern in forbidden_patterns)
            }
        )
    )
