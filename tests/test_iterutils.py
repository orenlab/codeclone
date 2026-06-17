# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import pytest

from codeclone.utils.iterutils import chunked


def test_chunked_splits_into_size_groups() -> None:
    assert list(chunked([1, 2, 3, 4, 5], 2)) == [(1, 2), (3, 4), (5,)]


def test_chunked_exact_multiple() -> None:
    assert list(chunked(range(4), 2)) == [(0, 1), (2, 3)]


def test_chunked_empty_yields_nothing() -> None:
    assert list(chunked([], 3)) == []


def test_chunked_consumes_lazily_from_iterator() -> None:
    assert list(chunked(iter("abcde"), 3)) == [("a", "b", "c"), ("d", "e")]


def test_chunked_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError, match="size must be"):
        list(chunked([1, 2], 0))
