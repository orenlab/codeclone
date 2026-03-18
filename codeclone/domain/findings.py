# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Final

CLONE_KIND_FUNCTION: Final = "function"
CLONE_KIND_BLOCK: Final = "block"
CLONE_KIND_SEGMENT: Final = "segment"

CLONE_NOVELTY_NEW: Final = "new"
CLONE_NOVELTY_KNOWN: Final = "known"

FAMILY_CLONE: Final = "clone"
FAMILY_CLONES: Final = "clones"
FAMILY_STRUCTURAL: Final = "structural"
FAMILY_DEAD_CODE: Final = "dead_code"
FAMILY_DESIGN: Final = "design"
FAMILY_METRICS: Final = "metrics"

CATEGORY_CLONE: Final = "clone"
CATEGORY_STRUCTURAL: Final = "structural"
CATEGORY_COMPLEXITY: Final = "complexity"
CATEGORY_COUPLING: Final = "coupling"
CATEGORY_COHESION: Final = "cohesion"
CATEGORY_DEAD_CODE: Final = "dead_code"
CATEGORY_DEPENDENCY: Final = "dependency"

__all__ = [
    "CATEGORY_CLONE",
    "CATEGORY_COHESION",
    "CATEGORY_COMPLEXITY",
    "CATEGORY_COUPLING",
    "CATEGORY_DEAD_CODE",
    "CATEGORY_DEPENDENCY",
    "CATEGORY_STRUCTURAL",
    "CLONE_KIND_BLOCK",
    "CLONE_KIND_FUNCTION",
    "CLONE_KIND_SEGMENT",
    "CLONE_NOVELTY_KNOWN",
    "CLONE_NOVELTY_NEW",
    "FAMILY_CLONE",
    "FAMILY_CLONES",
    "FAMILY_DEAD_CODE",
    "FAMILY_DESIGN",
    "FAMILY_METRICS",
    "FAMILY_STRUCTURAL",
]
