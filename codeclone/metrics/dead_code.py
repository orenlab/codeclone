# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Literal

from ..models import DeadCandidate, DeadItem
from ..paths import is_test_filepath

_TEST_NAME_PREFIXES = ("test_", "pytest_")
_DYNAMIC_METHOD_PREFIXES = ("visit_",)
_MODULE_RUNTIME_HOOK_NAMES = {"__getattr__", "__dir__"}
_DYNAMIC_HOOK_NAMES = {
    "setup",
    "teardown",
    "setUp",
    "tearDown",
    "setUpClass",
    "tearDownClass",
    "setup_class",
    "teardown_class",
    "setup_method",
    "teardown_method",
}


def find_unused(
    *,
    definitions: tuple[DeadCandidate, ...],
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str] = frozenset(),
) -> tuple[DeadItem, ...]:
    items: list[DeadItem] = []
    for symbol in definitions:
        if _is_non_actionable_candidate(symbol):
            continue
        if symbol.qualname in referenced_qualnames:
            continue
        if symbol.local_name in referenced_names:
            continue

        confidence: Literal["high", "medium"] = "high"
        if symbol.qualname.split(":", 1)[-1] in referenced_names:
            confidence = "medium"

        items.append(
            DeadItem(
                qualname=symbol.qualname,
                filepath=symbol.filepath,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                kind=symbol.kind,
                confidence=confidence,
            )
        )

    items_sorted = tuple(
        sorted(
            items,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
                item.kind,
            ),
        )
    )
    return items_sorted


def _is_non_actionable_candidate(symbol: DeadCandidate) -> bool:
    # pytest entrypoints and fixtures are discovered by naming conventions.
    if symbol.local_name.startswith(_TEST_NAME_PREFIXES):
        return True
    if is_test_filepath(symbol.filepath):
        return True

    # Module-level dynamic hooks (PEP 562) are invoked by import/runtime lookup.
    if symbol.kind == "function" and symbol.local_name in _MODULE_RUNTIME_HOOK_NAMES:
        return True

    # Magic methods and visitor callbacks are invoked by runtime dispatch.
    if symbol.kind == "method":
        if _is_dunder(symbol.local_name):
            return True
        if symbol.local_name.startswith(_DYNAMIC_METHOD_PREFIXES):
            return True
        if symbol.local_name in _DYNAMIC_HOOK_NAMES:
            return True
    return False


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")
