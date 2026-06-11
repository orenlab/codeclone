# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import pytest

from codeclone.observability.reason_kind import REASON_KINDS, validate_reason_kind


def test_validate_reason_kind_accepts_known_and_none() -> None:
    assert validate_reason_kind(None) is None
    for kind in sorted(REASON_KINDS):
        assert validate_reason_kind(kind) == kind


def test_validate_reason_kind_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown reason_kind"):
        validate_reason_kind("not-a-kind")
