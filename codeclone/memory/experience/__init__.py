# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Experience Layer: deterministic distillation of structural regularities
from the trajectory corpus (advisory, machine-owned, human-promotable)."""

from __future__ import annotations

from .distiller import (
    EXPERIENCE_MIN_SUPPORT,
    MIN_INFORMATION_VALUE,
    distill_experiences,
    information_value,
    pattern_keys,
)
from .models import (
    EXPERIENCE_DISTILLATION_VERSION,
    Experience,
    ExperienceEvidence,
    ExperienceFacet,
    ExperienceFacetKind,
    ExperienceStatus,
    PatternKey,
)
from .store import (
    count_experiences,
    list_experiences,
    list_experiences_for_subject_family,
    replace_experiences,
)

__all__ = [
    "EXPERIENCE_DISTILLATION_VERSION",
    "EXPERIENCE_MIN_SUPPORT",
    "MIN_INFORMATION_VALUE",
    "Experience",
    "ExperienceEvidence",
    "ExperienceFacet",
    "ExperienceFacetKind",
    "ExperienceStatus",
    "PatternKey",
    "count_experiences",
    "distill_experiences",
    "information_value",
    "list_experiences",
    "list_experiences_for_subject_family",
    "pattern_keys",
    "replace_experiences",
]
