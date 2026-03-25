# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..domain.source_scope import (
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_MIXED,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)

SOURCE_KIND_FILTER_VALUES: tuple[str, ...] = (
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_MIXED,
)

_SOURCE_KIND_LABELS: dict[str, str] = {
    SOURCE_KIND_PRODUCTION: "Production",
    SOURCE_KIND_TESTS: "Tests",
    SOURCE_KIND_FIXTURES: "Fixtures",
    SOURCE_KIND_MIXED: "Mixed",
    SOURCE_KIND_OTHER: "Other",
}

__all__ = [
    "SOURCE_KIND_FILTER_VALUES",
    "normalize_source_kind",
    "source_kind_label",
]


def normalize_source_kind(source_kind: str) -> str:
    return source_kind.strip().lower() or SOURCE_KIND_OTHER


def source_kind_label(source_kind: str) -> str:
    normalized = normalize_source_kind(source_kind)
    return _SOURCE_KIND_LABELS.get(
        normalized,
        normalized.title() or _SOURCE_KIND_LABELS[SOURCE_KIND_OTHER],
    )
