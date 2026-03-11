# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Set
from pathlib import Path

from .errors import BaselineValidationError

__all__ = ["validate_top_level_structure"]


def validate_top_level_structure(
    payload: Mapping[str, object],
    *,
    path: Path,
    required_keys: Set[str],
    allowed_keys: Set[str],
    schema_label: str,
    missing_status: str,
    extra_status: str,
) -> None:
    keys = set(payload.keys())
    missing = required_keys - keys
    if missing:
        raise BaselineValidationError(
            f"Invalid {schema_label} schema at {path}: missing top-level keys: "
            f"{', '.join(sorted(missing))}",
            status=missing_status,
        )
    extra = keys - allowed_keys
    if extra:
        raise BaselineValidationError(
            f"Invalid {schema_label} schema at {path}: unexpected top-level keys: "
            f"{', '.join(sorted(extra))}",
            status=extra_status,
        )
