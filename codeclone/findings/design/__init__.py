# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Report-only structural design signals.

Design signals are advisory review context. They never affect gates, health,
baseline, fingerprints, patch verification acceptance, ``edit_allowed``,
blast-radius permissions, or Engineering Memory truth.
"""

from __future__ import annotations

from .instance_methods import (
    DesignFindingGroup,
    DesignFindingSignature,
    InstanceIndependentMethodOccurrence,
    collect_instance_independent_methods,
    group_instance_independent_methods,
)

__all__ = [
    "DesignFindingGroup",
    "DesignFindingSignature",
    "InstanceIndependentMethodOccurrence",
    "collect_instance_independent_methods",
    "group_instance_independent_methods",
]
