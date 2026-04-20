# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.metrics import METRIC_FAMILIES, MetricFamily


def test_registered_metric_families_define_contract_metadata() -> None:
    assert METRIC_FAMILIES
    report_sections: set[str] = set()
    for family_name, family in METRIC_FAMILIES.items():
        assert isinstance(family, MetricFamily)
        assert family.name == family_name
        assert callable(family.compute)
        assert callable(family.aggregate)
        assert family.report_section
        assert family.report_section not in report_sections
        report_sections.add(family.report_section)
