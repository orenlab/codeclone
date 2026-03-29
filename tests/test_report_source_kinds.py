# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.report._source_kinds import (
    SOURCE_KIND_FILTER_VALUES,
    normalize_source_kind,
    source_kind_label,
)


def test_normalize_source_kind_handles_whitespace_and_empty() -> None:
    assert normalize_source_kind("  Production  ") == "production"
    assert normalize_source_kind("\n") == "other"


def test_source_kind_label_maps_known_and_unknown_values() -> None:
    assert source_kind_label("production") == "Production"
    assert source_kind_label("fixtures") == "Fixtures"
    assert source_kind_label("experimental_scope") == "Experimental_Scope"
    assert source_kind_label("   ") == "Other"


def test_source_kind_filter_values_are_stable_and_unique() -> None:
    assert SOURCE_KIND_FILTER_VALUES == (
        "production",
        "tests",
        "fixtures",
        "mixed",
    )
    assert len(SOURCE_KIND_FILTER_VALUES) == len(set(SOURCE_KIND_FILTER_VALUES))
