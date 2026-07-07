# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import pytest

from codeclone.utils import payload_narrow


def test_is_payload_dict_preserves_dict_identity() -> None:
    record: dict[str, object] = {"type": "module_role"}
    value: object = record
    assert payload_narrow.is_payload_dict(value)
    assert value is record
    assert not payload_narrow.is_payload_dict("not-a-dict")


def test_is_record_mapping_preserves_mapping_identity() -> None:
    record: dict[str, object] = {"type": "module_role", "statement": "hello"}
    value: object = record
    assert payload_narrow.is_record_mapping(value)
    assert value is record
    assert not payload_narrow.is_record_mapping("not-a-mapping")


def test_mapping_items_from_list_preserves_mapping_identity() -> None:
    numpy = pytest.importorskip("numpy")
    weight = numpy.float32(2.5)
    record: dict[str, object] = {"weight": weight}
    items = payload_narrow.mapping_items_from_list([record])
    assert len(items) == 1
    assert items[0] is record
    assert items[0]["weight"] is weight


def test_dict_items_from_list_preserves_dict_identity() -> None:
    record: dict[str, object] = {"trajectory_id": "t-1"}
    items = payload_narrow.dict_items_from_list([record])
    assert len(items) == 1
    assert items[0] is record


def test_nested_payload_dict_preserves_dict_identity() -> None:
    nested: dict[str, object] = {"p50": 1}
    assert payload_narrow.nested_payload_dict(nested) is nested
    assert payload_narrow.nested_payload_dict("bad") == {}


def test_mapping_items_from_list_rejects_non_list_input() -> None:
    assert payload_narrow.mapping_items_from_list({"not": "a list"}) == []


def test_dict_items_from_list_rejects_non_list_input() -> None:
    assert payload_narrow.dict_items_from_list("not-a-list") == []
