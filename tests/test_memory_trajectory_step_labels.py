# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.memory.trajectory.step_labels import step_display_name


def test_step_display_name_uses_catalog_for_known_events() -> None:
    assert step_display_name(event_type="intent.declared", status="active") == (
        "Change intent declared (active)"
    )


def test_step_display_name_falls_back_for_unknown_events() -> None:
    assert step_display_name(event_type="custom.event") == "custom → event"
