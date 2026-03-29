# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping


def assert_contains_all(text: str, *needles: str) -> None:
    for needle in needles:
        assert needle in text


def assert_mapping_entries(
    mapping: Mapping[str, object],
    /,
    **expected: object,
) -> None:
    for key, value in expected.items():
        assert mapping[key] == value


def snapshot_python_tag(snapshot: Mapping[str, object]) -> str:
    meta = snapshot.get("meta", {})
    assert isinstance(meta, dict)
    python_tag = meta.get("python_tag")
    assert isinstance(python_tag, str)
    return python_tag
