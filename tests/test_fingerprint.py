# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from codeclone.analysis.fingerprint import bucket_loc, sha1


def test_sha1_stable() -> None:
    assert sha1("abc") == "a9993e364706816aba3e25717850c26c9cd0d89d"


def test_bucket_loc_ranges() -> None:
    assert bucket_loc(0) == "0-19"
    assert bucket_loc(19) == "0-19"
    assert bucket_loc(20) == "20-49"
    assert bucket_loc(49) == "20-49"
    assert bucket_loc(50) == "50-99"
    assert bucket_loc(99) == "50-99"
    assert bucket_loc(100) == "100+"
