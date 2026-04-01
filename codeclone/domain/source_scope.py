# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Final

SOURCE_KIND_PRODUCTION: Final = "production"
SOURCE_KIND_TESTS: Final = "tests"
SOURCE_KIND_FIXTURES: Final = "fixtures"
SOURCE_KIND_MIXED: Final = "mixed"
SOURCE_KIND_OTHER: Final = "other"

SOURCE_KIND_ORDER: Final[dict[str, int]] = {
    SOURCE_KIND_PRODUCTION: 0,
    SOURCE_KIND_TESTS: 1,
    SOURCE_KIND_FIXTURES: 2,
    SOURCE_KIND_MIXED: 3,
    SOURCE_KIND_OTHER: 4,
}

SOURCE_KIND_BREAKDOWN_KEYS: Final[tuple[str, ...]] = (
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_OTHER,
)

IMPACT_SCOPE_RUNTIME: Final = "runtime"
IMPACT_SCOPE_NON_RUNTIME: Final = "non_runtime"
IMPACT_SCOPE_MIXED: Final = "mixed"

__all__ = [
    "IMPACT_SCOPE_MIXED",
    "IMPACT_SCOPE_NON_RUNTIME",
    "IMPACT_SCOPE_RUNTIME",
    "SOURCE_KIND_BREAKDOWN_KEYS",
    "SOURCE_KIND_FIXTURES",
    "SOURCE_KIND_MIXED",
    "SOURCE_KIND_ORDER",
    "SOURCE_KIND_OTHER",
    "SOURCE_KIND_PRODUCTION",
    "SOURCE_KIND_TESTS",
]
